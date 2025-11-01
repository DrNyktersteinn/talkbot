#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TalkBot GUI (Windows/Qt)
- Chat + Vision client for your FastAPI gateway
- Robust pyttsx3 TTS (re-init per utterance, threaded so UI stays snappy)
- Mic can target Chat or Vision
- Vision modes: scene / emotion / navigate / objects
- Saves Host, API key, and chosen voice
"""

import json
import sys
import time
import base64
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple

import requests

# ---- Optional libs with friendly fallbacks ----
try:
    import pyttsx3  # Windows SAPI5
except Exception:
    pyttsx3 = None

try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    import cv2
except Exception:
    cv2 = None

# ---- PyQt6 ----
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QVBoxLayout, QHBoxLayout, QGroupBox
)

APP_NAME = "TalkBot GUI"
SETTINGS_FILE = Path("settings.json")

# ---------------- Settings ----------------

@dataclass
class Settings:
    host: str = ""
    api_key: str = ""
    voice_name: str = ""  # saved by human-readable name

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                return cls(**json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# ---------------- Helpers ----------------

def bgr_to_qimage(bgr) -> Optional[QImage]:
    """cv2 BGR frame -> QImage (RGB)"""
    if bgr is None:
        return None
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    return QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)


def encode_jpeg(frame_bgr) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise RuntimeError("Failed to encode frame as JPEG")
    return buf.tobytes()


# ---------------- Main Window ----------------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings = Settings.load()

        # camera state
        self.cap = None
        self.cam_timer = QTimer(self)
        self.cam_timer.timeout.connect(self._grab_frame)
        self.last_frame = None  # BGR frame

        # tts state
        self._tts_lock = threading.Lock()
        self._last_spoken_text = ""

        self._build_ui()
        self._refresh_voice_list()
        self._log("[Ready] Set Host + API key, then Save/Test.")

    # ---------- UI ----------

    def _build_ui(self):
        root = QHBoxLayout(self)

        # Left: camera pane
        left = QVBoxLayout()
        self.preview = QLabel("Camera preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 320)
        self.preview.setStyleSheet("border: 1px solid #ccc;")
        left.addWidget(self.preview)

        cam_row = QHBoxLayout()
        self.btn_cam = QPushButton("Start Camera")
        self.btn_cam.clicked.connect(self._toggle_camera)
        self.btn_snap = QPushButton("Snap → Vision")
        self.btn_snap.clicked.connect(self._snap_to_vision)
        cam_row.addWidget(self.btn_cam)
        cam_row.addWidget(self.btn_snap)
        left.addLayout(cam_row)

        # Vision controls
        vis_box = QGroupBox("Vision")
        vis_lay = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["scene", "emotion", "navigate", "objects"])
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("Target (for navigate, optional)")
        self.btn_vision = QPushButton("Vision (use last frame)")
        self.btn_vision.clicked.connect(self._vision_click)
        vis_lay.addWidget(QLabel("Mode:"))
        vis_lay.addWidget(self.mode_combo)
        vis_lay.addWidget(QLabel("Target:"))
        vis_lay.addWidget(self.target_edit)
        vis_lay.addWidget(self.btn_vision)
        vis_box.setLayout(vis_lay)
        left.addWidget(vis_box)

        root.addLayout(left, 2)

        # Right: controls + chat + log
        right = QVBoxLayout()

        # Settings row
        settings_row1 = QHBoxLayout()
        self.host_edit = QLineEdit(self.settings.host)
        self.host_edit.setPlaceholderText("https://<your-tunnel>.trycloudflare.com")
        self.key_edit = QLineEdit(self.settings.api_key)
        self.key_edit.setPlaceholderText("64-char API key")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self._save_settings)
        btn_test = QPushButton("Test")
        btn_test.clicked.connect(self._test_health)
        settings_row1.addWidget(QLabel("Host:"))
        settings_row1.addWidget(self.host_edit)
        settings_row1.addWidget(QLabel("API key:"))
        settings_row1.addWidget(self.key_edit)
        settings_row1.addWidget(btn_save)
        settings_row1.addWidget(btn_test)
        right.addLayout(settings_row1)

        # Voice row
        voice_row = QHBoxLayout()
        self.voice_combo = QComboBox()
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        btn_say = QPushButton("🔈 Speak last")
        btn_say.clicked.connect(self._speak_last_text)
        voice_row.addWidget(QLabel("Voice:"))
        voice_row.addWidget(self.voice_combo)
        voice_row.addWidget(btn_say)
        right.addLayout(voice_row)

        # Mic target
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Mic target:"))
        self.mic_target_combo = QComboBox()
        self.mic_target_combo.addItems(["chat", "vision"])
        mic_btn = QPushButton("🎤 Start talking")
        mic_btn.clicked.connect(self._chat_from_mic)
        mic_row.addWidget(self.mic_target_combo)
        mic_row.addWidget(mic_btn)
        right.addLayout(mic_row)

        # Chat row
        chat_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message and press Send")
        btn_send = QPushButton("Send")
        btn_send.clicked.connect(self._send_chat)
        chat_row.addWidget(self.chat_input)
        chat_row.addWidget(btn_send)
        right.addLayout(chat_row)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        right.addWidget(self.log, 1)

        root.addLayout(right, 3)

    # ---------- Logging ----------

    def _log(self, msg: str):
        now = time.strftime("[%H:%M:%S]")
        self.log.append(f"{now} {msg}")

    # ---------- Settings ----------

    def _save_settings(self):
        self.settings.host = self.host_edit.text().strip()
        self.settings.api_key = self.key_edit.text().strip()
        self.settings.save()
        self._log("[Saved] Settings written to settings.json.")

    def _test_health(self):
        try:
            host, _ = self._hk()
        except Exception as e:
            self._log(f"Health check error: {e}")
            return
        try:
            r = requests.get(f"{host}/health", timeout=10)
            self._log(f"Health: {r.status_code} {r.text}")
        except Exception as e:
            self._log(f"Health check error: {e}")

    # ---------- Voice / TTS ----------

    def _refresh_voice_list(self):
        self.voice_combo.clear()
        if pyttsx3 is None:
            self.voice_combo.addItem("(pyttsx3 not available)")
            return
        try:
            eng = pyttsx3.init()
            voices = eng.getProperty("voices")
            names = [v.name for v in voices] if voices else []
            # Put saved voice first if exists
            if self.settings.voice_name and self.settings.voice_name in names:
                idx = names.index(self.settings.voice_name)
            else:
                idx = 0 if names else -1
            for nm in names:
                self.voice_combo.addItem(nm)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
            eng.stop()
            del eng
        except Exception:
            self.voice_combo.addItem("(system default)")

    def _on_voice_changed(self, _idx: int):
        name = self.voice_combo.currentText()
        if not name or name.startswith("("):
            self.settings.voice_name = ""
        else:
            self.settings.voice_name = name
        self.settings.save()
        self._log(f"Voice set: {self.settings.voice_name or 'system default'}")

    def _speak_async(self, text: str):
        # speak on a background thread (prevents UI freezes)
        if not text or pyttsx3 is None:
            return

        def run():
            try:
                with self._tts_lock:
                    eng = pyttsx3.init()
                    target_name = (self.settings.voice_name or "").strip()
                    if target_name:
                        try:
                            for v in eng.getProperty("voices"):
                                if v.name == target_name:
                                    eng.setProperty("voice", v.id)
                                    break
                        except Exception:
                            pass
                    eng.say(text)
                    eng.runAndWait()
                    eng.stop()
                    del eng
            except Exception as e:
                self._log(f"TTS error: {e}")

        self._last_spoken_text = text
        threading.Thread(target=run, daemon=True).start()

    def _speak_last_text(self):
        if self._last_spoken_text:
            self._speak_async(self._last_spoken_text)
            return

        lines = self.log.toPlainText().splitlines()
        for line in reversed(lines):
            s = line.strip()
            if s.startswith("Assistant:") or s.startswith("Vision:"):
                content = s.split(":", 1)[1].strip()
                if content:
                    self._speak_async(content)
                    return
        for line in reversed(lines):
            s = line.strip()
            if s:
                self._speak_async(s)
                return
        self._log("Nothing to speak yet.")

    # ---------- HTTP helpers ----------

    def _hk(self) -> Tuple[str, str]:
        host = self.host_edit.text().strip() or self.settings.host.strip()
        key = self.key_edit.text().strip() or self.settings.api_key.strip()
        if not host or not key:
            raise RuntimeError("Host or API key missing.")
        return host, key

    def _post_chat(self, host: str, key: str, text: str) -> dict:
        r = requests.post(
            f"{host}/chat",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"text": text, "voice_id": self.settings.voice_name or "en_US-amy-medium"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def _post_vision(self, host: str, key: str, frame_bgr, prompt: str,
                     mode: str, target: str) -> dict:
        # Encode frame to JPEG
        jpeg_bytes = encode_jpeg(frame_bgr)
        files = {
            "image": ("frame.jpg", jpeg_bytes, "image/jpeg")
        }
        data = {
            "prompt": prompt or "",
            "mode": (mode or "scene").lower(),
            "target": target or "",
            "voice_id": self.settings.voice_name or "en_US-amy-medium",
        }
        r = requests.post(
            f"{host}/vision",
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=90,
        )
        r.raise_for_status()
        return r.json()

    # ---------- Chat / Vision actions ----------

    def _send_chat(self):
        try:
            host, key = self._hk()
        except Exception as e:
            self._log(f"Chat error: {e}")
            return
        text = self.chat_input.text().strip()
        if not text:
            return
        self._log(f"You: {text}")
        try:
            res = self._post_chat(host, key, text)
            msg = (res or {}).get("text", "").strip()
            if msg:
                self._log(f"Assistant: {msg}")
                self._speak_async(msg)
            else:
                self._log("Assistant: (empty)")
        except requests.exceptions.HTTPError as e:
            self._log(f"Chat error: {e} | Body: {getattr(e.response, 'text', '')}")
        except Exception as e:
            self._log(f"Chat error: {e}")

    def _vision_click(self):
        if self.last_frame is None:
            self._log("No frame. Start Camera or Snap first.")
            return
        self._vision_with_frame(self.last_frame,
                                self.mode_combo.currentText(),
                                self.target_edit.text().strip(),
                                prompt="")

    def _snap_to_vision(self):
        if self.last_frame is None:
            self._log("No frame yet.")
            return
        self._vision_with_frame(self.last_frame,
                                self.mode_combo.currentText(),
                                self.target_edit.text().strip(),
                                prompt="")

    def _vision_with_frame(self, frame_bgr, mode: str, target: str, prompt: str):
        try:
            host, key = self._hk()
        except Exception as e:
            self._log(f"Vision error: {e}")
            return

        # Default prompt guidance; backend also adds hints
        user_prompt = prompt or {
            "scene": "Describe the scene briefly for navigation.",
            "emotion": "Describe the likely facial expression and overall emotion.",
            "navigate": f"How to navigate toward {target or 'the target'} in the scene?",
            "objects": "List the main objects present with short positions.",
        }.get((mode or "scene").lower(), "Describe the scene briefly for navigation.")

        try:
            res = self._post_vision(host, key, frame_bgr, user_prompt, mode, target)
            text = (res or {}).get("text", "").strip()
            if text:
                self._log(f"Vision:\n{text}")
                self._speak_async(text)
            else:
                self._log("Vision: (empty response).")
        except requests.exceptions.HTTPError as e:
            self._log(f"Vision error: {e} | Body: {getattr(e.response, 'text', '')}")
        except requests.exceptions.ConnectionError as e:
            self._log(f"Vision error: connection failed ({e})")
        except Exception as e:
            self._log(f"Vision error: {e}")

    # ---------- Mic (STT) ----------

    def _chat_from_mic(self):
        if sr is None:
            self._log("STT not available. Install: SpeechRecognition + PyAudio")
            return
        target = (self.mic_target_combo.currentText() or "chat").lower()
        r = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                self._log("Listening… (speak now)")
                r.adjust_for_ambient_noise(source, duration=0.5)
                audio = r.listen(source, timeout=6, phrase_time_limit=10)
            try:
                transcript = r.recognize_google(audio)
            except sr.UnknownValueError:
                self._log("Sorry, I couldn't understand your speech.")
                return
            except sr.RequestError as e:
                self._log(f"Speech service error: {e}")
                return
        except Exception as e:
            self._log(f"Mic error: {e}")
            return

        if target == "vision":
            if self.last_frame is None:
                self._log("No camera frame. Start Camera and try again.")
                return
            self._vision_with_frame(
                self.last_frame,
                self.mode_combo.currentText(),
                self.target_edit.text().strip(),
                prompt=transcript
            )
        else:
            self.chat_input.setText(transcript)
            self._send_chat()

    # ---------- Camera ----------

    def _toggle_camera(self):
        if cv2 is None:
            self._log("OpenCV not available. Install opencv-python.")
            return
        if self.cap is None:
            try:
                self.cap = cv2.VideoCapture(0)
                if not self.cap.isOpened():
                    self.cap.release()
                    self.cap = None
                    self._log("Could not open webcam.")
                    return
                self.cam_timer.start(33)  # ~30fps preview
                self.btn_cam.setText("Stop Camera")
            except Exception as e:
                self._log(f"Camera error: {e}")
        else:
            self.cam_timer.stop()
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            self.btn_cam.setText("Start Camera")
            self.preview.setText("Camera preview")
            self.last_frame = None

    def _grab_frame(self):
        if self.cap is None:
            return
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return
        self.last_frame = frame
        qim = bgr_to_qimage(frame)
        if qim:
            pix = QPixmap.fromImage(qim).scaled(
                self.preview.width(),
                self.preview.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview.setPixmap(pix)


# ---------------- main ----------------

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(1080, 640)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
