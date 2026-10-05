# Convenience targets. Requires Python >= 3.11 (tested with 3.13).
VENV   ?= .venv
PYTHON ?= python3
PY     := $(VENV)/bin/python

.PHONY: install test demo web cdt-data cdt bench clean

install:  ## Create .venv and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

test:  ## Run the test suite
	$(PY) -m pytest tests/ -q

demo:  ## Quick end-to-end demo (small dataset, several strategies)
	$(PY) -m eval.harness

web:  ## Start the Streamlit web app on http://localhost:8501
	$(VENV)/bin/streamlit run ui/web_app.py

cdt-data:  ## Generate the anonymised CDT-scale example data in data/cdt_example
	$(PY) examples/make_cdt_example_data.py

cdt:  ## Run the CDT walkthrough (initial schedule + 3 disruptions)
	$(PY) examples/cdt_walkthrough.py

bench:  ## Compare the CP-SAT and MIP backends at CDT scale
	$(PY) examples/benchmark_backends.py

clean:  ## Remove generated runs and caches
	rm -rf data/run-* data/demo-* data/sweeps .pytest_cache
	find . -name __pycache__ -not -path './$(VENV)/*' -prune -exec rm -rf {} +
