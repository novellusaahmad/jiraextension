#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
export FLASK_APP=app.py
flask run --host=0.0.0.0 --port=8505
