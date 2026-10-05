"""Compare the CP-SAT and MIP backends at CDT scale (data/cdt_example).

    python examples/make_cdt_example_data.py     # once
    python examples/benchmark_backends.py [--no-parallel] [--time-limit 120]

Replays the four events of ``cdt_walkthrough.py`` with each backend from the
same published schedule, and prints status, objective value and solve time.
Equal objective values mean the two backends found equally good schedules.
"""

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.cdt_walkthrough import CDT_PARAMS, load_cdt_dataset  # noqa: E402
from scheduler.solver import reschedule, solve_initial_schedule  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-parallel", action="store_true", help="disable parallel interview rooms")
    ap.add_argument("--time-limit", type=float, default=120)
    ap.add_argument("--fairness", default="min_dev")
    args = ap.parse_args()

    base = {**CDT_PARAMS, "time_limit": args.time_limit, "fairness": args.fairness}
    if args.no_parallel:
        base["allow_parallel"] = False

    ds0 = load_cdt_dataset()
    # Reference baseline: the CP-SAT initial schedule, shared by both backends.
    sched0, meta0 = solve_initial_schedule(data_store=copy.deepcopy(ds0), params={**base, "backend": "cpsat"})
    ds0["prev_schedule"], ds0["prev_staff_assignment"] = sched0, meta0["staff_assignment"]

    assigned = ds0["prev_staff_assignment"]
    non_lead = next(s for s in ds0["staff"] if not s.startswith("lead"))
    some = [(non_lead, t) for t, p in assigned.items() if non_lead in p][:3]
    events = [
        ("initial", None, None),
        ("add 4 candidates", {"add_candidate": [f"New-{i}" for i in range(4)]}, "local_repair"),
        (f"{non_lead} unavailable x{len(some)}", {"staff_unavailable": some}, "local_repair"),
        ("same, change_penalty", {"staff_unavailable": some}, "change_penalty"),
        ("same, variance_minimizing", {"staff_unavailable": some}, "variance_minimizing"),
    ]
    print(f"{'event':32s}{'backend':8s}{'status':10s}{'objective':>12s}{'time (s)':>10s}")
    for name, ev, strat in events:
        for backend in ("cpsat", "mip"):
            p = {**base, "backend": backend}
            if ev is None:
                _, m = solve_initial_schedule(data_store=copy.deepcopy(load_cdt_dataset()), params=p)
            else:
                _, m = reschedule(data_store=copy.deepcopy(ds0),
                                  change_event=ev, params={**p, "strategy": strat})
            obj = m["objective_value"]
            print(f"{name:32s}{backend:8s}{m['status']:10s}"
                  f"{('-' if obj is None else f'{obj:.1f}'):>12s}{m['solve_time_seconds']:>10.2f}")


if __name__ == "__main__":
    main()
