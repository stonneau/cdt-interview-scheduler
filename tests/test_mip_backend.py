"""Regression tests: the pure-Python MIP backend must match OR-Tools CP-SAT.

For every scenario the same problem is solved with ``backend="cpsat"`` and
``backend="mip"``.  Checks, in order:

1. same solver status;
2. same objective value when proven optimal;
3. the allocations themselves (candidate -> slot, slot -> staff panel) are
   compared.  Several optimal schedules can exist (ties), so when the MIP
   allocation *differs* from the CP-SAT one it must still be **feasible in the
   CP-SAT formulation**: every x/y variable of the MIP solution is fixed in
   the actual CP-SAT model, which must then solve with exactly the optimal
   objective value;
4. an independent validator re-checks the hard constraints on the MIP output.
"""

import copy
import re

import pytest

pytest.importorskip("scipy")
pytest.importorskip("ortools")

from eval.data_generators import generate_synthetic_dataset  # noqa: E402
from scheduler.solver import reschedule, solve_initial_schedule  # noqa: E402

TOL = 1e-6
STRATEGIES = [
    "full",
    "change_penalty",
    "local_repair",
    "slack_based",
    "fairness_weighted",
    "variance_minimizing",
    "plns",
]


def make_ds(seed, n_c=10, n_s=6, days=3, spd=4, complexity="simple", leads=2,
            require_leads=True, forbid=0):
    d = generate_synthetic_dataset(
        num_candidates=n_c, num_staff=n_s, num_days=days, slots_per_day=spd,
        complexity=complexity, num_leads=leads, require_leads=require_leads, seed=seed,
    )
    ds = copy.deepcopy(d)
    ds["forbidden_pairs"] = set(ds.get("forbidden_pairs") or [])
    non_leads = [s for s in ds["staff"] if not s.startswith("lead")]
    for i in range(forbid):  # deterministic supervisor/candidate conflicts
        ds["forbidden_pairs"].add((ds["candidates"][i], non_leads[i % len(non_leads)]))
    ds["prev_schedule"] = {}
    ds["prev_staff_assignment"] = None
    return ds


def base_slot(t):
    return re.sub(r"\.\d+$", "", t)


def check_hard_constraints(ds, schedule, staff_assignment, params):
    """Independent validation of a schedule against the model's hard constraints."""
    mn = params.get("min_staff_per_slot", 2)
    mx = params.get("max_staff_per_slot", 2)
    assert set(schedule) == set(ds["candidates"])
    assert all(t is not None for t in schedule.values()), "unscheduled candidate"
    slots = list(schedule.values())
    assert len(slots) == len(set(slots)), "two candidates in one slot"
    for c, t in schedule.items():
        assert ds["avail"][c].get(base_slot(t), 0) == 1, f"{c} unavailable at {t}"
        panel = staff_assignment[t]
        assert mn <= len(panel) <= mx, f"panel size {len(panel)} at {t}"
        for s in panel:
            assert ds["staff_avail"][s].get(base_slot(t), 0) == 1, f"{s} unavailable at {t}"
            assert (c, s) not in ds["forbidden_pairs"], f"forbidden pair {(c, s)}"
        req = [s for s in ds["required_staff"].get(c, []) if s in ds["staff"]]
        if req:
            assert set(req) & set(panel), f"no required staff for {c}"
    by_base = {}
    for t, panel in staff_assignment.items():
        for s in panel:
            by_base.setdefault((s, base_slot(t)), []).append(t)
    assert all(len(v) == 1 for v in by_base.values()), "staff in two parallel rooms"


def check_solve(kwargs, result):
    """Independent re-implementation of every hard constraint, on raw x/y values.

    Works on the exact inputs of one solve (so it also covers solves made inside
    a strategy, with frozen slots, parallel groups, lists of required leads...).
    Shares no code with either formulation.
    """
    cands, slots, staff = kwargs["candidates"], kwargs["time_slots"], kwargs["staff"]
    avail, savail = kwargs["avail"], kwargs["staff_avail"]
    mn = kwargs.get("min_staff_per_slot", 2)
    mx = kwargs.get("max_staff_per_slot", 2)
    X = {(c, t): result.value_x(c, t) for c in cands for t in slots}
    Y = {(s, t): result.value_y(s, t) for s in staff for t in slots}
    assert all(v in (0, 1) for v in X.values()) and all(v in (0, 1) for v in Y.values())

    for c in cands:  # 1. exactly one slot
        assert sum(X[c, t] for t in slots) == 1, f"{c} not in exactly one slot"
    for t in slots:  # 2. at most one candidate per slot
        assert sum(X[c, t] for c in cands) <= 1, f"two candidates in {t}"
    for (c, t), v in X.items():  # 3. candidate availability (missing = unavailable)
        assert not v or avail.get(c, {}).get(t, 0) == 1, f"{c} unavailable at {t}"
    for (s, t), v in Y.items():  # 4. staff availability
        assert not v or savail.get(s, {}).get(t, 0) == 1, f"{s} unavailable at {t}"
    for t in slots:  # 5. panel size on occupied slots
        if sum(X[c, t] for c in cands):
            n = sum(Y[s, t] for s in staff)
            assert mn <= n <= mx, f"panel size {n} not in [{mn},{mx}] at {t}"
    for c in cands:  # 6. at least one required staff member
        req = kwargs["required_staff"].get(c, [])
        req = [req] if isinstance(req, str) else req
        req = [s for s in req if s in staff]
        if req:
            for t in slots:
                if X[c, t]:
                    assert any(Y[s, t] for s in req), f"no required staff for {c} at {t}"
    for c, s in kwargs["forbidden_pairs"]:  # 7. forbidden pairs
        for t in slots:
            assert not (X[c, t] and Y[s, t]), f"forbidden pair {(c, s)} at {t}"
    for _base, group in (kwargs.get("parallel_slot_groups") or {}).items():  # 8.
        for s in staff:
            assert sum(Y[s, t] for t in group if t in set(slots)) <= 1, f"{s} in two parallel rooms"
    frozen = set(kwargs.get("frozen_slots") or [])  # 9. frozen slots
    prev = kwargs.get("prev_schedule") or {}
    prev_staff = kwargs.get("prev_staff_assignment") or {}
    for c in cands:
        if prev.get(c) in frozen and prev.get(c) in slots:
            assert X[c, prev[c]] == 1, f"frozen candidate {c} moved"
    for t in frozen & set(slots):
        for c in cands:
            if prev.get(c) != t:
                assert X[c, t] == 0, f"{c} placed in frozen slot {t}"
        for s in staff:
            assert Y[s, t] == (1 if s in set(prev_staff.get(t) or []) else 0), f"staff changed in frozen {t}"


def run_both(fn, ds, params):
    """Run *fn* with each backend; also capture every underlying solve."""
    out = {}
    for backend in ("cpsat", "mip"):
        solves = []
        schedule, meta = fn(ds, {**params, "backend": backend, "persist": False, "time_limit": 30,
                                 "_result_hook": lambda kw, r, _s=solves: _s.append((kw, r))})
        out[backend] = (schedule, meta, solves)
    return out


def normalise(schedule, staff_assignment):
    """Canonical form of an allocation, for equality comparison."""
    return (dict(schedule or {}),
            {t: sorted(p) for t, p in (staff_assignment or {}).items()})


def cpsat_accepts(build_kwargs, result):
    """Fix the MIP solution (all x and y) in the real CP-SAT model and solve it.

    Returns ``(status_name, objective)``; a feasible status means the
    allocation satisfies the CP-SAT formulation, and the objective is the value
    CP-SAT assigns to it.
    """
    from ortools.sat.python import cp_model
    from scheduler.model_builder import build_model

    model, x, y = build_model(**build_kwargs)
    for (c, t), var in x.items():
        model.Add(var == result.value_x(c, t))
    for (s, t), var in y.items():
        model.Add(var == result.value_y(s, t))
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "FEASIBLE", solver.ObjectiveValue()
    return "INFEASIBLE" if status == cp_model.INFEASIBLE else str(status), None


def initial(ds, params):
    return solve_initial_schedule(data_store=copy.deepcopy(ds), params=params)


def assert_same(res, ds=None, params=None):
    (sa, ma, _), (sb, mb, mip_solves) = res["cpsat"], res["mip"]
    if {ma["status"], mb["status"]} == {"OPTIMAL", "FEASIBLE"}:
        # One solver hit the time limit before proving optimality (slow CI runner):
        # the proven-optimal one must be at least as good, and the MIP output must be valid.
        for kwargs, result in mip_solves:
            if result.has_solution:
                check_solve(kwargs, result)
        opt, feas = (ma, mb) if ma["status"] == "OPTIMAL" else (mb, ma)
        assert opt["objective_value"] <= feas["objective_value"] + TOL
        return
    assert ma["status"] == mb["status"], (ma["status"], mb["status"])
    if ma["status"] != "OPTIMAL":
        return
    oa, ob = ma["objective_value"], mb["objective_value"]
    assert abs((oa or 0) - (ob or 0)) <= TOL, f"objective cpsat={oa} mip={ob}"

    for kwargs, result in mip_solves:   # independent validator on every MIP solve
        if result.has_solution:
            check_solve(kwargs, result)

    same_alloc = normalise(sa, ma["staff_assignment"]) == normalise(sb, mb["staff_assignment"])
    if not same_alloc:
        # Different optimal allocation: it must be feasible *and equally good*
        # in the CP-SAT formulation, for every solve the strategy performed.
        for kwargs, result in mip_solves:
            if not result.has_solution:
                continue
            status, obj = cpsat_accepts(kwargs, result)
            assert status == "FEASIBLE", "MIP allocation rejected by the CP-SAT model"
            assert abs(obj - result.objective_value) <= TOL, (
                f"CP-SAT scores the MIP allocation {obj}, MIP says {result.objective_value}")
    if ds is not None:
        check_hard_constraints(ds, sb, mb["staff_assignment"], params or {})
    return same_alloc


# ------------------------------------------------------------ initial solves

@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("fairness", ["none", "min_max", "min_dev", "balanced"])
def test_initial_matches(seed, fairness):
    ds = make_ds(seed, forbid=3)
    params = {"fairness": fairness}
    assert_same(run_both(initial, ds, params), ds, params)


@pytest.mark.parametrize("seed", [1, 2])
def test_initial_parallel_matches(seed):
    # more candidates than slots: only feasible with parallel rooms
    ds = make_ds(seed, n_c=14, n_s=8, days=2, spd=4, leads=3)
    params = {"fairness": "min_dev", "allow_parallel": True, "max_parallel": 2}
    res = run_both(initial, ds, params)
    assert res["mip"][1]["status"] in ("OPTIMAL", "FEASIBLE")
    assert_same(res, ds, params)


def test_initial_medium_complexity_and_panel_size():
    ds = make_ds(7, n_c=8, n_s=7, complexity="medium", leads=2)
    params = {"fairness": "min_dev", "min_staff_per_slot": 3, "max_staff_per_slot": 3}
    assert_same(run_both(initial, ds, params), ds, params)


def test_initial_infeasible_matches():
    ds = make_ds(4, n_c=6, n_s=4, days=1, spd=3)  # 6 candidates, 3 slots
    res = run_both(initial, ds, {"fairness": "min_dev"})
    assert res["cpsat"][1]["status"] == res["mip"][1]["status"] == "INFEASIBLE"


# ----------------------------------------------------------- rescheduling

def staged_change_events(ds, schedule, staff_assignment):
    """Representative disruptions derived from the published schedule."""
    cands = sorted(schedule)
    some_slot = schedule[cands[0]]
    leads = [s for s in ds["staff"] if s.startswith("lead")]
    others = [s for s in ds["staff"] if not s.startswith("lead")]
    return {
        "staff_unavailable": {"staff_unavailable": [(staff_assignment[some_slot][0], some_slot)]},
        "candidate_unavailable": {"candidate_unavailable": [(cands[1], schedule[cands[1]])]},
        "remove_candidate": {"remove_candidate": [cands[2]]},
        "add_candidate": {"add_candidate": ["newcomer"]},
        "staff_removed": {"staff_removed": [others[0]]},
        "lead_unavailable": {"staff_unavailable": [(leads[0], t) for t, p in staff_assignment.items()
                                                    if leads[0] in p][:2]},
    }


def reschedule_case(seed, **kw):
    ds = make_ds(seed, **kw)
    base = {"fairness": "min_dev", "persist": False, "time_limit": 20, "backend": "cpsat"}
    sched, meta = solve_initial_schedule(data_store=copy.deepcopy(ds), params=dict(base))
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")   # a valid baseline is all we need
    ds["prev_schedule"] = sched
    ds["prev_staff_assignment"] = meta["staff_assignment"]
    return ds, staged_change_events(ds, sched, meta["staff_assignment"])


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("event", ["staff_unavailable", "candidate_unavailable",
                                   "remove_candidate", "add_candidate",
                                   "staff_removed", "lead_unavailable"])
def test_reschedule_matches(strategy, event):
    ds, events = reschedule_case(11, n_c=10, n_s=7, days=3, spd=4)

    def fn(d, p):
        return reschedule(data_store=copy.deepcopy(d), change_event=events[event],
                          params={**p, "strategy": strategy})

    assert_same(run_both(fn, ds, {"fairness": "min_dev"}))


@pytest.mark.parametrize("strategy", ["change_penalty", "local_repair", "variance_minimizing"])
def test_reschedule_with_frozen_slots_matches(strategy):
    ds, events = reschedule_case(12, n_c=10, n_s=7, days=3, spd=4)
    first_day = sorted({t.split()[0] for t in ds["time_slots"]})[0]
    frozen = {t for t in ds["time_slots"] if t.startswith(first_day)}

    def fn(d, p):
        return reschedule(data_store=copy.deepcopy(d), change_event=events["staff_removed"],
                          params={**p, "strategy": strategy, "frozen_slots": frozen})

    assert_same(run_both(fn, ds, {"fairness": "min_dev"}))


@pytest.mark.parametrize("strategy", ["change_penalty", "local_repair"])
def test_reschedule_parallel_matches(strategy):
    ds = make_ds(13, n_c=12, n_s=8, days=2, spd=4, leads=3)
    base = {"fairness": "min_dev", "allow_parallel": True, "max_parallel": 2,
            "persist": False, "time_limit": 20, "backend": "cpsat"}
    sched, meta = solve_initial_schedule(data_store=copy.deepcopy(ds), params=dict(base))
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")   # a valid baseline is all we need
    ds["prev_schedule"], ds["prev_staff_assignment"] = sched, meta["staff_assignment"]
    t0 = sorted(sched.values())[0]
    event = {"staff_unavailable": [(meta["staff_assignment"][t0][0], t0)]}

    def fn(d, p):
        return reschedule(data_store=copy.deepcopy(d), change_event=event,
                          params={**p, "strategy": strategy})

    assert_same(run_both(fn, ds, {"fairness": "min_dev", "allow_parallel": True,
                                  "max_parallel": 2}))


# ------------------------------------------- negative controls for the checker

def _mip_solution(ds, params):
    """Solve with MIP and return (build_kwargs, result) of the single solve."""
    solves = []
    solve_initial_schedule(data_store=copy.deepcopy(ds), params={
        **params, "backend": "mip", "persist": False, "time_limit": 60,
        "_result_hook": lambda kw, r: solves.append((kw, r))})
    (kwargs, result), = solves
    return kwargs, result


class _Patched:
    """A MIP result whose x/y values are overridden, to build bad allocations."""

    def __init__(self, result, x=None, y=None):
        self._r, self._x, self._y = result, x or {}, y or {}

    def value_x(self, c, t):
        return self._x.get((c, t), self._r.value_x(c, t))

    def value_y(self, s, t):
        return self._y.get((s, t), self._r.value_y(s, t))


def _scenario():
    ds = make_ds(21, n_c=8, n_s=7, days=3, spd=4, leads=2, forbid=2)
    params = {"fairness": "min_dev"}
    kwargs, res = _mip_solution(ds, params)
    assert res.has_solution
    sched = {c: next(t for t in kwargs["time_slots"] if res.value_x(c, t)) for c in kwargs["candidates"]}
    return ds, kwargs, res, sched


def test_checker_accepts_the_true_solution():
    _, kwargs, res, _ = _scenario()
    status, obj = cpsat_accepts(kwargs, res)
    assert status == "FEASIBLE" and abs(obj - res.objective_value) <= TOL


def test_checker_rejects_corrupted_solutions():
    """The CP-SAT acceptance check must be able to FAIL, otherwise it proves nothing."""
    ds, kwargs, res, sched = _scenario()
    slots, staff = kwargs["time_slots"], kwargs["staff"]
    c0, c1 = sorted(sched)[:2]
    t0, t1 = sched[c0], sched[c1]
    panel0 = [s for s in staff if res.value_y(s, t0)]
    outsiders = [s for s in staff if s not in panel0 and kwargs["staff_avail"][s].get(t0) == 1]

    bad = {}
    # a) candidate moved to a slot where they are unavailable
    unavailable = next((t for t in slots if kwargs["avail"][c0].get(t, 0) != 1), None)
    if unavailable:
        bad["candidate in unavailable slot"] = _Patched(
            res, x={(c0, t0): 0, (c0, unavailable): 1})
    # b) two candidates in the same slot
    bad["two candidates in one slot"] = _Patched(res, x={(c1, t1): 0, (c1, t0): 1})
    # c) panel too big (3 staff instead of 2)
    if outsiders:
        bad["panel of 3"] = _Patched(res, y={(outsiders[0], t0): 1})
    # d) panel too small (1 staff)
    bad["panel of 1"] = _Patched(res, y={(panel0[0], t0): 0})
    # e) a required lead removed from the panel
    leads = [s for s in panel0 if s.startswith("lead")]
    if leads:
        bad["no lead on panel"] = _Patched(res, y={(s, t0): 0 for s in leads})
    # f) a forbidden supervisor placed on the panel
    for (c, s) in kwargs["forbidden_pairs"]:
        t = sched[c]
        if kwargs["staff_avail"][s].get(t) == 1:
            bad["forbidden pair on panel"] = _Patched(res, y={(s, t): 1})
            break

    assert len(bad) >= 4, "scenario too weak to exercise the checker"
    for name, patched in bad.items():
        status, _ = cpsat_accepts(kwargs, patched)
        assert status != "FEASIBLE", f"CP-SAT accepted a corrupted solution: {name}"


def test_checker_detects_a_wrong_objective():
    """Feasible but suboptimal allocation: accepted, with a strictly worse objective."""
    ds = make_ds(21, n_c=8, n_s=7, days=3, spd=4, leads=2, forbid=2)
    kwargs, res = _mip_solution(ds, {"fairness": "min_dev", "allow_idle_staff": True})  # original model
    sched = {c: next(t for t in kwargs["time_slots"] if res.value_x(c, t)) for c in kwargs["candidates"]}
    # Add a phantom staff on an EMPTY slot: still feasible (CP-SAT leaves empty slots free)
    # but it unbalances the workload, so CP-SAT must score it worse.
    occupied = set(sched.values())
    empty = next(t for t in kwargs["time_slots"] if t not in occupied)
    free = next(s for s in kwargs["staff"]
                if kwargs["staff_avail"][s].get(empty) == 1 and res.value_y(s, empty) == 0)
    status, obj = cpsat_accepts(kwargs, _Patched(res, y={(free, empty): 1}))
    assert status == "FEASIBLE"
    assert obj > res.objective_value + TOL


def test_independent_validator_rejects_corrupted_solutions():
    """check_solve must be able to fail too (same corruptions as the CP-SAT check)."""
    ds, kwargs, res, sched = _scenario()
    check_solve(kwargs, res)  # the true solution passes
    slots, staff = kwargs["time_slots"], kwargs["staff"]
    c0, c1 = sorted(sched)[:2]
    t0, t1 = sched[c0], sched[c1]
    panel0 = [s for s in staff if res.value_y(s, t0)]
    outsiders = [s for s in staff if s not in panel0 and kwargs["staff_avail"][s].get(t0) == 1]
    bad = [_Patched(res, x={(c1, t1): 0, (c1, t0): 1}),            # two candidates in a slot
           _Patched(res, y={(panel0[0], t0): 0}),                   # panel too small
           _Patched(res, x={(c0, t0): 0})]                          # candidate unscheduled
    if outsiders:
        bad.append(_Patched(res, y={(outsiders[0], t0): 1}))        # panel too big
    unavailable = next((t for t in slots if kwargs["avail"][c0].get(t, 0) != 1), None)
    if unavailable:
        bad.append(_Patched(res, x={(c0, t0): 0, (c0, unavailable): 1}))
    for patched in bad:
        with pytest.raises(AssertionError):
            check_solve(kwargs, patched)


# --------------------------------------------- identical allocations (tie-break stage)

@pytest.mark.parametrize("seed", [1, 2, 3, 4])
@pytest.mark.parametrize("fairness", ["none", "min_max", "min_dev", "balanced"])
def test_same_allocation_with_tie_break(seed, fairness):
    """Optimal allocations are not unique; the deterministic tie-break stage picks the same
    one in CP-SAT and in MIP, and the same one on every run."""
    ds = make_ds(seed, n_c=9, n_s=6, forbid=2)
    params = {"fairness": fairness}
    res = run_both(initial, ds, params)
    (sa, ma, _), (sb, mb, _) = res["cpsat"], res["mip"]
    if not ma["status"] == mb["status"] == "OPTIMAL":
        pytest.skip("a solver hit its time limit on this machine (optimality not proven)")
    assert normalise(sa, ma["staff_assignment"]) == normalise(sb, mb["staff_assignment"])
    again = run_both(initial, ds, params)["mip"]
    assert normalise(again[0], again[1]["staff_assignment"]) == normalise(sb, mb["staff_assignment"])


def test_same_allocation_when_rescheduling():
    ds, events = reschedule_case(11, n_c=10, n_s=7, days=3, spd=4)
    for strategy in ("change_penalty", "local_repair", "variance_minimizing"):
        def fn(d, p, strategy=strategy):
            return reschedule(data_store=copy.deepcopy(d), change_event=events["staff_unavailable"],
                              params={**p, "strategy": strategy})
        res = run_both(fn, ds, {"fairness": "min_dev"})
        (sa, ma, _), (sb, mb, _) = res["cpsat"], res["mip"]
        if not ma["status"] == mb["status"] == "OPTIMAL":
            continue   # a solver hit its time limit on this machine (optimality not proven)
        assert normalise(sa, ma["staff_assignment"]) == normalise(sb, mb["staff_assignment"]), strategy
