"""
User-facing CLI for interacting with the scheduler.

This is the main entrypoint for running the solver from the command line.
It uses the modular `scheduler` and `data_models` packages.
"""

import argparse
import os
import shlex
from data_models.store import DataStore
from data_models.loaders import (
    load_availability_objects_from_csv,
    load_staff_objects_from_csv,
    load_prev_schedule_from_csv,
    load_forbidden_pairs_from_csv,
    parse_forbidden_pairs_inline,
    objects_to_solver_inputs_from_models,
    unify_slots,
)
from scheduler.solver import solve_initial_schedule, reschedule
import copy

from eval.metrics import ScheduleMetrics


def _compute_and_print_metrics(schedule, prev_schedule, staff_assignment, time_slots):
    """Compute and print stability and robustness metrics for a schedule.

    Instantiates :class:`~eval.metrics.ScheduleMetrics` with the current and
    previous schedule, then prints the resulting stability and robustness
    dictionaries to stdout.

    :param schedule: Current schedule mapping ``{candidate_id: slot_id}``.
    :param prev_schedule: Previous/baseline schedule mapping
        ``{candidate_id: slot_id}``.
    :param staff_assignment: Staff assignment mapping ``{slot_id: [staff_id, ...]}``.
    :param time_slots: Ordered list of all timeslot identifiers.
    :returns: A tuple of ``(stability_dict, robustness_dict)`` as returned
        by :meth:`ScheduleMetrics.stability_metrics` and
        :meth:`ScheduleMetrics.robustness_metrics`.
    :rtype: tuple[dict, dict]
    """
    metrics = ScheduleMetrics(
        schedule=schedule,
        prev_schedule=prev_schedule,
        staff_assignment=staff_assignment,
        time_slots=time_slots,
    )
    stability = metrics.stability_metrics()
    robustness = metrics.robustness_metrics()
    print("Stability metrics:", stability)
    print("Robustness metrics:", robustness)
    return stability, robustness


def _generate_plots(run_id: str, base_dir: str = "data", out_dir: str = "outputs") -> None:
    """Generate all plots for a given DataStore run_id using eval.produce_plots.

    Note: ``produce_plots.main()`` writes plots to ``<out_dir>/<run_id>/``,
    so the actual files appear one level deeper than the *out_dir* argument.
    """
    import sys
    from pathlib import Path
    try:
        from eval.produce_plots import main as produce_main
    except ImportError:
        print("eval.produce_plots not available; skipping plots.")
        return

    orig_argv = sys.argv[:]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    sys.argv = [
        "produce_plots",
        "--base", base_dir,
        "--run-id", run_id,
        "--out", str(out_path),
    ]
    try:
        produce_main()
        # produce_plots.main() writes into out_path/run_id/
        print(f"Plots written to {out_path / run_id}")
    except Exception as e:
        print(f"Plot generation failed: {e}")
    finally:
        sys.argv = orig_argv

def _print_schedule(schedule, staff_assignment):
    """Print the current schedule and staff assignments to stdout.

    Each candidate–slot assignment is printed on its own line, sorted
    alphabetically by candidate ID, along with the staff members assigned
    to that slot.

    :param schedule: Schedule mapping ``{candidate_id: slot_id}``.
    :param staff_assignment: Staff assignment mapping ``{slot_id: [staff_id, ...]}``.
    :returns: Nothing.  Output is printed to stdout.
    :rtype: None
    """
    if not schedule:
        print("No schedule available.")
        return
    print("\nSchedule:")
    for c, t in sorted(schedule.items()):
        staff = staff_assignment.get(t, [])
        print(f"  {c} -> {t} | Staff: {', '.join(staff)}")
    print()

def _print_help():
    """Print the interactive-mode help text listing all available commands.

    :returns: Nothing.  Help text is printed to stdout.
    :rtype: None
    """
    print("""
Interactive commands:
  help                         Show this help
  show                         Show current schedule and staff assignment
  changes                      Show pending change_event
  strategy <name>              Set reschedule strategy (full, change_penalty, local_repair, slack_based)
  add staff_unavailable S T    Mark staff S unavailable at timeslot T (adds to change_event)
  add candidate_unavailable C [T]  Mark candidate C unavailable (optionally only at T)
  add remove_candidate C       Remove candidate C
  add add_candidate C          Add candidate C (full availability)
  add staff_removed S          Remove staff S
  add staff_added S            Add staff S (full availability)
  reschedule                   Apply pending change_event using current strategy and update baseline
  metrics                      Show stability and robustness metrics for current schedule
  plots [out_dir]              Generate plots for this session (saved to out_dir, default: outputs)
  reset_changes                Clear pending change_event
  quit / exit                  Exit
""")


def main() -> None:
    """Main entry-point for the Interview Scheduler CLI.

    Parses command-line arguments, loads CSV data via the
    :mod:`data_models.loaders` module, solves the initial schedule using
    :func:`~scheduler.solver.solve_initial_schedule`, and optionally enters
    an interactive REPL where the user can stage changes and reschedule.

    Supports DataStore browsing (``--browse-store``), schedule export
    (``--export-schedule``), robustness analysis (``--analyse-robustness``),
    plot generation, and full interactive rescheduling (``--interactive``).

    :returns: Nothing.  Results are printed to stdout.
    :rtype: None
    """
    parser = argparse.ArgumentParser(description="Interview Scheduler Solver CLI")
    parser.add_argument(
        "--browse-store",
        action="store_true",
        help="Browse persisted schedules/events in the DataStore and exit",
    )
    parser.add_argument(
        "--export-schedule",
        type=str,
        default=None,
        help="Export a saved schedule by id as a canonical prev_schedule CSV and exit",
    )
    parser.add_argument(
        "--export-out",
        type=str,
        default="prev_schedule.csv",
        help="Output path for export when used with --export-schedule (default: prev_schedule.csv)",
    )
    parser.add_argument(
        "--list-schedules",
        action="store_true",
        help="List saved schedules (used with --browse-store)",
    )
    parser.add_argument(
        "--show-schedule",
        type=str,
        default=None,
        help="Show a saved schedule by id (used with --browse-store)",
    )
    parser.add_argument(
        "--diff-schedules",
        nargs=2,
        metavar=("ID1", "ID2"),
        help="Show difference between two saved schedules (used with --browse-store)",
    )
    parser.add_argument(
        "--applicantscsv",
        type=str,
        required=False,
        help="Path to applicants' availability CSV file",
    )
    parser.add_argument(
        "--staffcsv",
        type=str,
        required=False,
        help="Path to staff availability CSV file",
    )
    parser.add_argument(
        "--prev-schedule",
        type=str,
        default=None,
        help=(
            "Optional path to prev_schedule.csv "
            '(candidate_id,timeslot_id,staff_ids as "s1;s2") '
            "to use for change-penalty objective"
        ),
    )
    parser.add_argument(
        "--min-staff",
        type=int,
        default=2,
        help="Minimum staff per slot",
    )
    parser.add_argument(
        "--fairness",
        type=str,
        choices=["none", "min_max", "min_dev"],
        default="min_max",
        help=(
            "Fairness objective: none, min_max (minimise max load), "
            "or min_dev (minimise deviations)"
        ),
    )
    parser.add_argument(
        "--staff-change-penalty-weight",
        type=int,
        default=1,
        help=(
            "Weight for penalising staff changes between previous and new schedule. "
            "0 disables staff change penalties."
        ),
    )
    parser.add_argument(
        "--analyse-robustness",
        action="store_true",
        help="After solving, print stability and robustness metrics for the initial schedule",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run interactive session to apply changes and reschedule",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist schedules and events to the DataStore (default: False for CLI unless this flag is set)",
    )
    parser.add_argument(
        "--use-saved-schedule",
        type=str,
        default=None,
        help="Use a saved schedule id from the DataStore as the prev_schedule baseline",
    )
    parser.add_argument(
        "--allow-parallel",
        action="store_true",
        help="Allow parallel interview slots (multiple candidates at the same time with different staff)",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=2,
        help="Maximum number of parallel interviews per time slot (default: 2, requires --allow-parallel)",
    )
    parser.add_argument(
        "--forbidden-pairs",
        type=str,
        default=None,
        help=(
            "Forbidden candidate-staff pairings. Can be a path to a CSV file "
            "with columns 'candidate_id,staff_id', or inline pairs in the "
            "format 'cand1:staff1,cand2:staff2'."
        ),
    )
    args = parser.parse_args()

    # Export a saved schedule as prev_schedule CSV if requested
    if args.export_schedule:
        ds = DataStore(config={"base_dir": "data"})
        try:
            out = ds.export_schedule_as_prev_csv(args.export_schedule, args.export_out)
            print(f"Exported schedule {args.export_schedule} -> {out}")
        except FileNotFoundError:
            print("Schedule not found:", args.export_schedule)
        except Exception as e:
            print("Failed to export schedule:", e)
        return

    # Browse persisted DataStore if requested
    if args.browse_store:
        ds = DataStore(config={"base_dir": "data"})
        if args.list_schedules:
            print("Saved schedules:")
            for item in ds.list_schedules():
                sid = item.get("id")
                ts = item.get("created_at")
                num = len(item.get("schedule", {}))
                print(f"  {sid}  (created_at={ts}, assignments={num})")
            return
        if args.show_schedule:
            try:
                payload = ds.get_schedule_metadata(args.show_schedule)
            except FileNotFoundError:
                print("Schedule not found:", args.show_schedule)
                return
            print("Schedule id:", payload.get("id"))
            print("Created at:", payload.get("created_at"))
            sched = payload.get("schedule", {})
            for c, t in sorted(sched.items()):
                print(f"  {c} -> {t}")
            return
        if args.diff_schedules:
            id1, id2 = args.diff_schedules
            try:
                a = ds.get_schedule_metadata(id1).get("schedule", {})
                b = ds.get_schedule_metadata(id2).get("schedule", {})
            except FileNotFoundError as e:
                print("Schedule not found:", e)
                return
            moved = []
            for c in sorted(set(list(a.keys()) + list(b.keys()))):
                if a.get(c) != b.get(c):
                    moved.append((c, a.get(c), b.get(c)))
            print(f"Differences between {id1} and {id2}: {len(moved)} changes")
            for c, old, new in moved:
                print(f"  {c}: {old} -> {new}")
            return
        print("--browse-store specified but no action given. Use --list-schedules, --show-schedule or --diff-schedules")
        return

    # Load canonical objects from CSV
    candidates_objs, time_slots1 = load_availability_objects_from_csv(args.applicantscsv)
    staff_objs, time_slots2 = load_staff_objects_from_csv(args.staffcsv)

    # Load forbidden candidate-staff pairings if provided
    forbidden_pairs_input = args.forbidden_pairs
    parsed_forbidden_pairs = set()
    if forbidden_pairs_input:
        if os.path.isfile(forbidden_pairs_input):
            parsed_forbidden_pairs = load_forbidden_pairs_from_csv(forbidden_pairs_input)
        else:
            parsed_forbidden_pairs = parse_forbidden_pairs_inline(forbidden_pairs_input)
        if parsed_forbidden_pairs:
            print(f"Forbidden pairs ({len(parsed_forbidden_pairs)}): {parsed_forbidden_pairs}")

    # Convert to solver inputs
    candidates, staff, avail, staff_avail, required_staff, forbidden_pairs = (
        objects_to_solver_inputs_from_models(candidates_objs, staff_objs,
                                            forbidden_pairs=parsed_forbidden_pairs)
    )

    # Ensure unified time slots across sources
    time_slots = unify_slots(time_slots1, time_slots2)

    # Optional previous schedule
    if args.prev_schedule:
        prev_mapping, prev_staff_assignment = load_prev_schedule_from_csv(args.prev_schedule)
        prev_schedule = prev_mapping
    else:
        prev_schedule = {}
        prev_staff_assignment = None

    data_store = {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
        "prev_schedule": prev_schedule or {},
        "prev_staff_assignment": prev_staff_assignment,
    }

    # If persist is enabled, create a DataStore object now and reuse it through
    # interactive mode. This ensures all schedules and events go to the same run_id directory.
    persist_store = None
    if args.persist:
        persist_store = DataStore(config={"base_dir": "data"})

    params = {
        "min_staff_per_slot": args.min_staff,
        "fairness": args.fairness,
        "staff_change_penalty_weight": args.staff_change_penalty_weight,
        "time_limit": 5,
        "strategy": "change_penalty",
        "persist": bool(args.persist),
        "use_saved_schedule_id": args.use_saved_schedule,
        "source_applicants": args.applicantscsv,
        "source_staff": args.staffcsv,
        "allow_parallel": bool(args.allow_parallel),
        "max_parallel": int(args.max_parallel),
    }

    # Pass the DataStore object if persistence is enabled. Also provide the
    # in-memory `data_store` dict via `_data_store_dict` so the solver does
    # not attempt to re-load CSVs from the DataStore's base_dir.
    ds_arg = persist_store if persist_store else data_store
    if persist_store:
        params["_data_store_dict"] = data_store
    schedule, metadata = solve_initial_schedule(data_store=ds_arg, params=params)
    staff_assignment = metadata.get("staff_assignment", {})
    _print_schedule(schedule, staff_assignment)

    if args.analyse_robustness:
        print("--- Robustness analysis for initial schedule ---")
        _compute_and_print_metrics(
            schedule=schedule,
            prev_schedule=data_store.get("prev_schedule") or {},
            staff_assignment=staff_assignment,
            time_slots=data_store.get("time_slots"),
        )

    if not args.interactive:
        return
    
    # Interactive mode
    change_event = {}
    current_ds = copy.deepcopy(data_store)
    current_ds["prev_schedule"] = schedule or {}
    current_ds["prev_staff_assignment"] = staff_assignment or {}

    print("Entering interactive mode. Type 'help' for commands.")
    _print_help()

    while True:
        try:
            raw = input("scheduler> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting interactive session.")
            break
        if not raw:
            continue
        parts = shlex.split(raw)
        cmd = parts[0].lower()

        if cmd in ("quit", "exit"):
            print("Goodbye.")
            break
        if cmd == "help":
            _print_help()
            continue
        if cmd == "show":
            _print_schedule(current_ds.get("prev_schedule", {}), current_ds.get("prev_staff_assignment", {}))
            continue
        if cmd == "changes":
            print("Pending change_event:", change_event)
            continue
        if cmd == "strategy":
            if len(parts) < 2:
                print("Usage: strategy <name>")
                continue
            params["strategy"] = parts[1]
            print("Strategy set to", params["strategy"])
            continue
        if cmd == "reset_changes":
            change_event = {}
            print("Cleared pending changes.")
            continue
        if cmd == "add":
            if len(parts) < 3:
                print("Usage examples:\n  add staff_unavailable s1 t1\n  add candidate_unavailable A [t1]\n  add remove_candidate C\n  add add_candidate D\n  add staff_removed s1\n  add staff_added s2")
                continue
            sub = parts[1].lower()
            if sub == "staff_unavailable":
                if len(parts) < 4:
                    print("Usage: add staff_unavailable <staff_id> <timeslot>")
                    continue
                s, t = parts[2], parts[3]
                change_event.setdefault("staff_unavailable", []).append((s, t))
                print(f"Queued staff_unavailable {s} at {t}")
                # also update current_ds.staff_avail so subsequent reschedules see it
                if s in current_ds.get("staff_avail", {}):
                    current_ds["staff_avail"][s][t] = 0
                continue
            if sub == "candidate_unavailable":
                c = parts[2]
                if len(parts) >= 4:
                    t = parts[3]
                    change_event.setdefault("candidate_unavailable", []).append((c, t))
                    if c in current_ds.get("avail", {}):
                        current_ds["avail"][c][t] = 0
                    print(f"Queued candidate_unavailable {c} at {t}")
                else:
                    change_event.setdefault("candidate_unavailable", []).append(c)
                    if c in current_ds.get("avail", {}):
                        for _t in current_ds["time_slots"]:
                            current_ds["avail"][c][_t] = 0
                    print(f"Queued candidate_unavailable {c} (all timeslots)")
                continue
            if sub == "remove_candidate":
                c = parts[2]
                change_event.setdefault("remove_candidate", []).append(c)
                if c in current_ds.get("candidates", []):
                    current_ds["candidates"].remove(c)
                    current_ds["avail"].pop(c, None)
                    current_ds["required_staff"].pop(c, None)
                print(f"Queued remove_candidate {c}")
                continue
            if sub == "add_candidate":
                c = parts[2]
                change_event.setdefault("add_candidate", []).append(c)
                if c not in current_ds.get("candidates", []):
                    current_ds["candidates"].append(c)
                    current_ds["avail"][c] = {t: 1 for t in current_ds["time_slots"]}
                print(f"Queued add_candidate {c}")
                continue
            if sub == "staff_removed":
                s = parts[2]
                change_event.setdefault("staff_removed", []).append(s)
                if s in current_ds.get("staff", []):
                    current_ds["staff"].remove(s)
                    current_ds["staff_avail"].pop(s, None)
                print(f"Queued staff_removed {s}")
                continue
            if sub == "staff_added":
                s = parts[2]
                change_event.setdefault("staff_added", []).append(s)
                if s not in current_ds.get("staff", []):
                    current_ds["staff"].append(s)
                    current_ds["staff_avail"][s] = {t: 1 for t in current_ds["time_slots"]}
                print(f"Queued staff_added {s}")
                continue
            print("Unknown add subcommand:", sub)
            continue
        if cmd == "metrics":
            sched = current_ds.get("prev_schedule") or {}
            prev = data_store.get("prev_schedule") or {}
            sa = current_ds.get("prev_staff_assignment") or {}
            if not sched:
                print("No schedule available. Run initial solve first.")
            else:
                _compute_and_print_metrics(
                    schedule=sched,
                    prev_schedule=prev,
                    staff_assignment=sa,
                    time_slots=current_ds.get("time_slots"),
                )
            continue
        if cmd == "plots":
            out_dir = parts[1] if len(parts) >= 2 else "outputs"
            if persist_store is None:
                print("Plots require persistence (restart with --persist). Skipping.")
            else:
                _generate_plots(
                    run_id=persist_store.run_id,
                    base_dir=str(persist_store.config.get("base_dir", "data")),
                    out_dir=out_dir,
                )
            continue
        if cmd == "reschedule":
            # call solver.reschedule with DataStore object (if available) for persistence
            # and pass current_ds as override data via _data_store_dict in params
            p = dict(params)  # copy
            p["_data_store_dict"] = current_ds  # Provide in-memory data to reschedule
            ds_arg = persist_store if persist_store else current_ds
            try:
                schedule_new, meta_new = reschedule(data_store=ds_arg, change_event=change_event, params=p)
            except Exception as e:
                print("Reschedule failed:", e)
                continue
            if not schedule_new:
                print("No solution produced.")
            else:
                staff_assignment_new = meta_new.get("staff_assignment", {})
                _print_schedule(schedule_new, staff_assignment_new)

                # Comparison metrics
                prev_baseline = current_ds.get("prev_schedule", {}) or {}
                _compute_and_print_metrics(
                    schedule=schedule_new,
                    prev_schedule=prev_baseline,
                    staff_assignment=staff_assignment_new,
                    time_slots=current_ds.get("time_slots"),
                )

                # update baseline to the new solution so subsequent reschedules consider it prev_schedule
                current_ds["prev_schedule"] = schedule_new
                current_ds["prev_staff_assignment"] = staff_assignment_new
                # clear pending changes (assumed applied)
                change_event = {}
            continue

        print("Unknown command. Type 'help' for available commands.")

if __name__ == "__main__":
    main()