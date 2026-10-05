"""Individual metric charts for sweep analysis.

Provides bar charts and box-plots for individual metrics such as
changed assignments, fairness variance, solve time, Gini coefficient,
staff load range, infeasibility rates, and noise-level progressions.
"""
import math
from pathlib import Path
from typing import List, Dict, Any

from eval.colour_palette import (
    BAR_PRIMARY, BAR_SECONDARY, BAR_MIN, BAR_MEDIAN, BAR_MAX,
    BAR_INFEASIBLE, BAR_TIMEOUT,
)
from eval.sweep_plots._helpers import (
    _safe_float, _feasible_only, _METRIC_DEFS, _MEAN_AGG_METRICS,
)

_NOISE_LEVEL_ORDER = ["low", "medium", "high", "extreme"]


def plot_boxplot_changed(rows: List[Dict[str, Any]], out_dir: str):
    """Box-plot of changed assignments per strategy (feasible runs only).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
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
        print("matplotlib not available; skipping boxplot")
        return

    feasible = _feasible_only(rows)

    groups: Dict[str, list] = {}
    for r in feasible:
        strat = r.get("strategy") or "unknown"
        val = _safe_float(r.get("changed_assignments") or r.get("num_changed") or 0)
        groups.setdefault(strat, []).append(val)

    if not groups:
        print("No data for boxplot")
        return

    strategies = sorted(groups.keys())
    data = [groups[s] for s in strategies]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.boxplot(data, labels=strategies, showmeans=True)
    ax.set_ylabel("# changed assignments")
    ax.set_title("Changed assignments by strategy (feasible runs only)")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    fig.savefig(out / "box_changed.png", bbox_inches="tight")
    plt.close(fig)


def plot_fairness_bar(rows: List[Dict[str, Any]], out_dir: str):
    """Bar chart of median fairness variance per strategy (feasible runs only).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
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
        print("matplotlib not available; skipping fairness bar")
        return

    feasible = _feasible_only(rows)

    groups: Dict[str, list] = {}
    for r in feasible:
        strat = r.get("strategy") or "unknown"
        val = _safe_float(r.get("staff_fairness_variance") or r.get("fairness_var") or 0)
        groups.setdefault(strat, []).append(val)

    if not groups:
        print("No data for fairness bar")
        return

    strategies = sorted(groups.keys())
    medians = [float(np.median(groups[s])) for s in strategies]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(len(strategies)), medians)
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("median fairness variance")
    ax.set_title("Median fairness variance by strategy (feasible runs only)")
    plt.tight_layout()
    fig.savefig(out / "fairness_bar.png", bbox_inches="tight")
    plt.close(fig)


def plot_solve_time_bar(rows: List[Dict[str, Any]], out_dir: str):
    """Bar chart of median solve time per strategy.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
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
        print("matplotlib not available; skipping solve time bar")
        return

    groups: Dict[str, list] = {}
    for r in rows:
        strat = r.get("strategy") or "unknown"
        val = _safe_float(r.get("solve_time_seconds", 0))
        groups.setdefault(strat, []).append(val)

    if not groups:
        return

    strategies = sorted(groups.keys())
    medians = [float(np.median(groups[s])) for s in strategies]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(len(strategies)), medians, color=BAR_PRIMARY)
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("median solve time (s)")
    ax.set_title("Median solve time by strategy")
    plt.tight_layout()
    fig.savefig(out / "solve_time_bar.png", bbox_inches="tight")
    plt.close(fig)


def plot_prop_changed_boxplot(rows: List[Dict[str, Any]], out_dir: str):
    """Box-plot of proportion of changed assignments (normalised stability).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNG.

    Returns
    -------
    None
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib not available; skipping prop_changed boxplot")
        return

    feasible = _feasible_only(rows)

    groups: Dict[str, list] = {}
    for r in feasible:
        strat = r.get("strategy") or "unknown"
        val = _safe_float(r.get("prop_changed", 0))
        groups.setdefault(strat, []).append(val)

    if not groups:
        return

    strategies = sorted(groups.keys())
    data = [groups[s] for s in strategies]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.boxplot(data, labels=strategies, showmeans=True)
    ax.set_ylabel("proportion changed")
    ax.set_title("Proportion of changed assignments by strategy (feasible runs only)")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    fig.savefig(out / "box_prop_changed.png", bbox_inches="tight")
    plt.close(fig)


def plot_gini_bar(rows: List[Dict[str, Any]], out_dir: str):
    """Bar chart of median Gini coefficient per strategy (feasible runs only).

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
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
        print("matplotlib not available; skipping Gini bar")
        return

    feasible = _feasible_only(rows)

    groups: Dict[str, list] = {}
    for r in feasible:
        strat = r.get("strategy") or "unknown"
        val = _safe_float(r.get("staff_fairness_gini", 0))
        groups.setdefault(strat, []).append(val)

    if not groups:
        return

    strategies = sorted(groups.keys())
    medians = [float(np.median(groups[s])) for s in strategies]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(len(strategies)), medians, color=BAR_SECONDARY)
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("median Gini coefficient")
    ax.set_title("Staff load Gini coefficient by strategy (feasible runs only)")
    plt.tight_layout()
    fig.savefig(out / "gini_bar.png", bbox_inches="tight")
    plt.close(fig)


def plot_staff_load_range(rows: List[Dict[str, Any]], out_dir: str):
    """Grouped bar chart showing median min / median / max staff load per strategy.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
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
        print("matplotlib not available; skipping staff load range")
        return

    groups_min: Dict[str, list] = {}
    groups_med: Dict[str, list] = {}
    groups_max: Dict[str, list] = {}
    feasible = _feasible_only(rows)
    for r in feasible:
        strat = r.get("strategy") or "unknown"
        groups_min.setdefault(strat, []).append(_safe_float(r.get("staff_load_min", 0)))
        groups_med.setdefault(strat, []).append(_safe_float(r.get("staff_load_median", 0)))
        groups_max.setdefault(strat, []).append(_safe_float(r.get("staff_load_max", 0)))

    strategies = sorted(groups_min.keys())
    if not strategies:
        return

    med_min = [float(np.median(groups_min[s])) for s in strategies]
    med_med = [float(np.median(groups_med[s])) for s in strategies]
    med_max = [float(np.median(groups_max[s])) for s in strategies]

    x = np.arange(len(strategies))
    width = 0.25

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(8, len(strategies) * 2), 5))
    ax.bar(x - width, med_min, width, label="min load", color=BAR_MIN)
    ax.bar(x, med_med, width, label="median load", color=BAR_MEDIAN)
    ax.bar(x + width, med_max, width, label="max load", color=BAR_MAX)
    ax.set_xticks(x)
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("staff load (# slots)")
    ax.set_title("Staff load distribution by strategy (feasible runs, median)")
    ax.legend(fontsize="small", loc="best")
    plt.tight_layout()
    fig.savefig(out / "staff_load_range.png", bbox_inches="tight")
    plt.close(fig)


def plot_infeasibility_bar(rows: List[Dict[str, Any]], out_dir: str):
    """Stacked bar chart of infeasibility rate (%) by strategy.

    The bar is split into *timeout* (UNKNOWN status) and *true infeasible*
    (INFEASIBLE / MODEL_INVALID) so readers can see how much of the
    non-feasible rate is caused by hitting the solver time limit versus
    the model being genuinely infeasible.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output PNG.

    Returns
    -------
    None
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib not available; skipping infeasibility bar")
        return

    groups_infeas: Dict[str, list] = {}
    groups_timeout: Dict[str, list] = {}
    for r in rows:
        strat = r.get("strategy") or "unknown"
        infeas_val = _safe_float(r.get("infeasible", 0))
        timeout_val = _safe_float(r.get("timeout", 0))
        groups_infeas.setdefault(strat, []).append(infeas_val)
        groups_timeout.setdefault(strat, []).append(timeout_val)

    if not groups_infeas:
        return

    strategies = sorted(groups_infeas.keys())
    n = [max(len(groups_infeas.get(s, [])), 1) for s in strategies]
    timeout_rates = [100.0 * sum(groups_timeout.get(s, [])) / n[i] for i, s in enumerate(strategies)]
    total_infeas_rates = [100.0 * sum(groups_infeas.get(s, [])) / n[i] for i, s in enumerate(strategies)]
    true_infeas_rates = [total - to for total, to in zip(total_infeas_rates, timeout_rates)]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(strategies))
    bars_infeas = ax.bar(x, true_infeas_rates, color=BAR_INFEASIBLE, label="True infeasible")
    bars_timeout = ax.bar(x, timeout_rates, bottom=true_infeas_rates, color=BAR_TIMEOUT, label="Timeout")
    ax.set_xticks(list(x))
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("non-feasible rate (%)")
    ax.set_title("Infeasibility rate by strategy (timeout vs true infeasible)")
    ax.legend(fontsize="small", loc="best")
    for i, s in enumerate(strategies):
        total = len(groups_infeas.get(s, []))
        infeas_count = int(sum(groups_infeas.get(s, [])))
        timeout_count = int(sum(groups_timeout.get(s, [])))
        true_infeas_count = infeas_count - timeout_count
        if infeas_count > 0:
            parts = []
            if true_infeas_count > 0:
                parts.append(f"infeas={true_infeas_count}")
            if timeout_count > 0:
                parts.append(f"timeout={timeout_count}")
            label_text = f"{', '.join(parts)}/{total}"
            ax.annotate(
                label_text,
                xy=(i, total_infeas_rates[i]),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=7,
            )
    plt.tight_layout()
    fig.savefig(out / "infeasibility_bar.png", bbox_inches="tight")
    plt.close(fig)


def plot_metric_vs_noise_level(rows: List[Dict[str, Any]], out_dir: str):
    """Line plots showing how each metric degrades as noise level increases.

    Produces one PNG per metric with one line per strategy, x-axis ordered
    ``low -> medium -> high -> extreme``.

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
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        print("matplotlib not available; skipping noise-level progression plots")
        return

    level_set = set(_NOISE_LEVEL_ORDER)
    filtered = [r for r in rows if r.get("noise_level", "") in level_set]
    if not filtered:
        return

    strategies = sorted({r.get("strategy", "unknown") for r in filtered})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for metric_key, metric_label, _hib in _METRIC_DEFS:
        use_mean = metric_key in _MEAN_AGG_METRICS
        agg_fn = np.mean if use_mean else np.median

        fig, ax = plt.subplots(figsize=(8, 5))
        has_data = False

        for strat in strategies:
            y_vals = []
            for level in _NOISE_LEVEL_ORDER:
                strat_level_rows = [
                    r for r in filtered
                    if r.get("strategy") == strat and r.get("noise_level") == level
                ]
                if not use_mean:
                    strat_level_rows = _feasible_only(strat_level_rows)
                vals = [_safe_float(r.get(metric_key, 0)) for r in strat_level_rows]
                y_vals.append(float(agg_fn(vals)) if vals else float("nan"))

            if any(not math.isnan(v) for v in y_vals):
                ax.plot(_NOISE_LEVEL_ORDER, y_vals, marker="o", label=strat)
                has_data = True

        if not has_data:
            plt.close(fig)
            continue

        ax.set_xlabel("Noise Level")
        ax.set_ylabel(metric_label)
        ax.set_title(f"{metric_label} vs Noise Level")
        ax.legend(fontsize="small", loc="best")
        plt.tight_layout()
        safe_metric = metric_key.replace(".", "_")
        fig.savefig(out / f"{safe_metric}_vs_noise_level.png", bbox_inches="tight")
        plt.close(fig)
