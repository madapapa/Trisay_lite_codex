#!/bin/zsh
set -euo pipefail
unsetopt BG_NICE 2>/dev/null || true

PROJECT_ROOT="/Users/vtl/project/codex/trisay_lite"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_INDEX="$PROJECT_ROOT/frontend/dist/index.html"
LOG_DIR="$PROJECT_ROOT/storage/logs"
LOG_FILE="$LOG_DIR/trisay_lite.log"
HOST="127.0.0.1"
PORT="8000"
URL="http://$HOST:$PORT"

is_server_listening() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q "$HOST:$PORT"
}

mkdir -p "$LOG_DIR"

if [[ ! -x "$BACKEND_DIR/.venv/bin/uvicorn" ]]; then
  echo "Backend virtual environment is missing. Expected $BACKEND_DIR/.venv/bin/uvicorn" >&2
  exit 1
fi

if [[ ! -f "$FRONTEND_INDEX" ]]; then
  echo "Production frontend is missing. Run: cd $PROJECT_ROOT/frontend && npm run build" >&2
  exit 1
fi

if is_server_listening; then
  echo "Trisay Lite is already running at $URL"
  exit 0
fi

# Inject Homebrew paths so ffmpeg/ffprobe are visible when launched from a
# macOS GUI app (Spotlight / Finder), which only inherits a minimal PATH.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

cd "$BACKEND_DIR"
nohup "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" >> "$LOG_FILE" 2>&1 &

echo "Starting Trisay Lite at $URL"
echo "Logs: $LOG_FILE"
