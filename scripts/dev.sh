#!/bin/bash
# Start JamRecall locally: API on 127.0.0.1:$JAMRECALL_API_PORT (default 8700), app on
# http://127.0.0.1:$JAMRECALL_WEB_PORT (default 5173).
# First run installs the backend venv (backend/install.sh) and frontend packages (npm ci).
# Ctrl-C stops both. Data: $JAMRECALL_DATA_DIR (default <repo>/var).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Node >= 20.19 is required (Vite 8). Use nvm with .nvmrc if the current node is older.
node_ok() { command -v node >/dev/null && node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)'; }
if ! node_ok; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    nvm use "$(cat .nvmrc)" >/dev/null || { echo "Install Node $(cat .nvmrc): nvm install $(cat .nvmrc)"; exit 1; }
  fi
fi
node_ok || { echo "Node >= 20.19 required (found $(node -v 2>/dev/null || echo none))"; exit 1; }

[ -x backend/.venv/bin/python ] || sh backend/install.sh
[ -d frontend/node_modules ] || (cd frontend && npm ci)

API_PORT="${JAMRECALL_API_PORT:-8700}"
WEB_PORT="${JAMRECALL_WEB_PORT:-5173}"
for port in "$API_PORT" "$WEB_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use by another program:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN | tail -n +2
    echo "Stop it, or choose other ports: JAMRECALL_API_PORT=... JAMRECALL_WEB_PORT=... $0"
    exit 1
  fi
done

echo "Data directory: ${JAMRECALL_DATA_DIR:-$ROOT/var}"
backend/.venv/bin/python -m uvicorn --factory jamrecall.app:get_app --host 127.0.0.1 \
  --port "$API_PORT" --app-dir backend &
BACK=$!
trap 'kill $BACK ${FRONT:-} 2>/dev/null; wait 2>/dev/null' INT TERM EXIT
echo "Starting the API (loads the Basic Pitch model, ~5 s)…"
ready=""
for _ in $(seq 1 120); do
  kill -0 "$BACK" 2>/dev/null || { echo "The API exited during startup (see messages above)."; exit 1; }
  # Check it is JamRecall answering, not some other server.
  if curl -sf "http://127.0.0.1:$API_PORT/api/config" | grep -q '"accepted_mime_types"'; then ready=1; break; fi
  sleep 0.5
done
[ -n "$ready" ] || { echo "The API did not become ready on port $API_PORT."; exit 1; }
(cd frontend && JAMRECALL_API_URL="http://127.0.0.1:$API_PORT" JAMRECALL_WEB_PORT="$WEB_PORT" \
  npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort) &
FRONT=$!
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$WEB_PORT/api/config" | grep -q '"accepted_mime_types"' && break; sleep 0.5
done
echo
echo "JamRecall is running: open http://127.0.0.1:$WEB_PORT in Chrome.  (Ctrl-C to stop)"
wait
