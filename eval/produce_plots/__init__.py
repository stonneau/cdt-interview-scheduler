"""Plotting utilities for demo outputs.

Produces Gantt-like candidate movement plots, bar chart of changed assignments
per strategy, a solver-time plot and a Pareto scatter if sweep data present.

Usage:
    python3 -m eval.produce_plots --base data/demo_out --out outputs/demo
"""

from eval.produce_plots._utils import (
    load_schedules,
    ensure_outdir,
    compute_num_changed,
    infer_change_idx,
)
from eval.produce_plots._gantt import (
    plot_gantt,
    extract_staff_by_slot,
    plot_staff_gantt,
)
from eval.produce_plots._bars import plot_bars
from eval.produce_plots._pareto import (
    plot_pareto,
    plot_pareto_regions,
    plot_pareto_regions_zoomed,
    _convex_hull,
)
from eval.produce_plots._heatmap import plot_staff_heatmap
from eval.produce_plots._timing import plot_solver_times
from eval.produce_plots._orchestrator import main

__all__ = [
    "load_schedules",
    "ensure_outdir",
    "compute_num_changed",
    "infer_change_idx",
    "plot_gantt",
    "extract_staff_by_slot",
    "plot_staff_gantt",
    "plot_bars",
    "plot_pareto",
    "plot_pareto_regions",
    "plot_pareto_regions_zoomed",
    "_convex_hull",
    "plot_staff_heatmap",
    "plot_solver_times",
    "main",
]
