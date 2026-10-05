"""Compare the ORIGINAL code (first commit) with the current CP-SAT path (not collected by pytest).

    python tests/compare_with_original.py [N_CASES] [FIRST_SEED] [COMMIT]

The original commit is checked out in a temporary git worktree and run in a subprocess on the
same cases (initial solves and reschedules with every strategy).  The current code is run with
``backend="cpsat"`` and ``allow_idle_staff=True`` (the original model).  Both use one search
thread and a fixed seed, so identical models give identical solutions: the script reports how
many statuses, objectives AND allocations are identical.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import fuzz_backends as F  # noqa: E402
from tests import test_mip_backend as T  # noqa: E402
from scheduler.solver import reschedule, solve_initial_schedule  # noqa: E402

RUNNER = r'''
import json, sys, copy
sys.path.insert(0, ".")
from scheduler.solver import solve_initial_schedule, reschedule
cases = json.load(open(sys.argv[1]))
out = []
def tup(d):
    d = copy.deepcopy(d)
    d["forbidden_pairs"] = {tuple(x) for x in d.get("forbidden_pairs", [])}
    for k in ("staff_unavailable", "candidate_unavailable"):
        pass
    return d
for c in cases:
    ds = tup(c["ds"]); params = c["params"]
    if c["kind"] == "initial":
        s, m = solve_initial_schedule(data_store=ds, params=params)
    else:
        ev = {k: [tuple(x) if isinstance(x, list) else x for x in v] for k, v in c["event"].items()}
        s, m = reschedule(data_store=ds, change_event=ev, params={**params, "strategy": c["strategy"]})
    out.append({"status": m["status"], "objective": m["objective_value"], "schedule": s,
                "panels": {t: sorted(p) for t, p in (m.get("staff_assignment") or {}).items()}})
json.dump(out, open(sys.argv[2], "w"))
'''


def jsonable(ds):
    d = copy.deepcopy(ds)
    d["forbidden_pairs"] = sorted(map(list, d["forbidden_pairs"]))
    return d


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    commit = sys.argv[3] if len(sys.argv) > 3 else subprocess.check_output(
        ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=ROOT, text=True).split()[0]
    work = tempfile.mkdtemp(prefix="orig_", dir=os.path.dirname(ROOT))
    subprocess.check_call(["git", "worktree", "add", "-q", "--detach", work, commit], cwd=ROOT)
    try:
        base = {"num_workers": 1, "random_seed": 0, "time_limit": float(os.environ.get("TIME_LIMIT", 15)), "persist": False}
        cases, new_results = [], []
        for seed in range(first, first + n):
            rng, ds, params = F.random_case(seed)
            if os.environ.get("ONLY_DEFAULT_MAX") and params.get("max_staff_per_slot", 2) != 2:
                continue   # the original ignores max_staff_per_slot when rescheduling (see tally)
            params = {**base, **{k: v for k, v in params.items()}}
            run = [("initial", None, None, ds, params)]
            sched, meta = solve_initial_schedule(data_store=copy.deepcopy(ds),
                                                 params={**params, "backend": "cpsat", "allow_idle_staff": True})
            if sched and meta["status"] in ("OPTIMAL", "FEASIBLE"):
                ds2 = copy.deepcopy(ds)
                ds2["prev_schedule"], ds2["prev_staff_assignment"] = sched, meta["staff_assignment"]
                ev = F.random_event(rng, ds2, sched, meta["staff_assignment"])
                for strat in T.STRATEGIES:
                    run.append(("reschedule", ev, strat, ds2, params))
            print(f"seed {seed}: {len(run)} solves", file=sys.stderr, flush=True)
            for kind, ev, strat, d, p in run:
                case = {"kind": kind, "ds": jsonable(d), "params": p, "event": ev, "strategy": strat}
                cases.append(case)
                if kind == "initial":
                    s, m = solve_initial_schedule(data_store=copy.deepcopy(d),
                                                  params={**p, "backend": "cpsat", "allow_idle_staff": True})
                else:
                    s, m = reschedule(data_store=copy.deepcopy(d), change_event=ev,
                                      params={**p, "backend": "cpsat", "allow_idle_staff": True, "strategy": strat})
                new_results.append({"status": m["status"], "objective": m["objective_value"], "schedule": s,
                                    "panels": {t: sorted(q) for t, q in (m.get("staff_assignment") or {}).items()}})
        cfile, ofile, rfile = (os.path.join(work, x) for x in ("cases.json", "orig.json", "runner.py"))
        json.dump(cases, open(cfile, "w"))
        open(rfile, "w").write(RUNNER)
        subprocess.check_call([sys.executable, rfile, cfile, ofile], cwd=work,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        orig = json.load(open(ofile))
        if os.environ.get("DUMP"):
            json.dump({"cases": cases, "orig": orig, "new": new_results}, open(os.environ["DUMP"], "w"))
        def blank():
            return dict(cases=0, same_status=0, same_objective=0, same_allocation=0, different=[])
        # The original reschedule path ignores max_staff_per_slot (always 2): a deliberate fix,
        # so cases with max != 2 are tallied apart from the ones where the two must agree.
        tally = {"max_staff_per_slot==2": blank(), "max_staff_per_slot!=2": blank()}
        for i, (a, b) in enumerate(zip(orig, new_results)):
            g = tally["max_staff_per_slot==2" if cases[i]["params"].get("max_staff_per_slot", 2) == 2
                      else "max_staff_per_slot!=2"]
            g["cases"] += 1
            g["same_status"] += a["status"] == b["status"]
            both_opt = a["status"] == b["status"] == "OPTIMAL"
            obj_ok = a["status"] == b["status"] and (not both_opt or abs((a["objective"] or 0) - (b["objective"] or 0)) < 1e-6)
            g["same_objective"] += obj_ok
            g["same_allocation"] += (a["schedule"] == b["schedule"] and a["panels"] == b["panels"])
            if not obj_ok:
                g["different"].append((i, cases[i]["kind"], cases[i]["strategy"], a["status"], b["status"], a["objective"], b["objective"]))
        print(json.dumps(tally))
    finally:
        subprocess.call(["git", "worktree", "remove", "--force", work], cwd=ROOT)


if __name__ == "__main__":
    main()
