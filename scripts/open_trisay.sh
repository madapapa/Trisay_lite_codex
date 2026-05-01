#!/bin/zsh
set -euo pipefail
unsetopt BG_NICE 2>/dev/null || true

PROJECT_ROOT="/Users/vtl/project/codex/trisay_lite"
URL="http://127.0.0.1:8000"
PORT="8000"

is_server_listening() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q "127.0.0.1:$PORT"
}

"$PROJECT_ROOT/scripts/start_trisay.sh"

for _ in {1..40}; do
  if is_server_listening; then
    open "$URL"
    exit 0
  fi
  sleep 0.25
done

echo "Trisay Lite did not become ready at $URL" >&2
exit 1
