python3 -m unittest discover -s tests
python3 -m eval.harness --applicantscsv data/applicants_availabilities.csv --staffcsv data/staff_aligned_45min.csv
pytest -q tests/test_strategies.py
python3 -m pytest tests/ -v