"""Experiment harnesses — demo, robustness, and actual-data runners.

Public API
----------
- :func:`demo_small.run_demo_small` — small demo on CSV or synthetic data.
- :func:`demo_small.run_generated_demo` — demo on synthetically generated data.
- :func:`demo_actual_data.run_actual_data_demo` — demo with real CSV data.
- :func:`robustness_experiment.run_experiment` — Monte-Carlo robustness test.
"""

from eval.experiments.demo_small import run_demo_small, run_generated_demo
from eval.experiments.demo_actual_data import run_actual_data_demo
from eval.experiments.robustness_experiment import run_experiment

__all__ = [
    "run_demo_small",
    "run_generated_demo",
    "run_actual_data_demo",
    "run_experiment",
]
