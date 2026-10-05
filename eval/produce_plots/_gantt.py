"""Gantt chart plotting functions.

Provides candidate-movement Gantt charts and staff-assignment Gantt charts
that visualise initial vs. rescheduled assignments side-by-side.
"""
from pathlib import Path
from typing import Dict, List

from eval.colour_palette import (
    GANTT_INITIAL, GANTT_RESCHEDULE, GANTT_NEW, GANTT_CONNECTOR,
)


def extract_staff_by_slot(staff_assignment: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Return the staff-assignment mapping unchanged.

    Parameters
    ----------
    staff_assignment : dict[str, list[str]]
        Mapping of slot → list of staff IDs (already in the expected
        shape).

    Returns
    -------
    dict[str, list[str]]
        The same mapping, or an empty dict if *staff_assignment* is falsy.
    """
    return staff_assignment or {}


def plot_gantt(initial_sched: Dict[str, str], target_sched: Dict[str, str], out_path: Path, title: str):
    """Plot a candidate-movement Gantt chart.

    Draws horizontal bars for each candidate's initial and target
    time-slot assignment, with connector lines for moved candidates
    and distinct colours for newly-added candidates.

    Parameters
    ----------
    initial_sched : dict[str, str]
        Mapping of candidate → slot for the initial schedule.
    target_sched : dict[str, str]
        Mapping of candidate → slot for the target schedule.
    out_path : Path
        File path for the saved PNG image.
    title : str
        Title string shown on the chart.
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
        from matplotlib.lines import Line2D
    except Exception:
        print("matplotlib not available; skipping gantt")
        return

    slots = sorted(set(list(initial_sched.values()) + list(target_sched.values())))
    slot_index = {s: i for i, s in enumerate(slots)}

    candidates = sorted(set(list(initial_sched.keys()) + list(target_sched.keys())))

    initial_set = set(initial_sched.keys())
    new_candidates = {c for c in candidates if c not in initial_set}

    bar_h = 0.35
    fig_w = max(10, len(candidates) * 0.35)
    fig_h = max(4, len(slots) * 0.25)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    moved_count = 0
    added_count = len(new_candidates)
    for i, c in enumerate(candidates):
        a = initial_sched.get(c)
        b = target_sched.get(c)

        is_new = c in new_candidates
        target_colour = GANTT_NEW if is_new else GANTT_RESCHEDULE

        if a:
            ax.broken_barh([(i - bar_h, bar_h * 2)], (slot_index[a], 0.8),
                           facecolors=(GANTT_INITIAL,), label="_nolegend_")
        if b:
            ax.broken_barh([(i - bar_h + 0.05, bar_h * 2)], (slot_index[b] + 0.05, 0.8),
                           facecolors=(target_colour,), label="_nolegend_")
        if a != b:
            moved_count += 1
            if a is not None and b is not None:
                y_start = slot_index[a] + 0.4
                y_end = slot_index[b] + 0.4
                ax.plot([i, i], [y_start, y_end], color=GANTT_CONNECTOR, linewidth=1, label="_nolegend_")

    ax.set_xticks(range(len(candidates)))
    ax.set_xticklabels(candidates, rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(len(slots)))
    ax.set_yticklabels(slots, fontsize=7)
    ax.set_xlabel("Candidate")
    ax.set_ylabel("Time Slot")

    legend_handles = [
        Patch(facecolor=GANTT_INITIAL, label="Initial assignment"),
        Patch(facecolor=GANTT_RESCHEDULE, label="Rescheduled (unchanged)"),
        Patch(facecolor=GANTT_NEW, label=f"Newly added ({added_count})"),
        Line2D([0], [0], color=GANTT_CONNECTOR, linewidth=1, label=f"Moved ({moved_count})"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7)

    ax.set_title(f"{title} — moved: {moved_count}, added: {added_count}", fontsize=9)
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close(fig)


def plot_staff_gantt(initial_staff_assign: Dict[str, List[str]], target_staff_assign: Dict[str, List[str]],
                     out_path: Path, title: str):
    """Plot a slot-centric Gantt showing staff assignments per slot.

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
        from matplotlib.patches import Patch
        from matplotlib.lines import Line2D
    except Exception:
        print("matplotlib not available; skipping staff gantt")
        return

    initial_by_slot = extract_staff_by_slot(initial_staff_assign)
    target_by_slot = extract_staff_by_slot(target_staff_assign)

    all_slots = sorted(set(list(initial_by_slot.keys()) + list(target_by_slot.keys())))
    if not all_slots:
        print("No staff assignments found; skipping staff gantt")
        return

    all_staff = sorted(set([s for sl in initial_by_slot.values() for s in sl] +
                           [s for sl in target_by_slot.values() for s in sl]))

    if not all_staff:
        print("No staff found; skipping staff gantt")
        return

    slot_index = {s: i for i, s in enumerate(all_slots)}
    staff_index = {s: i for i, s in enumerate(all_staff)}

    fig, ax = plt.subplots(figsize=(max(10, len(all_slots) * 0.35), max(4, len(all_staff) * 0.25)))

    changed_count = 0
    total_staff_changes = 0
    for slot in all_slots:
        initial_staff = set(initial_by_slot.get(slot, []))
        target_staff = set(target_by_slot.get(slot, []))

        for staff in initial_staff:
            y_pos = staff_index[staff]
            ax.broken_barh([(slot_index[slot], 0.8)], (y_pos - 0.4, 0.8),
                           facecolors=(GANTT_INITIAL,), label="_nolegend_", edgecolor="black", linewidth=0.5)

        for staff in target_staff:
            y_pos = staff_index[staff]
            ax.broken_barh([(slot_index[slot] + 0.05, 0.8)], (y_pos - 0.4 + 0.1, 0.8),
                           facecolors=(GANTT_RESCHEDULE,), label="_nolegend_", edgecolor="black", linewidth=0.5)

        added = target_staff - initial_staff
        removed = initial_staff - target_staff
        if added or removed:
            changed_count += 1
        total_staff_changes += len(added) + len(removed)

    ax.set_yticks(range(len(all_staff)))
    ax.set_yticklabels(all_staff, fontsize=8)
    ax.set_xticks(range(len(all_slots)))
    ax.set_xticklabels(all_slots, rotation=45, ha="right", fontsize=8)

    legend_handles = [
        Patch(facecolor=GANTT_INITIAL, label="Initial staff"),
        Patch(facecolor=GANTT_RESCHEDULE, label="Target staff"),
        Patch(facecolor="none", edgecolor="none",
              label=f"Staff changes: {total_staff_changes}"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=8)

    ax.set_xlabel("Time slot")
    ax.set_ylabel("Staff ID")
    ax.set_title(f"{title} — slots with staff changes: {changed_count}")
    plt.tight_layout()
    fig.savefig(out_path, bbox_inches='tight')
    plt.close(fig)
