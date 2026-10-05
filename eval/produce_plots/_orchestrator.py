"""CLI orchestrator for the produce_plots package.

Contains the ``main()`` entry-point that discovers runs, loads schedules,
builds records, and delegates to individual plotting functions.
"""
from pathlib import Path
import json
import statistics
import argparse
from typing import Dict, Any, List

from eval.colour_palette import apply_colorblind_cycle

from eval.produce_plots._utils import load_schedules, ensure_outdir, compute_num_changed
from eval.produce_plots._gantt import plot_gantt, plot_staff_gantt
from eval.produce_plots._bars import plot_bars
from eval.produce_plots._pareto import plot_pareto
from eval.produce_plots._heatmap import plot_staff_heatmap
from eval.produce_plots._timing import plot_solver_times


def main():
    """Run the full plotting pipeline from the command line.

    Parses ``--base``, ``--run-id``, and ``--out`` arguments, loads
    schedules from the DataStore, and produces Gantt charts, bar charts,
    Pareto scatter plots, staff heatmaps, and solver-time plots in the
    output directory.
    """
    apply_colorblind_cycle()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=str, default="data", help="Base directory containing run subdirectories")
    parser.add_argument("--run-id", type=str, default=None, help="Explicit run_id to analyze (auto-selects if not provided)")
    parser.add_argument("--out", type=str, default="outputs", help="Output directory for plots")
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
    else:
        base_path = Path(args.base)
        if not base_path.exists():
            print(f"Base directory {args.base} does not exist")
            return

        run_dirs = [d for d in base_path.iterdir() if d.is_dir() and (d / "schedules").exists()]
        if not run_dirs:
            print(f"No run directories found in {args.base}")
            return

        def get_latest_ts(run_dir):
            max_ts = 0
            for sched_file in (run_dir / "events").glob("*.json"):
                try:
                    with open(sched_file) as f:
                        data = json.load(f)
                        ts = data.get("ts", 0)
                        max_ts = max(max_ts, ts)
                except Exception:
                    pass
            return max_ts

        run_with_max = max(run_dirs, key=get_latest_ts)
        run_id = run_with_max.name
        args.run_id = run_id

    out_dir = Path(args.out) / run_id
    ensure_outdir(out_dir)

    schedules, events = load_schedules(args.base, run_id)
    if not schedules:
        print("No schedules found in DataStore; nothing to plot")
        return

    schedules_sorted = sorted(schedules, key=lambda s: (s.get("seq") or 0, s.get("created_at", 0)))

    initial = schedules_sorted[0]
    print(f"This is the initial schedule {initial.get('id')} (run_id={args.run_id}, seq={initial.get('seq')})")
    initial_sched = initial.get("schedule", {})

    strat_map = {}
    change_records = []
    solver_time_records = []
    pareto_points = []

    def derive_label_from_event(inner_event: Dict[str, Any]) -> str:
        meta = (inner_event.get("metadata") or {})
        label = meta.get("change_event_label")
        if label:
            if label.strip().lower() in ("reschedule", ""):
                return "no_change"
            return label
        ce = inner_event.get("change_event") or {}
        if isinstance(ce, dict) and ce:
            if "noise_applied" in ce:
                noise_meta = ce.get("noise_applied", {})
                if isinstance(noise_meta, dict):
                    noise_type = noise_meta.get("type", "noise_applied")
                    return noise_type
            return ",".join(sorted(list(ce.keys())))
        return "no_change"

    reschedule_events_inner = []
    for ev in events:
        inner = ev.get("event") if isinstance(ev, dict) else ev
        if not inner:
            continue
        if inner.get("type") == "reschedule":
            reschedule_events_inner.append(inner)

    label_to_idx: Dict[str, int] = {}
    ordered_labels: List[str] = []
    for inner in reschedule_events_inner:
        lbl = derive_label_from_event(inner)
        if lbl not in label_to_idx:
            label_to_idx[lbl] = len(ordered_labels)
            ordered_labels.append(lbl)

    for payload in schedules_sorted:
        meta = payload.get("metadata") or {}
        sched = payload.get("schedule") or {}
        strat = meta.get("strategy") or ("initial" if payload == initial else "unknown")
        strat_map.setdefault(strat, payload)

        solver_time_records.append({"strategy": strat, "solve_time_seconds": meta.get("solve_time_seconds")})

        if payload == initial:
            continue

        label = None
        label_raw = meta.get("change_event_label")
        if label_raw:
            label = ("no_change" if label_raw.strip().lower() in ("reschedule", "") else label_raw)
        else:
            eid = meta.get("change_event_id") or meta.get("event_id") or meta.get("change_event_id")
            if eid:
                for ev in events:
                    ev_id = ev.get("id")
                    inner = ev.get("event") if isinstance(ev, dict) else ev
                    if ev_id == eid:
                        label = derive_label_from_event(inner)
                        break

        if label is None:
            label = "no_change"

        if label not in label_to_idx:
            label_to_idx[label] = len(ordered_labels)
            ordered_labels.append(label)

        change_idx = label_to_idx[label]

        num_changed = meta.get("num_changed_assignments")
        if num_changed is None:
            prev_id = meta.get("prev_schedule_id") or meta.get("previous_schedule_id")
            baseline = None
            if prev_id:
                id_map = {p.get("id"): p for p in schedules_sorted}
                prev_payload = id_map.get(prev_id)
                if prev_payload:
                    baseline = prev_payload.get("schedule", {})
            if baseline is None:
                baseline = initial_sched

            num_changed = compute_num_changed(baseline, sched)

        change_records.append({"strategy": strat, "num_changed_assignments": num_changed, "change_idx": change_idx})

        c_w = meta.get("candidate_change_penalty_weight")
        s_w = meta.get("staff_change_penalty_weight")
        if c_w is not None and s_w is not None and num_changed is not None:
            staff_assign = meta.get("staff_assignment", {})
            counts = [len(v) for v in staff_assign.values()] if staff_assign else []
            fv = statistics.pvariance(counts) if counts else 0
            pareto_points.append({"num_changed": num_changed, "fairness_var": fv, "label": f"c{c_w}-s{s_w}"})

    change_labels = {i: lbl for i, lbl in enumerate(ordered_labels)}

    for payload in schedules_sorted:
        if payload == initial:
            continue
        meta = payload.get("metadata") or {}
        strat = meta.get("strategy") or "unknown"
        label_raw = meta.get("change_event_label")
        if label_raw:
            label = ("no_change" if label_raw.strip().lower() in ("reschedule", "") else label_raw)
        else:
            eid = meta.get("change_event_id") or meta.get("event_id")
            label = None
            if eid:
                for ev in events:
                    if ev.get("id") == eid:
                        label = derive_label_from_event(ev.get("event") if isinstance(ev, dict) else ev)
                        break
            if label is None:
                label = "no_change"
        seq = payload.get("seq") or 0
        sid = payload.get("id") or "unknown"
        title = f"Event: {label} | Strategy: {strat} | seq:{seq}"
        out_path = out_dir / f"gantt_seq{seq}_{label}_{strat}_{sid[:8]}.png"
        plot_gantt(initial_sched, payload.get("schedule", {}), out_path, title=title)

        initial_staff_assign = initial.get("metadata", {}).get("staff_assignment", {})
        target_staff_assign = meta.get("staff_assignment", {})

        if initial_staff_assign and target_staff_assign:
            staff_gantt_path = out_dir / f"staff_gantt_seq{seq}_{label}_{strat}_{sid[:8]}.png"
            plot_staff_gantt(initial_staff_assign, target_staff_assign, staff_gantt_path,
                             title=f"Staff Gantt - {title}")

            staff_heatmap_path = out_dir / f"staff_heatmap_seq{seq}_{label}_{strat}_{sid[:8]}.png"
            plot_staff_heatmap(initial_staff_assign, target_staff_assign, staff_heatmap_path,
                               title=f"Staff Heatmap - {title}")

    plot_bars(change_records, out_dir / "bar_changes.png", labels=change_labels)

    plot_pareto(pareto_points, out_dir / "pareto.png")

    plot_solver_times(solver_time_records, out_dir / "solver_time.png")

    print(f"Plots for run {args.run_id} written to", out_dir)
