"""Pareto frontier scatter and region plots.

Provides scatter plots of stability-vs-fairness Pareto frontiers,
convex-hull region overlays, and zoomed views focused on median clusters.
"""
from pathlib import Path
from typing import Dict, Any, List

from eval.colour_palette import CATEGORY_CYCLE


def _convex_hull(points):
    """Compute the convex hull of a set of 2-D points.

    Uses Andrew's monotone-chain algorithm.  Pure numpy, no scipy needed.

    Parameters
    ----------
    points : numpy.ndarray
        An N×2 array of (x, y) coordinates.

    Returns
    -------
    numpy.ndarray
        An M×2 array of hull vertices in counter-clockwise order.
    """
    import numpy as np

    pts = points[np.lexsort((points[:, 1], points[:, 0]))]
    if len(pts) <= 1:
        return pts

    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return np.array(hull)


def plot_pareto(points: List[Dict[str, Any]], out_path: Path):
    """Plot a Pareto scatter of stability vs fairness.

    Points are grouped by strategy and colour-coded accordingly.

    Parameters
    ----------
    points : list[dict]
        Each dict must contain ``"num_changed"`` (int), ``"fairness_var"``
        (float), and ``"label"`` (str, strategy prefix before ``|``).
    out_path : Path
        File path for the saved PNG image.
    """
    try:
        import matplotlib.pyplot as plt
        from collections import defaultdict
    except Exception:
        print("matplotlib not available; skipping pareto")
        return

    if not points:
        print("No pareto points found; skipping")
        return

    by_strategy: Dict[str, list] = defaultdict(list)
    for p in points:
        label = p.get("label", "")
        strategy = label.split("|")[0] if "|" in label else label
        by_strategy[strategy].append(p)

    fig, ax = plt.subplots(figsize=(8, 5))

    for strategy, pts in sorted(by_strategy.items()):
        xs = [p["num_changed"] for p in pts]
        ys = [p["fairness_var"] for p in pts]
        ax.scatter(xs, ys, label=strategy, alpha=0.5, s=20)

    ax.set_xlabel("# changed assignments", fontsize=16)
    ax.set_ylabel("fairness variance", fontsize=16)
    ax.set_title("Pareto: stability vs fairness", fontsize=18)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=12, loc="best", title="strategy")
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches='tight')
    plt.close(fig)


def plot_pareto_regions(points: List[Dict[str, Any]], out_path: Path,
                        x_key: str = "num_changed"):
    """Pareto plot with convex-hull regions, median markers, and a zoomed inset.

    Draws a filled convex hull (alpha shading) around each strategy's points
    and a bold median marker so the viewer can quickly see where each strategy
    tends to land without interpreting hundreds of overlapping dots.

    A zoomed inset ("magnifying glass") is placed in the upper-left corner,
    focused on the bounding box of all strategy medians with IQR error bars.

    Parameters
    ----------
    points : list[dict]
        Each dict must contain *x_key* (number), ``"fairness_var"`` (float),
        and ``"label"`` (str).
    out_path : Path
        File path for the saved PNG image.
    x_key : str
        Dictionary key for the x-axis metric (default ``"num_changed"``).
        Pass ``"prop_changed"`` to use proportion changed instead.
    """
    _X_LABELS = {
        "num_changed": "# changed assignments (stability →)",
        "prop_changed": "proportion changed (stability →)",
    }
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from collections import defaultdict
        from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
    except Exception:
        print("matplotlib not available; skipping pareto regions")
        return

    if not points:
        print("No pareto points found; skipping pareto regions")
        return

    by_strategy: Dict[str, list] = defaultdict(list)
    for p in points:
        label = p.get("label", "")
        strategy = label.split("|")[0] if "|" in label else label
        by_strategy[strategy].append(p)

    fig, ax = plt.subplots(figsize=(10, 7))
    colours = CATEGORY_CYCLE

    medians_x = []
    medians_y = []
    strategy_data: list = []

    for idx, (strategy, pts) in enumerate(sorted(by_strategy.items())):
        colour = colours[idx % len(colours)]
        xs = np.array([p[x_key] for p in pts])
        ys = np.array([p["fairness_var"] for p in pts])

        if len(xs) >= 3:
            try:
                hull_pts = _convex_hull(np.column_stack([xs, ys]))
                if len(hull_pts) >= 3:
                    polygon = plt.Polygon(
                        hull_pts, facecolor=colour, alpha=0.18,
                        edgecolor=colour, linewidth=1.5, linestyle="--",
                    )
                    ax.add_patch(polygon)
            except Exception:
                pass

        mx, my = float(np.median(xs)), float(np.median(ys))
        medians_x.append(mx)
        medians_y.append(my)
        med_fmt = f"{mx:.3f}" if x_key == "prop_changed" else f"{mx:.1f}"
        ax.scatter(
            [mx], [my], marker="X", s=160, color=colour,
            edgecolors="black", linewidths=0.8, zorder=5,
            label=f"{strategy}  (med: {med_fmt}, {my:.3f})",
        )
        strategy_data.append((strategy, colour, xs, ys, mx, my))

    ax.set_xlabel(_X_LABELS.get(x_key, x_key), fontsize=16)
    ax.set_ylabel("fairness variance (equity →)", fontsize=16)
    ax.set_title("Strategy regions: stability vs fairness", fontsize=18)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=12, loc="upper right", title="strategy (median x, y)")

    if len(medians_x) >= 2:
        x_lo, x_hi = min(medians_x), max(medians_x)
        y_lo, y_hi = min(medians_y), max(medians_y)
        x_span = max(x_hi - x_lo, 1)
        y_span = max(y_hi - y_lo, 0.01)
        pad_x = x_span * 0.6
        pad_y = y_span * 0.6

        axins = inset_axes(ax, width="40%", height="40%", loc="upper left",
                           borderpad=2.0)
        axins.set_xlim(x_lo - pad_x, x_hi + pad_x)
        axins.set_ylim(max(0, y_lo - pad_y), y_hi + pad_y)

        for strategy, colour, xs, ys, mx, my in strategy_data:
            axins.scatter(xs, ys, color=colour, s=8, alpha=0.15,
                          edgecolors="none")
            x_q1 = float(np.percentile(xs, 25))
            x_q3 = float(np.percentile(xs, 75))
            y_q1 = float(np.percentile(ys, 25))
            y_q3 = float(np.percentile(ys, 75))
            axins.errorbar(
                mx, my,
                xerr=[[mx - x_q1], [x_q3 - mx]],
                yerr=[[my - y_q1], [y_q3 - my]],
                fmt="none", ecolor=colour, elinewidth=1.0, capsize=3,
                capthick=1.0, alpha=0.6, zorder=4,
            )
            axins.scatter([mx], [my], marker="X", s=120, color=colour,
                          edgecolors="black", linewidths=0.8, zorder=5)

        axins.set_title("Median zoom", fontsize=8)
        axins.tick_params(labelsize=7)
        try:
            mark_inset(ax, axins, loc1=3, loc2=4, fc="none", ec="0.5",
                       linestyle="--", linewidth=0.8)
        except Exception:
            pass

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)


def plot_pareto_regions_zoomed(points: List[Dict[str, Any]], out_path: Path):
    """Standalone zoomed Pareto plot focused on the median cluster area.

    When the convex-hull regions extend far from the medians, the full-scale
    plot makes closely-spaced medians impossible to distinguish.  This variant
    computes the bounding box of all strategy medians and zooms the axes to a
    comfortable margin around that box, with IQR error bars and individual
    points shown as small dots for context.

    Parameters
    ----------
    points : list[dict]
        Each dict must contain ``"num_changed"`` (int), ``"fairness_var"``
        (float), and ``"label"`` (str).
    out_path : Path
        File path for the saved PNG image.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from collections import defaultdict
    except Exception:
        print("matplotlib not available; skipping pareto regions zoomed")
        return

    if not points:
        return

    by_strategy: Dict[str, list] = defaultdict(list)
    for p in points:
        label = p.get("label", "")
        strategy = label.split("|")[0] if "|" in label else label
        by_strategy[strategy].append(p)

    fig, ax = plt.subplots(figsize=(9, 6))
    colours = CATEGORY_CYCLE

    medians_x = []
    medians_y = []

    for idx, (strategy, pts) in enumerate(sorted(by_strategy.items())):
        colour = colours[idx % len(colours)]
        xs = np.array([p["num_changed"] for p in pts])
        ys = np.array([p["fairness_var"] for p in pts])

        ax.scatter(xs, ys, color=colour, s=10, alpha=0.15, edgecolors="none")

        mx, my = float(np.median(xs)), float(np.median(ys))
        medians_x.append(mx)
        medians_y.append(my)

        x_q1, x_q3 = float(np.percentile(xs, 25)), float(np.percentile(xs, 75))
        y_q1, y_q3 = float(np.percentile(ys, 25)), float(np.percentile(ys, 75))
        ax.errorbar(
            mx, my,
            xerr=[[mx - x_q1], [x_q3 - mx]],
            yerr=[[my - y_q1], [y_q3 - my]],
            fmt="none", ecolor=colour, elinewidth=1.2, capsize=4, capthick=1.2,
            alpha=0.6, zorder=4,
        )

        ax.scatter(
            [mx], [my], marker="X", s=180, color=colour,
            edgecolors="black", linewidths=1.0, zorder=5,
            label=f"{strategy}  (med: {mx:.1f}, {my:.3f})",
        )

    if medians_x and medians_y:
        x_lo, x_hi = min(medians_x), max(medians_x)
        y_lo, y_hi = min(medians_y), max(medians_y)
        x_span = max(x_hi - x_lo, 1)
        y_span = max(y_hi - y_lo, 0.01)
        pad_x = x_span * 0.6
        pad_y = y_span * 0.6
        ax.set_xlim(x_lo - pad_x, x_hi + pad_x)
        ax.set_ylim(max(0, y_lo - pad_y), y_hi + pad_y)

    ax.set_xlabel("# changed assignments (stability →)", fontsize=16)
    ax.set_ylabel("fairness variance (equity →)", fontsize=16)
    ax.set_title("Strategy medians: stability vs fairness (zoomed)", fontsize=18)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=12, loc="best", title="strategy (median x, y)")
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
