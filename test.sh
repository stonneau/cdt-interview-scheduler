#!/usr/bin/env bash
# Run the test suite. Run `make install` first.
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
"$PY" -m pytest tests/ -q "$@"
