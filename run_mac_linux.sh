#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
echo 'Tin\x27s Takoyaki: open http://127.0.0.1:5000'
exec .venv/bin/python app.py
