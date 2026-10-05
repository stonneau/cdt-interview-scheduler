"""Sweep framework — parameter-grid generation and parallel experiment execution.

Public API
----------
- :func:`sweep_runner.run_sweep` — execute a parameter sweep across experiments.
- :func:`sweep_runner.run_single_experiment` — run one experiment and return metrics.
- :func:`sweep_scenarios.strategy_comparison_iter` — yield parameter dicts for a
  strategy × size × complexity × noise × seed grid.
- :func:`sweep_scenarios.default_param_iter` — legacy full-grid iterator.
"""

from eval.sweep.sweep_runner import run_sweep, run_single_experiment
from eval.sweep.sweep_scenarios import strategy_comparison_iter, default_param_iter

__all__ = [
    "run_sweep",
    "run_single_experiment",
    "strategy_comparison_iter",
    "default_param_iter",
]
