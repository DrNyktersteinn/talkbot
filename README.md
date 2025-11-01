
---

# TalkBot (Chat + Vision)

FastAPI gateway on a Linux VM (with Ollama vision + chat models), plus a simple Windows/Qt GUI client that does:

* Text chat (Mistral via Ollama)
* Vision prompts (scene / emotion / navigate / objects) with webcam snapshots
* Local TTS (pyttsx3) and optional mic STT (SpeechRecognition + PyAudio)

> **Repo layout (high-level)**
>
> * `gateway/` – FastAPI app (uvicorn)
> * `talkbot_gui.py` – Windows Qt GUI client
> * `run_api.sh` – helper to start the API on the VM
> * `appdata/piper/` – local TTS voices (optional, server side)
> * `runtime/` – API keys and runtime files (ignored by git)

---

## 0) Requirements

### VM (Linux, tested on Ubuntu)

* Python 3.10+ (we used 3.13 via Miniconda)
* `pip` and `uvicorn`, `fastapi`, `httpx`
* [Ollama](https://ollama.ai) running on the VM (defaults to `http://127.0.0.1:11434`)
* Optional: `cloudflared` to expose your API over HTTPS

### Windows laptop (client)

* Python 3.11+
* Webcam + microphone
* Packages: `PyQt6`, `requests`, `pyttsx3` (TTS), `opencv-python`
* Optional STT: `SpeechRecognition`, `PyAudio`

---

## 1) VM: Clone & set up the API

```bash
# SSH into the VM, then:
cd ~
git clone https://github.com/DrNyktersteinn/talkbot.git
cd talkbot

# (Recommended) use a venv or conda env
python -m venv .venv
source .venv/bin/activate

pip install -r gateway/requirements.txt
# If requirements.txt is not present or minimal, ensure:
pip install fastapi uvicorn httpx pillow
```

Create your API key file (64-char random is fine):

```bash
mkdir -p runtime
echo 'YOUR_64_CHAR_TOKEN_HERE' > runtime/api_keys.txt
```

Pull models in Ollama (on the VM):

```bash
# Chat model:
ollama pull mistral:latest

# Vision model (pick at least one):
ollama pull moondream:latest
# Optional stronger model (larger download/VRAM):
ollama pull llava:latest
```

Quick test Ollama:

```bash
curl -s http://127.0.0.1:11434/api/version
curl -s http://127.0.0.1:11434/api/tags
```

Start the API (foreground):

```bash
# stop anything on 8081
fuser -k 8081/tcp 2>/dev/null || true

TALKBOT_DATA_DIR="$HOME/talkbot/runtime" \
API_KEYS_FILE="$HOME/talkbot/runtime/api_keys.txt" \
OLLAMA_URL="http://127.0.0.1:11434" \
CHAT_MODEL="mistral:latest" \
VISION_MODEL="moondream:latest" \
python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload
```

Health check (from the VM):

```bash
curl -s http://127.0.0.1:8081/health
```

Auth check (replace with your key):

```bash
KEY="$(cat runtime/api_keys.txt)"
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8081/_authdebug | python -m json.tool
```

> **Tip:** Use `run_api.sh` if included:
>
> ```bash
> chmod +x run_api.sh
> ./run_api.sh
> ```

 Expose via Cloudflare Tunnel

```bash
# Download cloudflared if not installed
cd ~/talkbot
curl -LO https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64

# Start a one-off tunnel
./cloudflared-linux-amd64 tunnel --url http://127.0.0.1:8081
# Copy the https://<something>.trycloudflare.com URL it prints
```

---

## 2) Windows: set up and run the GUI

Clone the same repo or just copy `talkbot_gui.py`:

```powershell
cd "C:\Users\<you>\Desktop\TalkBot"
python -m venv .venv
. .\.venv\Scripts\Activate.ps1

pip install PyQt6 requests pyttsx3 opencv-python
# Optional STT:
pip install SpeechRecognition PyAudio==0.2.14
```

Run the GUI:

```powershell
python .\talkbot_gui.py
```

In the GUI:

1. Paste **Host**:

   * If using the tunnel: `https://<your-subdomain>.trycloudflare.com`
   * If on the same LAN and port is open: `http://<VM-IP>:8081`
2. Paste **API key** (same value you put in the VM’s `runtime/api_keys.txt`)
3. Click **Save** then **Test**
4. Use **Start Camera** → **Snap → Vision** or click **Vision (use last frame)**
5. Choose **Mode**: scene / emotion / navigate / objects
6. Voice list (Windows SAPI) is selectable at top; click **🔈 Speak last** to replay

> **Mic target**: choose **chat** or **vision** before pressing “🎤 Start talking”.

---

## 3) Quick API checks from any machine

```bash
# Health (no auth needed)
curl -s https://<tunnel>/health

# Auth (should show token_len: 64 and loaded_keys: 1)
curl -s -H "Authorization: Bearer <YOUR_KEY>" https://<tunnel>/_authdebug

# Chat
curl -s -H "Authorization: Bearer <YOUR_KEY>" -H "Content-Type: application/json" \
  -d '{"text":"hello"}' https://<tunnel>/chat | python -m json.tool

# Vision (multipart)
curl -s -H "Authorization: Bearer <YOUR_KEY>" \
  -F "image=@sample.jpg;type=image/jpeg" -F "mode=scene" \
  https://<tunnel>/vision | python -m json.tool
```

---

## 4) After reboot (“cold start”)

On the VM:

```bash
# Start Ollama (if needed)
sudo systemctl start ollama 2>/dev/null || true

# Start the API
cd ~/talkbot
source .venv/bin/activate
fuser -k 8081/tcp 2>/dev/null || true
TALKBOT_DATA_DIR="$HOME/talkbot/runtime" \
API_KEYS_FILE="$HOME/talkbot/runtime/api_keys.txt" \
OLLAMA_URL="http://127.0.0.1:11434" \
CHAT_MODEL="mistral:latest" \
VISION_MODEL="moondream:latest" \
python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload
```

If you use Cloudflare, start it again to get a **new** temporary URL:

```bash
cd ~/talkbot
./cloudflared-linux-amd64 tunnel --url http://127.0.0.1:8081
```

Paste the new URL into the GUI and click **Save**.

---

## 5) Updating code & backing up

### Pull latest changes (on VM):

```bash
cd ~/talkbot
git pull
# Restart the API (CTRL+C then run start command again)
```

### Save a snapshot to your GitHub

```bash
cd ~/talkbot
git checkout -B main
git add -A
git commit -m "Update: <describe change>"
git push -u origin main
```

> Make sure `runtime/api_keys.txt` stays out of git (already in `.gitignore`).

---

## 6) Troubleshooting

**403 Invalid API key**

* The GUI must send the **same key** stored in `~/talkbot/runtime/api_keys.txt`.
* Test with:
  `curl -s -H "Authorization: Bearer <KEY>" https://<tunnel>/_authdebug`

**500 Internal Server Error (chat/vision)**

* Tail server logs in the VM terminal running uvicorn; most issues are upstream model errors or temporary TTS errors.
* Use diagnostic endpoints (if present): `/chat_diag`, `/vision_diag`.

**“Could not find PyAudio” (on Windows)**

* You can still use the GUI without mic STT.
* To enable STT: `pip install SpeechRecognition PyAudio==0.2.14`

**Tunnel URL stops working / NameResolutionError**

* The Cloudflare URL changes every time you restart `cloudflared`.
* Start the tunnel again and paste the **new** URL in the GUI.

**Vision returns empty sometimes**

* Switch model: try `llava:latest` if downloaded.
* Ensure JPEG frames are reaching the API (see VM logs).
* Lower latency: keep the API process warm; the first call after idle can be slower.

**Camera not opening (Windows)**

* Close other apps using the camera.
* Ensure `opencv-python` is installed in the same venv you run the GUI.

---

## 7) Changing models (server)

You can swap models via environment variables when starting uvicorn:

```bash
# Example: use LLAVA for vision
VISION_MODEL="llava:latest" \
CHAT_MODEL="mistral:latest" \
python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload
```

Pull before using:

```bash
ollama pull llava:latest
```

---

## 8) Security notes

* Keep `runtime/api_keys.txt` **out** of version control.
* If you ever paste your API key or a GitHub PAT publicly, revoke it immediately and create a new one.
* Tunnels are public: treat your API key like a password.

---

## 9) Support scripts

* **`run_api.sh`** (if present) shows a known-good start command with environment variables.
* **`sample.jpg`** is included for quick vision checks.

---

## 10) Contact & License

* Maintainer: **DrNyktersteinn** (`amalmadhuam@gmail.com`)


---

How to add features or make changes
1) Quick map of the codebase

gateway/main.py – FastAPI server that exposes:

POST /chat – sends your text to the chat model (Mistral by default)

POST /vision – sends an image + a mode (scene | emotion | navigate | objects) to the vision model

Auth is via Bearer token (the string in runtime/api_keys.txt)

Models and host are set via environment variables at startup

talkbot_gui.py – Windows/Qt GUI client:

Camera preview + “Snap → Vision”

Dropdown for Mode

Local TTS (pyttsx3)

Optional mic STT (SpeechRecognition + PyAudio)

Sends requests to the VM gateway URL you paste into the app

Tip: the server and GUI are loosely coupled over HTTP. You can evolve them independently: just keep the same endpoints and fields.

2) Typical changes you might want
A) Add a new Vision mode (server + GUI)

Server (VM) – gateway/main.py

In the existing /vision route, you’ll see logic that reads mode from the form/JSON and builds a prompt. Look for a mapping or if/elif that switches on mode.

Add a new mode, e.g. count:

# inside /vision handler, where prompt is built:
mode = (mode or "scene").lower()

if mode == "scene":
    sys_hint = "Describe the scene briefly for navigation."
elif mode == "emotion":
    sys_hint = "Describe the likely facial expression and overall emotion."
elif mode == "navigate":
    target = (payload or {}).get("target") or (target or "")
    sys_hint = f"How would you navigate toward {target or 'the target'}? Mention obstacles and directions."
elif mode == "objects":
    sys_hint = "List the main objects and their approximate positions (e.g., 'mug - bottom-right'). Keep it short."
elif mode == "count":  # <--- NEW
    sys_hint = "Count people and visible key objects. Return a compact list like 'people: N, chairs: M, screens: K'."
else:
    sys_hint = "Describe the scene briefly."


No other server changes are required—your gateway will keep sending the image bytes to Ollama’s /api/chat with images:[<b64>].

GUI (Windows) – talkbot_gui.py

Add the mode to the dropdown and give it a default prompt:

# 1) When building the UI:
self.mode_combo.addItems(["scene", "emotion", "navigate", "objects", "count"])

# 2) When deciding the default user prompt (in _vision_with_frame):
user_prompt = prompt or {
    "scene": "Describe the scene briefly for navigation.",
    "emotion": "Describe the likely facial expression and overall emotion.",
    "navigate": f"How to navigate toward {target or 'the target'} in the scene?",
    "objects": "List the main objects present with short positions.",
    "count": "Count people and visible key objects. Keep it compact.",  # NEW
}.get((mode or "scene").lower(), "Describe the scene briefly for navigation.")


Re-run the API and GUI; select count in the mode list and Snap → Vision.

B) Add a new endpoint on the server (e.g., /summarize)

Server

# gateway/main.py
from fastapi import FastAPI, Header, HTTPException
api = FastAPI()

@api.post("/summarize")
async def summarize(payload: dict, authorization: str | None = Header(None)):
    _require_key(authorization)  # same auth gate as others
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    sys_prompt = "You are a concise summarizer. 3 bullets max."
    summary = await ollama_chat(
        CHAT_MODEL,
        [{"role":"system","content":sys_prompt},
         {"role":"user","content":text}]
    )
    return {"summary": summary}


GUI (optional)
Add a new button and handler that POSTs to /summarize with a text box’s content.

C) Swap or pin models (server)

When you start uvicorn, set the env vars:

CHAT_MODEL="mistral:latest" \
VISION_MODEL="llava:latest" \
python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload


Pull before switching:

ollama pull llava:latest


You can even add a fallback in your /vision code: if model A returns empty content, automatically retry with model B.

D) Improve TTS reliability (GUI)

The GUI already re-inits pyttsx3 per utterance. If you want a volume/rate slider:

eng = pyttsx3.init()
eng.setProperty("rate", 180)   # default ~200
eng.setProperty("volume", 0.9) # 0.0 - 1.0


Add sliders in the UI and store in Settings so users can tweak.

E) Add wake-words, continuous listening, or STT to Vision

The GUI already has mic → chat or mic → vision (select in the combo).

To make Vision the default mic target, set the combo default to “vision”.

For wake-word, you’d add a background thread listening and trigger _chat_from_mic().

3) Dev loop (run & test quickly)
Server (VM)
cd ~/talkbot
source .venv/bin/activate
fuser -k 8081/tcp 2>/dev/null || true

# Change models or keep defaults:
CHAT_MODEL="mistral:latest" \
VISION_MODEL="moondream:latest" \
python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload


Test:

KEY="$(cat runtime/api_keys.txt)"

# Chat
curl -s -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"text":"hello"}' http://127.0.0.1:8081/chat | python -m json.tool

# Vision (scene)
curl -s -H "Authorization: Bearer $KEY" \
  -F "image=@sample.jpg;type=image/jpeg" \
  -F "mode=scene" http://127.0.0.1:8081/vision | python -m json.tool

GUI (Windows)
cd C:\path\to\repo
. .\.venv\Scripts\Activate.ps1
python .\talkbot_gui.py


Paste the VM tunnel URL (or VM IP if reachable) and your API key, Save → Test.

4) Coding style & structure

Keep server logic small & focused in the route handlers.

For bigger features, split helpers into a gateway/utils.py and import into main.py.

Prefer async IO (already using httpx.AsyncClient).

5) Version control & GitHub flow

On the VM (or locally if you dev there):

cd ~/talkbot
git checkout -b feature/new-vision-mode
# edit gateway/main.py and/or talkbot_gui.py

git add -A
git commit -m "feat(vision): add 'count' mode"
git push -u origin feature/new-vision-mode


Open a Pull Request on GitHub from feature/new-vision-mode → main.

Secrets: runtime/api_keys.txt is already in .gitignore—never commit it.

6) Releasing/Sharing

Update the README if you add new modes/endpoints.

If you change the GUI’s required packages, list them in a requirements-client.txt (optional).

If you change the server’s dependencies, update gateway/requirements.txt.

7) Common pitfalls (and fixes)

403 Invalid API key: the GUI must use the exact string in runtime/api_keys.txt. Test / _authdebug.

Empty Vision text: try a different model (llava:latest), or add a retry fallback in server code.

Latency spikes: first call “warms” the model. Send a /health or trivial chat at startup.

Tunnel stops working: start a fresh cloudflared session; the URL changes each time.

Mic errors: you can run without STT. To enable, pip install SpeechRecognition PyAudio==0.2.14.
