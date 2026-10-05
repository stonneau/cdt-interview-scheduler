"""End-to-end CDT use case: initial schedule, then three disruptions.

Runs from the repository root::

    python examples/make_cdt_example_data.py      # once, creates data/cdt_example/
    python examples/cdt_walkthrough.py

It mirrors the CDT 2026 deployment described in the UG4 report (section 4.6):

1. Initial schedule for ~33 candidates / 16 staff / 160 slots
2. Late applicants are added                        -> ``local_repair``
3. One academic cancels a day                       -> ``local_repair``
4. Industrial action: all staff lost for several days -> ``change_penalty``
   (with sparser real-world availability this can be INFEASIBLE: the solver
   proves it quickly so the coordinator can ask applicants for new availability)
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_models.loaders import (  # noqa: E402
    load_availability_objects_from_csv,
    load_forbidden_pairs_from_csv,
    load_staff_objects_from_csv,
    objects_to_solver_inputs_from_models,
    unify_slots,
)
from scheduler.solver import reschedule, solve_initial_schedule  # noqa: E402

DATA = Path("data/cdt_example")

# ---------------------------------------------------------------- CDT config
# These are the settings used for the CDT 2026 cycle (see d2air.md, section 4).
CDT_PARAMS = {
    "min_staff_per_slot": 2,     # 2-person panels ...
    "max_staff_per_slot": 2,     # ... exactly 2
    "fairness": "min_dev",       # even workload across staff (report: preferred to min_max)
    "allow_parallel": True,      # online interviews: several panels at the same time
    "max_parallel": 2,
    "time_limit": 30,            # seconds, as in the report
    "random_seed": 0,
    "persist": False,
}


def load_cdt_dataset():
    """Load the CSVs and build the solver input dict."""
    cands, slots_a = load_availability_objects_from_csv(str(DATA / "applicants_availabilities.csv"))
    staff, slots_s = load_staff_objects_from_csv(str(DATA / "staff_availabilities.csv"))
    forbidden = load_forbidden_pairs_from_csv(str(DATA / "forbidden_pairs.csv"))
    cids, sids, avail, savail, required, fp = objects_to_solver_inputs_from_models(
        cands, staff, forbidden_pairs=forbidden  # leads auto-detected: ids starting with "lead"
    )
    return {
        "candidates": cids,
        "time_slots": sorted(unify_slots(slots_a, slots_s)),
        "avail": avail,
        "staff": sids,
        "staff_avail": savail,
        "required_staff": required,
        "forbidden_pairs": fp,
        "prev_schedule": {},
        "prev_staff_assignment": None,
    }


def apply_event(ds, event):
    """Mirror a change event onto *ds* so the next reschedule starts from it."""
    ds = copy.deepcopy(ds)
    for s, t in event.get("staff_unavailable", []):
        ds["staff_avail"][s][t] = 0
    for c in event.get("add_candidate", []):
        ds["candidates"].append(c)
        ds["avail"][c] = {t: 1 for t in ds["time_slots"]}
        ds["required_staff"][c] = sorted({l for v in ds["required_staff"].values() for l in v})
    return ds


def report(title, schedule, meta):
    print(f"\n=== {title} ===")
    print(f"status={meta.get('status')}  solve_time={meta.get('solve_time_seconds', 0):.2f}s  "
          f"scheduled={len(schedule or {})}  changed={meta.get('num_changed_assignments')}")


def main():
    ds = load_cdt_dataset()
    leads = sorted({l for v in ds["required_staff"].values() for l in v})
    print(f"{len(ds['candidates'])} candidates, {len(ds['staff'])} staff "
          f"(leads: {', '.join(leads)}), {len(ds['time_slots'])} slots, "
          f"{len(ds['forbidden_pairs'])} forbidden pairs")

    # 1. Initial schedule
    schedule, meta = solve_initial_schedule(data_store=ds, params=dict(CDT_PARAMS))
    report("Event 1: initial schedule", schedule, meta)
    if not schedule:
        return
    ds["prev_schedule"] = schedule
    ds["prev_staff_assignment"] = meta["staff_assignment"]

    def step(title, event, strategy):
        nonlocal ds
        ds = apply_event(ds, event)
        sched, m = reschedule(data_store=ds, change_event=event,
                              params={**CDT_PARAMS, "strategy": strategy})
        report(f"{title} [{strategy}]", sched, m)
        if sched:  # only adopt the new schedule if the solve succeeded
            ds["prev_schedule"] = sched
            ds["prev_staff_assignment"] = m["staff_assignment"]
        return sched

    # 2. Four late applicants
    step("Event 2: 4 candidates added",
         {"add_candidate": [f"Candidate-{i}" for i in (34, 35, 36, 37)]}, "local_repair")

    # 3. One non-lead academic cancels the slots they were assigned to on one day
    busiest = max(ds["staff"], key=lambda s: sum(s in v for v in ds["prev_staff_assignment"].values())
                  if not s.startswith("lead") else -1)
    day = sorted({t.split()[0] for t in ds["prev_staff_assignment"]})[0]
    cancelled = [(busiest, t) for t, v in ds["prev_staff_assignment"].items()
                 if busiest in v and t.startswith(day)]
    cancelled = cancelled or [(busiest, t) for t, v in ds["prev_staff_assignment"].items() if busiest in v][:1]
    step(f"Event 3: {busiest} unavailable for {len(cancelled)} slot(s)",
         {"staff_unavailable": cancelled}, "local_repair")

    # 4. Industrial action: every staff member unavailable for the busiest week
    weeks = {}
    for t in ds["prev_schedule"].values():
        d = t.split()[0]
        weeks.setdefault(d[:8] + str((int(d[8:]) - 1) // 7), set()).add(d)
    lost = sorted(max(weeks.values(), key=len))
    strike = [(s, t) for s in ds["staff"] for t in ds["time_slots"] if t.split()[0] in lost]
    step(f"Event 4: strike on {len(lost)} day(s)", {"staff_unavailable": strike}, "change_penalty")


if __name__ == "__main__":
    main()
