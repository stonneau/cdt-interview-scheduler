"""Plot utilities for sweep outputs (Pareto and summaries).

Generates analysis-ready charts from the flat CSV produced by sweep_runner:
  - Pareto frontier (stability vs fairness)
  - Box-plot of changed assignments by strategy
  - Bar chart of staff fairness variance by strategy
  - Grouped bar charts broken down by noise, size, and complexity
  - Solve-time, proportion changed, Gini coefficient, staff load range plots
  - Summary lookup tables (CSV) with median values per strategy x dimension

Usage::

    python3 -m eval.sweep_plots --csv data/sweep_results.csv --out outputs/sweep
"""

# Re-export every public symbol so that ``from eval.sweep_plots import X``
# continues to work after the monolithic file was split into sub-modules.

from eval.sweep_plots._helpers import (
    _safe_float,
    _feasible_only,
    _group_by,
    _METRIC_DEFS,
    _MEAN_AGG_METRICS,
)

from eval.sweep_plots._metric_plots import (
    plot_boxplot_changed,
    plot_fairness_bar,
    plot_solve_time_bar,
    plot_prop_changed_boxplot,
    plot_gini_bar,
    plot_staff_load_range,
    plot_infeasibility_bar,
    plot_metric_vs_noise_level,
)

from eval.sweep_plots._dimension_plots import (
    _grouped_bar,
    _dimension_breakdown,
    plot_by_noise,
    plot_by_noise_level,
    plot_by_size,
    plot_by_complexity,
    plot_by_penalty_scale,
)

from eval.sweep_plots._pareto_plots import (
    plot_pareto_by_penalty_scale,
    plot_pareto_ps_fw_interaction,
)

from eval.sweep_plots._summary import (
    generate_summary_tables,
    _export_summary_latex,
    generate_recommendation_table,
)

from eval.sweep_plots._io import (
    load_sweep_csv,
    build_pareto_points,
    plot_pareto_from_csv,
    main,
)

__all__ = [
    # Helpers
    "_safe_float",
    "_feasible_only",
    "_group_by",
    "_METRIC_DEFS",
    "_MEAN_AGG_METRICS",
    # Metric plots
    "plot_boxplot_changed",
    "plot_fairness_bar",
    "plot_solve_time_bar",
    "plot_prop_changed_boxplot",
    "plot_gini_bar",
    "plot_staff_load_range",
    "plot_infeasibility_bar",
    "plot_metric_vs_noise_level",
    # Dimension plots
    "_grouped_bar",
    "_dimension_breakdown",
    "plot_by_noise",
    "plot_by_noise_level",
    "plot_by_size",
    "plot_by_complexity",
    "plot_by_penalty_scale",
    # Pareto plots
    "plot_pareto_by_penalty_scale",
    "plot_pareto_ps_fw_interaction",
    # Summary
    "generate_summary_tables",
    "_export_summary_latex",
    "generate_recommendation_table",
    # IO
    "load_sweep_csv",
    "build_pareto_points",
    "plot_pareto_from_csv",
    "main",
]
