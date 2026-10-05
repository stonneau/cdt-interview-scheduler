"""Dimension-breakdown grouped bar charts for sweep analysis.

Generates grouped bar charts that break metrics down by a dimension
such as noise type, noise level, dataset size, complexity, or penalty
scale.
"""
from pathlib import Path
from typing import List, Dict, Any

from eval.sweep_plots._helpers import (
    _safe_float, _feasible_only, _group_by, _MEAN_AGG_METRICS,
)


def _grouped_bar(
    rows: List[Dict[str, Any]],
    group_key: str,
    metric_key: str,
    ylabel: str,
    title: str,
    filename: str,
    out_dir: str,
):
    """Plot a grouped bar chart for a single metric across a dimension.

    One bar group per *group_key* value, one bar per strategy, showing the
    median (or mean for rate metrics) of *metric_key*.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    group_key : str
        Column name to group the x-axis by.
    metric_key : str
        Column name of the metric to aggregate.
    ylabel : str
        Label for the y-axis.
    title : str
        Chart title.
    filename : str
        Output file name (e.g. ``"changed_assignments_by_noise_type.png"``).
    out_dir : str
        Directory to write the output PNG.

    Returns
    -------
    None
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        print(f"matplotlib not available; skipping {filename}")
        return

    by_group = _group_by(rows, group_key)
    group_labels = sorted(by_group.keys())
    if not group_labels:
        return

    all_strategies: set = set()
    for grp_rows in by_group.values():
        for r in grp_rows:
            all_strategies.add(r.get("strategy", "unknown"))
    strategies = sorted(all_strategies)

    n_groups = len(group_labels)
    n_strats = len(strategies)
    if n_groups == 0 or n_strats == 0:
        return

    use_mean = metric_key in _MEAN_AGG_METRICS
    agg_fn = np.mean if use_mean else np.median

    x = np.arange(n_groups)
    width = 0.8 / n_strats

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, n_groups * 2), 5))

    for i, strat in enumerate(strategies):
        agg_vals = []
        for glabel in group_labels:
            strat_rows = [r for r in by_group[glabel] if r.get("strategy") == strat]
            if not use_mean:
                strat_rows = _feasible_only(strat_rows)
            vals = [_safe_float(r.get(metric_key, 0)) for r in strat_rows]
            agg_vals.append(float(agg_fn(vals)) if vals else 0.0)
        ax.bar(x + i * width, agg_vals, width, label=strat)

    ax.set_xticks(x + width * (n_strats - 1) / 2)
    ax.set_xticklabels(group_labels, rotation=45, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize="small", loc="best")
    plt.tight_layout()
    fig.savefig(out / filename, bbox_inches="tight")
    plt.close(fig)


def _dimension_breakdown(rows, group_key, out_dir):
    """Generate grouped-bar charts for all tracked metrics by a dimension.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    group_key : str
        Column name of the dimension to break down by.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    _BREAKDOWN_METRICS = [
        ("changed_assignments", "median changed assignments", "Stability"),
        ("prop_changed", "median prop changed", "Normalised stability"),
        ("infeasible", "infeasibility rate", "Infeasibility"),
        ("timeout", "timeout rate", "Timeout"),
        ("staff_fairness_variance", "median fairness variance", "Fairness (variance)"),
        ("staff_fairness_gini", "median Gini coefficient", "Fairness (Gini)"),
        ("solve_time_seconds", "median solve time (s)", "Solve time"),
        ("staff_load_max", "median max staff load", "Max staff load"),
    ]
    dim_label = {
        "noise_type": "noise type",
        "noise_level": "noise level",
        "size_label": "dataset size",
        "complexity": "availability complexity",
        "penalty_scale": "penalty scale",
    }.get(group_key, group_key)

    for metric_key, ylabel, short_title in _BREAKDOWN_METRICS:
        safe_metric = metric_key.replace(".", "_")
        _grouped_bar(
            rows, group_key=group_key,
            metric_key=metric_key,
            ylabel=ylabel,
            title=f"{short_title} by {dim_label}",
            filename=f"{safe_metric}_by_{group_key}.png",
            out_dir=out_dir,
        )


def plot_by_noise(rows: List[Dict[str, Any]], out_dir: str):
    """Generate dimension-breakdown charts grouped by noise type.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    _dimension_breakdown(rows, "noise_type", out_dir)


def plot_by_noise_level(rows: List[Dict[str, Any]], out_dir: str):
    """Breakdown charts by noise severity level (low / medium / high / extreme).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    _dimension_breakdown(rows, "noise_level", out_dir)


def plot_by_size(rows: List[Dict[str, Any]], out_dir: str):
    """Generate dimension-breakdown charts grouped by dataset size.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    _dimension_breakdown(rows, "size_label", out_dir)


def plot_by_complexity(rows: List[Dict[str, Any]], out_dir: str):
    """Generate dimension-breakdown charts grouped by availability complexity.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    _dimension_breakdown(rows, "complexity", out_dir)


def plot_by_penalty_scale(rows: List[Dict[str, Any]], out_dir: str):
    """Breakdown charts by penalty_scale (only when multiple values exist).

    Only generated when the data contains more than one distinct
    penalty_scale value (i.e. a sweep was performed).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNGs.

    Returns
    -------
    None
    """
    distinct = {r.get("penalty_scale", "") for r in rows}
    distinct.discard("")
    if len(distinct) < 2:
        return
    _dimension_breakdown(rows, "penalty_scale", out_dir)
