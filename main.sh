#!/usr/bin/env bash
# Interactive CLI on the CDT-scale example data (generated on first use). Run `make install` first.
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
[ -f data/cdt_example/applicants_availabilities.csv ] || "$PY" examples/make_cdt_example_data.py
"$PY" -m ui.cli \
  --applicantscsv data/cdt_example/applicants_availabilities.csv \
  --staffcsv data/cdt_example/staff_availabilities.csv \
  --forbidden-pairs data/cdt_example/forbidden_pairs.csv \
  --fairness min_dev --interactive "$@"
