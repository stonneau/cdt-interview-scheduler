"""Advanced Pareto plots coloured by penalty_scale and fairness_weight.

Provides ``plot_pareto_by_penalty_scale`` (connected-median paths along the
stability-fairness frontier) and ``plot_pareto_ps_fw_interaction`` (ratio
scatter and faceted heatmaps showing how penalty_scale and fairness_weight
interact).
"""
import math
from pathlib import Path
from typing import List, Dict, Any

from eval.colour_palette import (
    CATEGORY_CYCLE, CMAP_SEQUENTIAL, CMAP_DIVERGING, CMAP_HEATMAP,
)
from eval.sweep_plots._helpers import _safe_float


def plot_pareto_by_penalty_scale(points: List[Dict[str, Any]], out_dir: str,
                                  x_key: str = "num_changed",
                                  suffix: str = ""):
    """Pareto plot (stability vs fairness) showing penalty_scale effect.

    Generates two plots:

    1. ``pareto_penalty_scale{suffix}.png`` -- For each strategy, a connected
       line traces the median (stability, fairness) at each penalty_scale
       value, coloured by a gradient.

    2. ``pareto_penalty_scale_faceted{suffix}.png`` -- One subplot per
       strategy with the same connected-median approach.

    Only generated when the data contains more than one distinct
    penalty_scale value.

    Parameters
    ----------
    points : list of dict
        Pareto point dicts with ``num_changed``, ``prop_changed``,
        ``fairness_var``, ``strategy``, and ``penalty_scale`` keys.
    out_dir : str
        Directory to write the output PNGs.
    x_key : str
        Dictionary key for the x-axis metric (default ``"num_changed"``).
    suffix : str
        Suffix appended to output filenames before the extension.

    Returns
    -------
    None
    """
    _X_LABELS = {
        "num_changed": "# changed assignments (stability →)",
        "prop_changed": "proportion changed (stability →)",
    }
    _X_LABELS_SHORT = {
        "num_changed": "changed assignments",
        "prop_changed": "proportion changed",
    }
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as np
        from collections import defaultdict
    except Exception:
        print("matplotlib not available; skipping pareto-by-penalty-scale")
        return

    ps_points = []
    for p in points:
        ps_raw = p.get("penalty_scale", "")
        if ps_raw == "":
            continue
        try:
            ps_val = float(ps_raw)
        except (TypeError, ValueError):
            continue
        ps_points.append({**p, "_ps": ps_val})

    distinct_ps = {p["_ps"] for p in ps_points}
    if len(distinct_ps) < 2:
        return

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    by_strategy: Dict[str, list] = defaultdict(list)
    for p in ps_points:
        by_strategy[p.get("strategy", "unknown")].append(p)

    markers = ["o", "s", "^", "D", "v", "P", "*", "X", "h", "<", ">"]
    strategy_names = sorted(by_strategy.keys())
    strategy_markers = {s: markers[i % len(markers)] for i, s in enumerate(strategy_names)}

    _LOG_FLOOR = 1e-9
    all_ps = sorted(distinct_ps)
    vmin = min(all_ps)
    vmax = max(all_ps)
    use_log = vmax / max(vmin, _LOG_FLOOR) > 10
    norm = mcolors.LogNorm(vmin=max(vmin, _LOG_FLOOR), vmax=vmax) if use_log else mcolors.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.cm.get_cmap(CMAP_SEQUENTIAL)

    def _median_path(pts):
        """Return sorted-by-ps arrays (ps_vals, med_x, med_y)."""
        by_ps: Dict[float, list] = defaultdict(list)
        for p in pts:
            by_ps[p["_ps"]].append(p)
        ps_sorted = sorted(by_ps.keys())
        med_x = np.array([float(np.median([q[x_key] for q in by_ps[ps]])) for ps in ps_sorted])
        med_y = np.array([float(np.median([q["fairness_var"] for q in by_ps[ps]])) for ps in ps_sorted])
        return np.array(ps_sorted), med_x, med_y

    # Plot 1: combined connected-median paths
    fig, ax = plt.subplots(figsize=(9, 6))
    colours = CATEGORY_CYCLE

    for idx, strat in enumerate(strategy_names):
        pts = by_strategy[strat]
        colour = colours[idx % len(colours)]
        marker = strategy_markers[strat]

        xs_all = np.array([p[x_key] for p in pts])
        ys_all = np.array([p["fairness_var"] for p in pts])
        ax.scatter(xs_all, ys_all, color=colour, marker=marker,
                   s=15, alpha=0.15, edgecolors="none")

        ps_vals, med_x, med_y = _median_path(pts)
        for i in range(len(ps_vals) - 1):
            seg_colour = cmap(norm(ps_vals[i]))
            ax.plot(med_x[i:i+2], med_y[i:i+2], color=seg_colour,
                    linewidth=2.5, solid_capstyle="round")

        sc = ax.scatter(med_x, med_y, c=ps_vals, cmap=cmap, norm=norm,
                        marker=marker, s=80, edgecolors="black", linewidths=0.8,
                        zorder=5, label=strat)

        for i, ps in enumerate(ps_vals):
            ax.annotate(f"{ps:g}", (med_x[i], med_y[i]),
                        textcoords="offset points", xytext=(5, 5),
                        fontsize=8, color="dimgrey")

    cbar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, pad=0.02)
    cbar.set_label("penalty_scale (λ_p)", fontsize=14)
    cbar.ax.tick_params(labelsize=12)

    ax.set_xlabel(_X_LABELS.get(x_key, x_key), fontsize=16)
    ax.set_ylabel("fairness variance (equity →)", fontsize=16)
    ax.set_title("Stability–fairness frontier by penalty scale (median paths)", fontsize=18)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=12, loc="best", title="strategy", markerscale=1.0)
    plt.tight_layout()
    fig.savefig(out / f"pareto_penalty_scale{suffix}.png", bbox_inches="tight", dpi=150)
    plt.close(fig)

    # Plot 2: faceted variant (one subplot per strategy)
    n_strats = len(strategy_names)
    if n_strats >= 2:
        ncols = min(n_strats, 3)
        nrows = math.ceil(n_strats / ncols)
        fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.5 * nrows),
                                  squeeze=False, sharex=True, sharey=True)
        for s_idx, strat in enumerate(strategy_names):
            r, c = divmod(s_idx, ncols)
            ax = axes[r][c]
            pts = by_strategy[strat]

            xs_all = np.array([p[x_key] for p in pts])
            ys_all = np.array([p["fairness_var"] for p in pts])
            ax.scatter(xs_all, ys_all, color="lightgrey", s=12, alpha=0.4, edgecolors="none")

            ps_vals, med_x, med_y = _median_path(pts)
            for i in range(len(ps_vals) - 1):
                seg_colour = cmap(norm(ps_vals[i]))
                ax.plot(med_x[i:i+2], med_y[i:i+2], color=seg_colour,
                        linewidth=2.5, solid_capstyle="round")
            ax.scatter(med_x, med_y, c=ps_vals, cmap=cmap, norm=norm,
                       s=60, edgecolors="black", linewidths=0.7, zorder=5)
            for i, ps in enumerate(ps_vals):
                ax.annotate(f"λ={ps:g}", (med_x[i], med_y[i]),
                            textcoords="offset points", xytext=(5, 4),
                            fontsize=7, color="dimgrey")

            ax.set_title(strat, fontsize=14)
            ax.set_xlabel(_X_LABELS_SHORT.get(x_key, x_key), fontsize=14)
            ax.set_ylabel("fairness var", fontsize=14)
            ax.tick_params(labelsize=12)

        for s_idx in range(n_strats, nrows * ncols):
            r, c = divmod(s_idx, ncols)
            axes[r][c].set_visible(False)
        fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=axes, pad=0.02,
                     label="penalty_scale (λ_p)")
        fig.suptitle("Penalty-scale effect per strategy (median paths)", fontsize=16, y=1.01)
        plt.tight_layout()
        fig.savefig(out / f"pareto_penalty_scale_faceted{suffix}.png", bbox_inches="tight", dpi=150)
        plt.close(fig)


def plot_pareto_ps_fw_interaction(points: List[Dict[str, Any]], out_dir: str,
                                   x_key: str = "num_changed",
                                   suffix: str = ""):
    """Pareto plot showing how penalty_scale and fairness_weight interact.

    When both lambda_p and lambda_f are swept, the ratio lambda_p/lambda_f
    determines how the solver trades stability for fairness.

    Generates:

    1. ``pareto_ps_fw_interaction{suffix}.png`` -- Median points coloured by
       the lambda_p/lambda_f ratio.

    2. ``pareto_ps_fw_heatmap{suffix}.png`` -- Faceted heatmaps (one per
       strategy) with penalty_scale on x, fairness_weight on y.

    Only generated when data contains multiple distinct values for both
    penalty_scale and fairness_weight.

    Parameters
    ----------
    points : list of dict
        Pareto point dicts.
    out_dir : str
        Directory to write the output PNGs.
    x_key : str
        Dictionary key for the x-axis metric (default ``"num_changed"``).
    suffix : str
        Suffix appended to output filenames before the extension.

    Returns
    -------
    None
    """
    _X_LABELS = {
        "num_changed": "# changed assignments (stability →)",
        "prop_changed": "proportion changed (stability →)",
    }
    _HEATMAP_LABELS = {
        "num_changed": "med changed",
        "prop_changed": "med prop changed",
    }
    _HEATMAP_SUPTITLES = {
        "num_changed": "Stability by penalty_scale × fairness_weight (median changed assignments)",
        "prop_changed": "Stability by penalty_scale × fairness_weight (median proportion changed)",
    }
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as np
        from collections import defaultdict
    except Exception:
        print("matplotlib not available; skipping ps/fw interaction plot")
        return

    _LOG_FLOOR = 1e-9
    combo_points = []
    for p in points:
        ps_raw = p.get("penalty_scale", "")
        fw_raw = p.get("fairness_weight", "")
        if ps_raw == "" or fw_raw == "":
            continue
        try:
            ps_val = float(ps_raw)
            fw_val = float(fw_raw)
        except (TypeError, ValueError):
            continue
        ratio = ps_val / max(fw_val, _LOG_FLOOR)
        combo_points.append({**p, "_ps": ps_val, "_fw": fw_val, "_ratio": ratio})

    distinct_ps = {p["_ps"] for p in combo_points}
    distinct_fw = {p["_fw"] for p in combo_points}
    if len(distinct_ps) < 2 or len(distinct_fw) < 2:
        return

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    by_strategy: Dict[str, list] = defaultdict(list)
    for p in combo_points:
        by_strategy[p.get("strategy", "unknown")].append(p)

    strategy_names = sorted(by_strategy.keys())
    markers = ["o", "s", "^", "D", "v", "P", "*", "X", "h", "<", ">"]
    strategy_markers = {s: markers[i % len(markers)] for i, s in enumerate(strategy_names)}

    all_ratios = sorted({p["_ratio"] for p in combo_points})
    vmin = min(all_ratios)
    vmax = max(all_ratios)
    use_log = vmax / max(vmin, _LOG_FLOOR) > 10
    norm = (mcolors.LogNorm(vmin=max(vmin, _LOG_FLOOR), vmax=vmax)
            if use_log else mcolors.Normalize(vmin=vmin, vmax=vmax))
    cmap = plt.cm.get_cmap(CMAP_DIVERGING)

    # Plot 1: combined interaction plot
    fig, ax = plt.subplots(figsize=(8, 5))
    colours = CATEGORY_CYCLE

    for idx, strat in enumerate(strategy_names):
        pts = by_strategy[strat]
        marker = strategy_markers[strat]

        by_combo: Dict[tuple, list] = defaultdict(list)
        for p in pts:
            by_combo[(p["_ps"], p["_fw"])].append(p)

        med_data = []
        for (ps, fw), grp in sorted(by_combo.items()):
            mx = float(np.median([q[x_key] for q in grp]))
            my = float(np.median([q["fairness_var"] for q in grp]))
            ratio = ps / max(fw, 1e-9)
            med_data.append((ps, fw, ratio, mx, my))

        if not med_data:
            continue

        ps_arr = np.array([d[0] for d in med_data])
        fw_arr = np.array([d[1] for d in med_data])
        ratio_arr = np.array([d[2] for d in med_data])
        mx_arr = np.array([d[3] for d in med_data])
        my_arr = np.array([d[4] for d in med_data])

        sc = ax.scatter(mx_arr, my_arr, c=ratio_arr, cmap=cmap, norm=norm,
                        marker=marker, s=80, edgecolors="black", linewidths=0.7,
                        zorder=5, label=strat)

        for i in range(len(med_data)):
            ps, fw = med_data[i][0], med_data[i][1]
            ax.annotate(f"{ps:g}/{fw:g}", (mx_arr[i], my_arr[i]),
                        textcoords="offset points", xytext=(5, 5),
                        fontsize=7, color="dimgrey")

    cbar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, pad=0.02)
    cbar.set_label("λ_p / λ_f ratio", fontsize=14)
    cbar.ax.tick_params(labelsize=12)

    ax.set_xlabel(_X_LABELS.get(x_key, x_key), fontsize=16)
    ax.set_ylabel("fairness variance (equity →)", fontsize=16)
    ax.set_title("Stability–fairness frontier by penalty/fairness ratio (medians)",
                 fontsize=18)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=12, loc="best", title="strategy", markerscale=1.0)

    ax.autoscale(tight=True)
    x_lo, x_hi = ax.get_xlim()
    y_lo, y_hi = ax.get_ylim()
    x_pad = (x_hi - x_lo) * 0.03
    y_pad = (y_hi - y_lo) * 0.03
    ax.set_xlim(max(0, x_lo - x_pad), x_hi + x_pad)
    ax.set_ylim(max(0, y_lo - y_pad), y_hi + y_pad)
    ax.margins(0.02)

    plt.tight_layout()
    fig.savefig(out / f"pareto_ps_fw_interaction{suffix}.png", bbox_inches="tight", dpi=150)
    plt.close(fig)

    # Plot 2: faceted heatmaps per strategy
    n_strats = len(strategy_names)
    if n_strats < 1:
        return
    ncols = min(n_strats, 3)
    nrows = math.ceil(n_strats / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 4.5 * nrows),
                             squeeze=False)

    ps_sorted = sorted(distinct_ps)
    fw_sorted = sorted(distinct_fw)

    for s_idx, strat in enumerate(strategy_names):
        r, c = divmod(s_idx, ncols)
        ax = axes[r][c]
        pts = by_strategy[strat]

        by_combo: Dict[tuple, list] = defaultdict(list)
        for p in pts:
            by_combo[(p["_ps"], p["_fw"])].append(p)

        grid = np.full((len(fw_sorted), len(ps_sorted)), np.nan)
        for fi, fw in enumerate(fw_sorted):
            for pi, ps in enumerate(ps_sorted):
                grp = by_combo.get((ps, fw), [])
                if grp:
                    grid[fi, pi] = float(np.median([q[x_key] for q in grp]))

        im = ax.imshow(grid, aspect="auto", cmap=CMAP_HEATMAP, origin="lower")
        ax.set_xticks(range(len(ps_sorted)))
        ax.set_xticklabels([f"{v:g}" for v in ps_sorted], fontsize=12)
        ax.set_yticks(range(len(fw_sorted)))
        ax.set_yticklabels([f"{v:g}" for v in fw_sorted], fontsize=12)
        ax.set_xlabel("penalty_scale (λ_p)", fontsize=14)
        ax.set_ylabel("fairness_weight (λ_f)", fontsize=14)
        ax.set_title(strat, fontsize=14)

        cell_fmt = ".2f" if x_key == "prop_changed" else ".1f"
        for fi in range(len(fw_sorted)):
            for pi in range(len(ps_sorted)):
                val = grid[fi, pi]
                if not np.isnan(val):
                    ax.text(pi, fi, f"{val:{cell_fmt}}", ha="center", va="center",
                            fontsize=10, color="black" if val < np.nanmax(grid) * 0.7 else "white")

        fig.colorbar(im, ax=ax, pad=0.04, shrink=0.8,
                     label=_HEATMAP_LABELS.get(x_key, "med changed"))

    for s_idx in range(n_strats, nrows * ncols):
        r, c = divmod(s_idx, ncols)
        axes[r][c].set_visible(False)

    fig.suptitle(_HEATMAP_SUPTITLES.get(x_key, ""), fontsize=16, y=1.01)
    plt.tight_layout()
    fig.savefig(out / f"pareto_ps_fw_heatmap{suffix}.png", bbox_inches="tight", dpi=150)
    plt.close(fig)
