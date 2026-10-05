#!/usr/bin/env bash
# Interactive CLI on the small demo dataset. Run `make install` first.
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
"$PY" -m ui.cli \
  --applicantscsv data/demo_small/applicants_availabilities.csv \
  --staffcsv data/demo_small/staff_aligned_45min.csv \
  --interactive "$@"
