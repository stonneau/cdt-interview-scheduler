"""Evaluation framework — metrics, data generation, noise, and experiment harnesses.

Subpackages
-----------
- :mod:`experiments` — demo, robustness, and actual-data experiment runners.
- :mod:`sweep` — parameter-grid generation and parallel sweep execution.
- :mod:`sweep_plots` — sweep CSV analysis and plotting.
- :mod:`produce_plots` — per-run Gantt, bar, Pareto, and heatmap plots.

Top-level modules
-----------------
- :mod:`metrics` — stability and robustness metric computation.
- :mod:`data_generators` — synthetic dataset generation.
- :mod:`noise_generators` — perturbation generators for robustness testing.
- :mod:`change_analyzer` — human-readable change event summaries.
- :mod:`collect_metrics` — per-run metrics aggregation to CSV.
- :mod:`colour_palette` — colorblind-friendly colour definitions.
- :mod:`harness` — CLI orchestrator dispatching to experiment runners.
"""
