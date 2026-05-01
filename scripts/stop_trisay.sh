#!/bin/zsh
set -euo pipefail

PORT="8000"
HOST="127.0.0.1"

PIDS=$(lsof -ti TCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)

if [[ -z "$PIDS" ]]; then
  echo "Trisay Lite is not running on port $PORT."
  exit 0
fi

echo "Stopping Trisay Lite (PID: $PIDS)..."
echo "$PIDS" | xargs kill -9
echo "Done. http://$HOST:$PORT is now free."
