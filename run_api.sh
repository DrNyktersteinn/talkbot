#!/usr/bin/env bash
set -e
export TALKBOT_DATA_DIR="$HOME/talkbot/runtime"
export API_KEYS_FILE="$HOME/talkbot/runtime/api_keys.txt"
export OLLAMA_URL="http://127.0.0.1:11434"
export CHAT_MODEL="mistral:latest"
# pick one you actually have pulled: moondream:latest, moondream2:latest, or llava:latest
export VISION_MODEL="moondream:latest"

# free the port if a crashed reloader is hanging around
fuser -k 8081/tcp 2>/dev/null || true
pkill -f "uvicorn .*8081" 2>/dev/null || true
sleep 1

python -m uvicorn gateway.main:api --host 0.0.0.0 --port 8081 --reload
