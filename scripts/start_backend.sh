#!/usr/bin/env bash
# Start the SFT Mission Control backend (also serves the prebuilt frontend on :8000).
set -euo pipefail
cd "$(dirname "$0")/../backend"
export SFT_MODEL_PYTHON="${SFT_MODEL_PYTHON:-$HOME/projects/tawhiri-master/.venv310/bin/python}"
export TAWHIRI_DATA_DIR="${TAWHIRI_DATA_DIR:-$HOME/projects/tawhiri-data}"
export TAWHIRI_API_URL="${TAWHIRI_API_URL:-http://127.0.0.1:5000}"
echo "Model interpreter : $SFT_MODEL_PYTHON"
echo "Weather data dir  : $TAWHIRI_DATA_DIR"
echo "Tawhiri engine    : $TAWHIRI_API_URL (start it with: TZ=UTC tawhiri-webapp runserver)"
exec uvicorn main:app --host 127.0.0.1 --port 8000
