"""Randomised cross-check of the MIP backend against CP-SAT (not collected by pytest).

    python tests/fuzz_backends.py [N_CASES] [FIRST_SEED]

Each case draws a random instance (sizes, availability density, 1-3 leads with
CDT-style "at least one of all leads" lists or single leads, forbidden pairs,
panel size bounds, fairness mode, parallel rooms), solves it with both
backends, then applies 1-3 random disruptions (optionally with frozen slots)
and reschedules with a random strategy.  For every solve it checks:
status equality, objective equality, the independent validator on the MIP
solution and, when allocations differ, acceptance of the MIP solution by the
real CP-SAT model with the same objective.
"""

import copy
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import test_mip_backend as T  # noqa: E402
from scheduler.solver import reschedule, solve_initial_schedule  # noqa: E402


def random_case(seed):
    rng = random.Random(seed)
    leads = rng.choice([1, 2, 3])
    ds = T.make_ds(
        seed, n_c=rng.randint(4, 14), n_s=rng.randint(max(4, leads + 2), 9),
        days=rng.randint(2, 4), spd=rng.randint(3, 5),
        complexity=rng.choice(["simple", "medium", "complex"]), leads=leads,
        require_leads=rng.random() < 0.7, forbid=rng.randint(0, 4))
    if rng.random() < 0.5:  # CDT style: every candidate requires "one of all leads"
        lead_ids = [s for s in ds["staff"] if s.startswith("lead")]
        ds["required_staff"] = {c: list(lead_ids) for c in ds["candidates"]}
    mn, mx = rng.choice([(2, 2), (1, 2), (2, 3), (1, 1), (3, 3)])
    params = {"fairness": rng.choice(["none", "min_max", "min_dev"]),
              "min_staff_per_slot": mn, "max_staff_per_slot": mx}
    if rng.random() < 0.35:
        params.update(allow_parallel=True, max_parallel=rng.choice([2, 3]))
    return rng, ds, params


def random_event(rng, ds, sched, panels):
    ev = {}
    cands = sorted(sched)
    if rng.random() < 0.5 and panels:
        t = rng.choice(sorted(panels))
        ev.setdefault("staff_unavailable", []).append((rng.choice(panels[t]), T.base_slot(t)))
    if rng.random() < 0.4:
        c = rng.choice(cands)
        ev.setdefault("candidate_unavailable", []).append((c, T.base_slot(sched[c])))
    if rng.random() < 0.3 and len(cands) > 3:
        ev["remove_candidate"] = [rng.choice(cands)]
    if rng.random() < 0.3:
        ev["add_candidate"] = [f"new{rng.randint(0, 99)}"]
    if rng.random() < 0.2:
        others = [s for s in ds["staff"] if not s.startswith("lead")]
        ev["staff_removed"] = [rng.choice(others)]
    return ev or {"staff_unavailable": []}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    stats = dict(solves=0, optimal=0, infeasible=0, nonopt=0, identical=0, differing=0)
    t0 = time.time()
    for seed in range(first, first + n):
        rng, ds, params = random_case(seed)
        res = T.run_both(T.initial, ds, params)
        steps = [("initial", res, ds, params)]
        (sa, ma, _) = res["cpsat"]
        if ma["status"] in ("OPTIMAL", "FEASIBLE") and sa:
            ds2 = copy.deepcopy(ds)
            ds2["prev_schedule"], ds2["prev_staff_assignment"] = sa, ma["staff_assignment"]
            panels = {t: p for t, p in ma["staff_assignment"].items()}
            for _ in range(rng.randint(1, 2)):
                ev = random_event(rng, ds2, sa, panels)
                strat = rng.choice(T.STRATEGIES)
                p2 = dict(params)
                if rng.random() < 0.3:
                    days = sorted({T.base_slot(t).split()[0] for t in ds2["time_slots"]})
                    p2["frozen_slots"] = {t for t in ds2["time_slots"] if t.split()[0] == days[0]}

                def fn(d, p, ev=ev, strat=strat):
                    return reschedule(data_store=copy.deepcopy(d), change_event=ev,
                                      params={**p, "strategy": strat})
                steps.append((f"{strat} {sorted(ev)}", T.run_both(fn, ds2, p2), None, p2))
        for label, r, d, p in steps:
            try:
                (sa_, ma_, _), (sb_, mb_, _) = r["cpsat"], r["mip"]
                stats["solves"] += 1
                if ma_["status"] == "OPTIMAL" == mb_["status"]:
                    stats["optimal"] += 1
                    same = T.assert_same(r, d, p)
                    stats["identical" if same else "differing"] += 1
                elif ma_["status"] == mb_["status"] == "INFEASIBLE":
                    stats["infeasible"] += 1
                else:
                    stats["nonopt"] += 1
                    assert ma_["status"] == mb_["status"] or {ma_["status"], mb_["status"]} <= {"OPTIMAL", "FEASIBLE"} , \
                        (ma_["status"], mb_["status"])
                    for kw, rr in r["mip"][2]:
                        if rr.has_solution:
                            T.check_solve(kw, rr)
            except AssertionError as e:
                print(f"MISMATCH seed={seed} step={label}: {e}")
                raise
        if (seed - first + 1) % 25 == 0:
            print(f"  {seed - first + 1}/{n} cases, {stats} [{time.time() - t0:.0f}s]", flush=True)
    print("DONE", stats)


if __name__ == "__main__":
    main()
