#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from python.org or use Homebrew."
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

if [ -z "${PARKVISION_ADMIN_PASSWORD:-}" ]; then
  echo
  echo "Create a private operator password. Do not share it with visitors."
  read -r -s -p "Admin password: " PARKVISION_ADMIN_PASSWORD
  echo
  if [ "${#PARKVISION_ADMIN_PASSWORD}" -lt 12 ]; then
    echo "Use at least 12 characters and run again."
    exit 1
  fi
  export PARKVISION_ADMIN_PASSWORD
fi
if [ -z "${PARKVISION_SECRET_KEY:-}" ]; then
  export PARKVISION_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi
export PARKVISION_MODE="${PARKVISION_MODE:-demo}"

if [ "$PARKVISION_MODE" = "hardware" ] && [ -z "${PARKVISION_SERIAL_PORT:-}" ]; then
  echo "Hardware mode needs PARKVISION_SERIAL_PORT. Example: /dev/cu.usbmodem1101"
  echo "Find it with: ls /dev/cu.*"
  exit 1
fi

echo
 echo "PARKVISION mode: $PARKVISION_MODE"
echo "Open http://127.0.0.1:5000"
echo "Keep this Terminal window running. Press Ctrl+C to stop."
python app.py
