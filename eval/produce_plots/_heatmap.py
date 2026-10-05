"""Staff assignment heatmap plot.

Provides a colour-coded grid showing which staff are assigned in which
time slots across initial and target schedules.
"""
from pathlib import Path
from typing import Dict, List

from eval.colour_palette import (
    HEATMAP_DISCRETE, HEATMAP_INITIAL, HEATMAP_TARGET, HEATMAP_BOTH, HEATMAP_NONE,
)
from eval.produce_plots._gantt import extract_staff_by_slot


def plot_staff_heatmap(initial_staff_assign: Dict[str, List[str]], target_staff_assign: Dict[str, List[str]],
                       out_path: Path, title: str):
    """Plot a heatmap of staff assignments (rows=staff, cols=slots).

    Cell values encode assignment status: initial-only, target-only,
    both (unchanged), or none.

    Parameters
    ----------
    initial_staff_assign : dict[str, list[str]]
        Mapping of slot → staff IDs for the initial schedule.
    target_staff_assign : dict[str, list[str]]
        Mapping of slot → staff IDs for the target schedule.
    out_path : Path
        File path for the saved PNG image.
    title : str
        Title string shown on the chart.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        print("matplotlib not available; skipping staff heatmap")
        return

    initial_by_slot = extract_staff_by_slot(initial_staff_assign)
    target_by_slot = extract_staff_by_slot(target_staff_assign)

    all_slots = sorted(set(list(initial_by_slot.keys()) + list(target_by_slot.keys())))
    all_staff = sorted(set([s for sl in initial_by_slot.values() for s in sl] +
                           [s for sl in target_by_slot.values() for s in sl]))

    if not all_slots or not all_staff:
        print("No staff assignments found; skipping staff heatmap")
        return

    # Values: 0=none, 1=initial only, 2=target only, 3=both
    matrix = np.zeros((len(all_staff), len(all_slots)))

    for slot_idx, slot in enumerate(all_slots):
        initial_staff = set(initial_by_slot.get(slot, []))
        target_staff = set(target_by_slot.get(slot, []))

        for staff_idx, staff in enumerate(all_staff):
            in_initial = staff in initial_staff
            in_target = staff in target_staff

            if in_initial and in_target:
                matrix[staff_idx, slot_idx] = 3
            elif in_initial and not in_target:
                matrix[staff_idx, slot_idx] = 1
            elif not in_initial and in_target:
                matrix[staff_idx, slot_idx] = 2
            else:
                matrix[staff_idx, slot_idx] = 0

    colors = HEATMAP_DISCRETE
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(boundaries=[-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], ncolors=5)

    fig, ax = plt.subplots(figsize=(max(8, len(all_slots) * 0.4), max(8, len(all_staff) * 0.5)))
    im = ax.imshow(matrix, cmap=cmap, norm=norm, aspect='auto', origin='lower')

    _tick_fs = max(9, min(14, 560 // max(len(all_slots), 1)))
    _cell_fs = max(8, min(12, 480 // max(len(all_slots), 1)))

    ax.set_xticks(range(len(all_slots)))
    ax.set_xticklabels(all_slots, rotation=45, ha="right", fontsize=_tick_fs)
    ax.set_yticks(range(len(all_staff)))
    ax.set_yticklabels(all_staff, fontsize=_tick_fs)

    for staff_idx in range(len(all_staff)):
        for slot_idx in range(len(all_slots)):
            val = int(matrix[staff_idx, slot_idx])
            if val > 0:
                label = ['', 'I', 'T', 'I+T'][val]
                ax.text(slot_idx, staff_idx, label, ha='center', va='center', fontsize=_cell_fs, color='black')

    from matplotlib.patches import Patch as MplPatch
    legend_elements = [
        MplPatch(facecolor=HEATMAP_INITIAL, label='Initial only'),
        MplPatch(facecolor=HEATMAP_TARGET, label='Target only'),
        MplPatch(facecolor=HEATMAP_BOTH, label='Both (unchanged)'),
        MplPatch(facecolor=HEATMAP_NONE, edgecolor='black', label='None'),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=_tick_fs,
              framealpha=0.9, edgecolor="grey")

    ax.set_xlabel("Time slot", fontsize=_tick_fs + 1)
    ax.set_ylabel("Staff ID", fontsize=_tick_fs + 1)
    ax.set_title(f"{title}", fontsize=_tick_fs + 4)
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches='tight')
    plt.close(fig)
