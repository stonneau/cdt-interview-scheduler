"""
Collect per-run metrics and save to CSV.

Aggregates metrics from all schedules/events in a run to produce:
  - Per-schedule row: iteration, strategy, change_event, changed_assignments,
    changed_candidate_assignments, changed_staff_assignments,
    temporal_deviation_minutes, fairness_variance, solve_time, feasible
  - Saved as {run_id}/metrics.csv in the base_dir

Change details are stored directly in the event store when events are created,
so they can be retrieved from event records if needed for debugging.
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

from data_models.store import DataStore
from eval.metrics import ScheduleMetrics


def collect_metrics_for_run(base_dir: str, run_id: str) -> List[Dict[str, Any]]:
    """
    Load all schedules and events for a run and extract metrics.
    
    Parameters
    ----------
    base_dir : str
        Base directory containing run subdirectories.
    run_id : str
        Run identifier (subdirectory name).
    
    Returns
    -------
    List[Dict[str, Any]]
        List of metric rows, each with keys:
        - iteration: schedule sequence number
        - strategy: rescheduling strategy used
        - change_event: human-readable change event label
        - changed_assignments: count of all changes (candidates + staff)
        - changed_candidate_assignments: count of candidates whose slot changed
        - changed_staff_assignments: count of (staff, slot) pair changes
        - fairness_variance: staff load variance
        - solve_time: solver time in seconds
        - feasible: boolean (1.0 or 0.0)
    """
    ds = DataStore(config={"base_dir": base_dir, "run_id": run_id})
    
    # Load all schedules and events
    schedules = list(ds.list_schedules())
    events = list(ds.iter_change_events())
    
    if not schedules:
        return []
    
    # Sort schedules by sequence number
    schedules_sorted = sorted(schedules, key=lambda s: (s.get("seq") or 0, s.get("created_at", 0)))
    
    # Initial schedule
    initial_schedule = schedules_sorted[0].get("schedule", {}) if schedules_sorted else {}
    
    # Build event label map: event_id -> label
    event_labels: Dict[str, str] = {}
    for ev in events:
        ev_id = ev.get("id")
        inner = ev.get("event", {})
        
        # Try to extract label from metadata
        meta = inner.get("metadata", {})
        label = meta.get("change_event_label", "")
        if label and label.strip().lower() not in ("reschedule", ""):
            event_labels[ev_id] = label
        else:
            # Fallback: extract from change_event structure
            change_event = inner.get("change_event", {})
            if isinstance(change_event, dict) and change_event:
                if "noise_applied" in change_event:
                    noise_meta = change_event.get("noise_applied", {})
                    if isinstance(noise_meta, dict):
                        label = noise_meta.get("type", "noise_applied")
                        event_labels[ev_id] = label
                else:
                    # For other change events, use keys joined by comma
                    label = ",".join(sorted(list(change_event.keys())))
                    event_labels[ev_id] = label
    
    # Extract metrics for each schedule
    rows = []
    prev_schedule = None
    prev_staff_assign = None
    
    for sched_payload in schedules_sorted:
        seq = sched_payload.get("seq") or 0
        meta = sched_payload.get("metadata", {})
        sched = sched_payload.get("schedule", {})
        
        # Skip initial schedule (seq 0 or missing strategy)
        strat = meta.get("strategy")
        if strat is None or strat == "":
            prev_schedule = sched
            prev_staff_assign = meta.get("staff_assignment", {})
            continue
        
        # Determine baseline for change calculation
        prev_sched_id = meta.get("prev_schedule_id") or meta.get("previous_schedule_id")
        baseline_schedule = None
        baseline_staff_assign = None
        if prev_sched_id:
            # Try to find the previous schedule by id
            for sp in schedules_sorted:
                if sp.get("id") == prev_sched_id:
                    baseline_schedule = sp.get("schedule", {})
                    baseline_staff_assign = sp.get("metadata", {}).get("staff_assignment", {})
                    break
        if baseline_schedule is None:
            baseline_schedule = prev_schedule if prev_schedule else initial_schedule
        if baseline_staff_assign is None:
            baseline_staff_assign = prev_staff_assign or {}
        
        # Get change event label
        change_event_id = meta.get("change_event_id") or meta.get("event_id")
        change_event_label = event_labels.get(change_event_id, "")
        if not change_event_label:
            change_event_label = meta.get("change_event_label", "no_change")
        
        # Compute metrics using ScheduleMetrics
        staff_assign = meta.get("staff_assignment", {})
        metrics_obj = ScheduleMetrics(
            schedule=sched,
            prev_schedule=baseline_schedule,
            staff_assignment=staff_assign,
            prev_staff_assignment=baseline_staff_assign,
        )
        
        stability = metrics_obj.stability_metrics()
        robustness = metrics_obj.robustness_metrics()
        
        # Determine feasibility: check if solve was successful
        cp_status = meta.get("cp_status")
        feasible = 1.0 if cp_status == 4 else 0.0  # 4 = OPTIMAL
        
        row = {
            "iteration": seq,
            "strategy": strat,
            "change_event": change_event_label,
            "changed_assignments": int(stability.get("changed_assignments", 0)),
            "changed_candidate_assignments": int(stability.get("changed_candidate_assignments", 0)),
            "changed_staff_assignments": int(stability.get("changed_staff_assignments", 0)),
            "temporal_deviation_minutes": round(stability.get("temporal_deviation_minutes", 0.0), 2),
            "fairness_variance": round(robustness.get("staff_fairness_variance", 0.0), 4),
            "solve_time": round(meta.get("solve_time_seconds", 0.0), 6),
            "feasible": feasible,
        }
        rows.append(row)
        prev_schedule = sched
        prev_staff_assign = staff_assign
    
    return rows


def save_metrics_csv(base_dir: str, run_id: str, rows: List[Dict[str, Any]]) -> Path:
    """
    Save metrics rows to CSV file in the run directory.
    
    Parameters
    ----------
    base_dir : str
        Base directory containing run subdirectories.
    run_id : str
        Run identifier (subdirectory name).
    rows : List[Dict[str, Any]]
        Metrics rows to save.
    
    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    run_dir = Path(base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Metrics file goes in the run_id directory
    csv_path = run_dir / "metrics.csv"
    
    if not rows:
        # Write header only
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "iteration", "strategy", "change_event", "changed_assignments",
                "changed_candidate_assignments", "changed_staff_assignments",
                "temporal_deviation_minutes","fairness_variance", "solve_time", "feasible"
            ])
            writer.writeheader()
        return csv_path
    
    # Write rows with header
    fieldnames = ["iteration", "strategy", "change_event", "changed_assignments",
                "changed_candidate_assignments", "changed_staff_assignments",
                "temporal_deviation_minutes","fairness_variance", "solve_time", "feasible"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return csv_path


def collect_and_save_metrics(base_dir: str, run_id: str) -> Path:
    """
    Convenience function: collect metrics and save to CSV in one call.
    
    Parameters
    ----------
    base_dir : str
        Base directory containing run subdirectories.
    run_id : str
        Run identifier (subdirectory name).
    
    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    rows = collect_metrics_for_run(base_dir, run_id)
    csv_path = save_metrics_csv(base_dir, run_id, rows)
    print(f"Metrics saved to {csv_path}")
    return csv_path
