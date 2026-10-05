"""Bar chart of changed assignments per strategy and change-event.

Provides the grouped bar chart that visualises how many candidate
assignments each strategy changed for every change event.
"""
from pathlib import Path
from typing import Dict, Any, List


def plot_bars(change_records: List[Dict[str, Any]], out_path: Path, labels: Dict[int, str] = None):
    """Plot a grouped bar chart of changed assignments.

    Parameters
    ----------
    change_records : list[dict]
        Each dict must contain ``"strategy"`` (str),
        ``"num_changed_assignments"`` (int), and ``"change_idx"`` (int).
    out_path : Path
        File path for the saved PNG image.
    labels : dict[int, str] or None
        Optional mapping of change-index → human-readable label for
        x-axis tick labels.
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib not available; skipping bars")
        return

    groups = {}
    for r in change_records:
        key = (r.get("change_idx"), r.get("strategy"))
        groups.setdefault(key, 0)
        groups[key] = r.get("num_changed_assignments") or 0

    strategies = sorted(list({s for _, s in groups.keys()}))
    change_idxs = sorted(list({i for i, _ in groups.keys()}))

    import numpy as np
    x = np.arange(len(change_idxs))
    width = 0.8 / max(1, len(strategies))

    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = []
    for j, strat in enumerate(strategies):
        vals = [groups.get((ci, strat), 0) for ci in change_idxs]
        b = ax.bar(x + j * width, vals, width, label=strat)
        bars.append((b, vals))

    ax.set_xticks(x + width * (len(strategies) - 1) / 2)
    if labels:
        xticks = [labels.get(i, f"change_{i}") for i in change_idxs]
    else:
        xticks = [f"change_{i}" for i in change_idxs]
    ax.set_xticklabels(xticks, rotation=45, ha="right")
    ax.set_ylabel("# changed assignments")
    ax.legend()
    ax.set_title("Changed assignments per strategy and change-event")
    plt.tight_layout()
    try:
        for b_group, vals in bars:
            for rect, v in zip(b_group, vals):
                height = rect.get_height()
                if height is None:
                    continue
                ax.annotate(
                    f"{int(v)}",
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )
    except Exception:
        pass

    fig.savefig(out_path, bbox_inches='tight')
    plt.close(fig)
