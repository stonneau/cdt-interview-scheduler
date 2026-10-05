"""Solver timing bar chart.

Provides a simple bar chart of solver wall-clock times per strategy.
"""
from pathlib import Path
from typing import Dict, Any, List


def plot_solver_times(records: List[Dict[str, Any]], out_path: Path):
    """Plot a bar chart of solver times per strategy.

    Parameters
    ----------
    records : list[dict]
        Each dict must contain ``"strategy"`` (str) and
        ``"solve_time_seconds"`` (float or None).
    out_path : Path
        File path for the saved PNG image.
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib not available; skipping solver time plot")
        return

    strategies = [r.get("strategy") for r in records]
    times = [r.get("solve_time_seconds") or 0 for r in records]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(range(len(strategies)), times)
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(strategies, rotation=45, ha="right")
    ax.set_ylabel("solve_time_seconds")
    ax.set_title("Solver time per strategy")
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches='tight')
    plt.close(fig)
