"""Solver backends: OR-Tools CP-SAT (default) and a pure-Python MIP backend.

Both backends receive the *same* keyword arguments as
:func:`scheduler.model_builder.build_model` and return a :class:`SolveResult`.
Select one with ``params["backend"]`` (``"cpsat"`` or ``"mip"``).

The MIP backend (:func:`solve_mip`) formulates the identical model as a
mixed-integer linear program and solves it with HiGHS through
``scipy.optimize.milp``.  It needs only numpy and scipy (no native OR-Tools
wheel), so it also runs in the browser through Pyodide.  Correctness against
CP-SAT is checked in ``tests/test_mip_backend.py``.

OR-Tools is imported lazily so that this module (and the MIP path) works
when OR-Tools is not installed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

# OR-Tools CpSolverStatus integer codes, kept so ``cp_status`` metadata is
# identical whichever backend produced it.
CP_UNKNOWN = 0
CP_MODEL_INVALID = 1
CP_FEASIBLE = 2
CP_INFEASIBLE = 3
CP_OPTIMAL = 4

_STATUS_NAMES = {
    CP_OPTIMAL: "OPTIMAL",
    CP_FEASIBLE: "FEASIBLE",
    CP_INFEASIBLE: "INFEASIBLE",
    CP_MODEL_INVALID: "MODEL_INVALID",
    CP_UNKNOWN: "UNKNOWN",
}


@dataclass
class SolveResult:
    """Backend-independent solve outcome."""

    status: int
    objective_value: Optional[float]
    value_x: Callable[[str, str], int]
    value_y: Callable[[str, str], int]
    solve_time: float
    num_conflicts: int = 0
    num_branches: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def status_name(self) -> str:
        return _STATUS_NAMES.get(self.status, str(self.status))

    @property
    def has_solution(self) -> bool:
        return self.status in (CP_OPTIMAL, CP_FEASIBLE)

    @property
    def infeasible(self) -> bool:
        return self.status == CP_INFEASIBLE


def tie_break_weight(kind: str, who: str, slot: str) -> int:
    """Deterministic pseudo-random positive integer for one (candidate|staff, slot) pair.

    Several allocations often have exactly the same objective value.  A second stage
    picks, among the optimal ones, the allocation of minimum total tie-break weight; as
    the weights depend only on names, CP-SAT and MIP (and every run) agree on the choice.
    """
    import zlib
    return zlib.crc32(f"{kind}|{who}|{slot}".encode("utf-8")) % 1048573 + 1


def _remaining(params: Dict[str, Any], elapsed: float):
    tl = params.get("time_limit")
    return None if tl is None else max(1.0, float(tl) - elapsed)


def solve(build_kwargs: Dict[str, Any], params: Dict[str, Any]) -> SolveResult:
    """Build and solve the scheduling model with the backend named in *params*."""
    backend = params.get("backend", "cpsat")
    if backend == "cpsat":
        result = solve_cpsat(build_kwargs, params)
    elif backend == "mip":
        result = solve_mip(build_kwargs, params)
    else:
        raise ValueError(f"unknown backend {backend!r} (expected 'cpsat' or 'mip')")
    # Optional observer, used by the regression tests to capture every solve
    # (model inputs + full solution) made by a strategy.
    hook = params.get("_result_hook")
    if hook is not None:
        hook(build_kwargs, result)
    return result


# --------------------------------------------------------------------- CP-SAT

def solve_cpsat(build_kwargs: Dict[str, Any], params: Dict[str, Any]) -> SolveResult:
    from ortools.sat.python import cp_model
    from scheduler.model_builder import build_model

    model, x, y = build_model(**build_kwargs)
    solver = cp_model.CpSolver()
    if params.get("time_limit") is not None:
        solver.parameters.max_time_in_seconds = float(params["time_limit"])
    if params.get("num_workers") is not None:
        solver.parameters.num_search_workers = int(params["num_workers"])
    if params.get("random_seed") is not None:
        try:
            solver.parameters.random_seed = int(params["random_seed"])
        except Exception:
            pass
    if params.get("deterministic") is not None:
        try:
            solver.parameters.randomize_search = not bool(params["deterministic"])
        except Exception:
            pass

    start = time.time()
    status = int(solver.Solve(model))

    objective = None
    if status in (CP_OPTIMAL, CP_FEASIBLE):
        try:
            objective = solver.ObjectiveValue()
        except Exception:
            objective = None

    # Stage 2 (tie-break): among allocations of optimal cost, take the one of minimum
    # name-derived weight, so that every backend and every run returns the same allocation.
    if params.get("tie_break", True) and status == CP_OPTIMAL:
        main = getattr(model, "_main_objective", None)
        if main is not None:
            model.Add(main <= int(round(objective)))
        model.Minimize(
            sum(tie_break_weight("x", c, t) * var for (c, t), var in x.items())
            + sum(tie_break_weight("y", s_, t) * var for (s_, t), var in y.items()))
        solver2 = cp_model.CpSolver()
        solver2.parameters.CopyFrom(solver.parameters)
        rem = _remaining(params, time.time() - start)
        if rem is not None:
            solver2.parameters.max_time_in_seconds = rem
        st2 = int(solver2.Solve(model))
        if st2 in (CP_OPTIMAL, CP_FEASIBLE):
            solver = solver2          # same main-objective value, canonical allocation
    solve_time = time.time() - start

    def value_x(c, t):
        try:
            return int(solver.Value(x[c, t]))
        except Exception:
            return 0

    def value_y(s, t):
        try:
            return int(solver.Value(y[s, t]))
        except Exception:
            return 0

    return SolveResult(
        status=status,
        objective_value=objective,
        value_x=value_x,
        value_y=value_y,
        solve_time=solve_time,
        num_conflicts=solver.NumConflicts(),
        num_branches=solver.NumBranches(),
    )


# ------------------------------------------------------------------------ MIP

def solve_mip(build_kwargs: Dict[str, Any], params: Dict[str, Any]) -> SolveResult:
    """Solve the same model as ``build_model`` as a MIP with HiGHS (scipy)."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    a = build_kwargs
    candidates = list(a["candidates"])
    time_slots = list(a["time_slots"])
    staff = list(a["staff"])
    avail = a.get("avail") or {}
    staff_avail = a.get("staff_avail") or {}
    required_staff = a.get("required_staff") or {}
    forbidden_pairs = a.get("forbidden_pairs") or []
    prev_schedule = a.get("prev_schedule")
    prev_staff_assignment = a.get("prev_staff_assignment")
    min_staff = a.get("min_staff_per_slot", 2)
    max_staff = a.get("max_staff_per_slot", 2)
    fairness = a.get("fairness", "none")
    w_staff = a.get("staff_change_penalty_weight", 1)
    penalty_scale = a.get("penalty_scale", 1)
    fairness_weight = a.get("fairness_weight", 1)
    w_cand = a.get("candidate_change_penalty_weight", 5)
    groups = a.get("parallel_slot_groups")
    frozen = frozenset(a.get("frozen_slots") or [])
    allow_idle = bool(a.get("allow_idle_staff", False))

    C, T, S = len(candidates), len(time_slots), len(staff)
    c_idx = {c: i for i, c in enumerate(candidates)}
    s_idx = {s: i for i, s in enumerate(staff)}
    t_idx = {t: i for i, t in enumerate(time_slots)}
    t_set = set(time_slots)

    # Variable layout: x[c,t] | y[s,t] | aux (max_load, dev_s)
    def xi(c, t):
        return c_idx[c] * T + t_idx[t]

    def yi(s, t):
        return C * T + s_idx[s] * T + t_idx[t]

    n_xy = C * T + S * T
    aux = {}
    n = n_xy
    if fairness == "min_max":
        aux["max_load"] = n
        n += 1
    elif fairness in ("min_dev", "variance"):
        for s in staff:
            aux[("dev", s)] = n
            n += 1
    balanced_groups = []
    balanced_lead_set = set()
    if fairness == "balanced":
        from scheduler.model_builder import _lead_set
        lead_set = _lead_set(required_staff, staff)
        balanced_lead_set = lead_set
        for gi, group in enumerate(g for g in ([s for s in staff if s in lead_set],
                                               [s for s in staff if s not in lead_set]) if len(g) > 1):
            aux[("hi", gi)], aux[("lo", gi)] = n, n + 1
            balanced_groups.append((gi, group))
            n += 2

    lb = np.zeros(n)
    ub = np.ones(n)
    if "max_load" in aux:
        ub[aux["max_load"]] = T
    for s in staff:
        if ("dev", s) in aux:
            ub[aux[("dev", s)]] = T
    for gi, _g in balanced_groups:
        ub[aux[("hi", gi)]] = ub[aux[("lo", gi)]] = T
    integrality = np.zeros(n)
    integrality[:n_xy] = 1
    # Workload aggregates are integers too: declaring it tightens HiGHS' bound (optimality proofs).
    integrality[n_xy:] = 1

    # Availability (missing keys -> unavailable)
    for c in candidates:
        row = avail.get(c, {})
        for t in time_slots:
            if row.get(t, 0) != 1:
                ub[xi(c, t)] = 0
    for s in staff:
        row = staff_avail.get(s, {})
        for t in time_slots:
            if row.get(t, 0) != 1:
                ub[yi(s, t)] = 0

    # Frozen slots
    frozen_cands = set()
    if frozen and prev_schedule:
        for c in candidates:
            pt = prev_schedule.get(c)
            if pt is not None and pt in frozen and pt in t_set:
                lb[xi(c, pt)] = 1
                frozen_cands.add(c)
    if frozen and prev_staff_assignment:
        for t, ids in prev_staff_assignment.items():
            if t in frozen and t in t_set:
                for s in (ids or []):
                    if s in s_idx:
                        lb[yi(s, t)] = 1
    prev_staff_by_slot = {t: set(ids or []) for t, ids in (prev_staff_assignment or {}).items()}
    for t in frozen:
        if t not in t_set:
            continue
        for c in candidates:
            if c not in frozen_cands:
                ub[xi(c, t)] = 0
        for s in staff:
            if s not in prev_staff_by_slot.get(t, set()):
                ub[yi(s, t)] = 0

    rows, cols, vals, row_lo, row_hi = [], [], [], [], []
    n_rows = 0

    def add_row(entries, lo, hi):
        nonlocal n_rows
        for j, v in entries:
            rows.append(n_rows)
            cols.append(j)
            vals.append(v)
        row_lo.append(lo)
        row_hi.append(hi)
        n_rows += 1

    inf = np.inf
    # 1. each candidate in exactly one slot
    for c in candidates:
        add_row([(xi(c, t), 1.0) for t in time_slots], 1, 1)
    # 2. at most one candidate per slot
    for t in time_slots:
        add_row([(xi(c, t), 1.0) for c in candidates], -inf, 1)
    # 5. staff count per occupied slot (sum(x) at a slot is its has_candidate indicator, <= 1).
    #    Unless idle staff are allowed (original model), nobody is assigned to an empty slot.
    for t in time_slots:
        sum_x = [(xi(c, t), 1.0) for c in candidates]
        sum_y = [(yi(s, t), 1.0) for s in staff]
        if allow_idle:   # original model: with no candidate the staff count is free (0..|S|)
            add_row(sum_y + [(j, -float(min_staff)) for j, _ in sum_x], 0, inf)
            add_row(sum_y + [(j, float(S - max_staff)) for j, _ in sum_x], -inf, S)
        else:
            for s in staff:
                add_row([(yi(s, t), 1.0)] + [(j, -1.0) for j, _ in sum_x], -inf, 0)
            add_row(sum_y + [(j, -float(min_staff)) for j, _ in sum_x], 0, inf)
            add_row(sum_y + [(j, -float(max_staff)) for j, _ in sum_x], -inf, 0)
    # 6. required staff: at least one required member on the panel
    for c in candidates:
        req = required_staff.get(c, [])
        if isinstance(req, str):
            req = [req]
        req_valid = [s for s in req if s in s_idx]
        if req_valid:
            for t in time_slots:
                add_row([(yi(s, t), 1.0) for s in req_valid] + [(xi(c, t), -1.0)], 0, inf)
    # 7. forbidden pairs
    for c, s in forbidden_pairs:
        for t in time_slots:
            add_row([(yi(s, t), 1.0), (xi(c, t), 1.0)], -inf, 1)
    # 8. parallel exclusivity
    if groups:
        for s in staff:
            for _base, group in groups.items():
                valid = [t for t in group if t in t_set]
                if len(valid) > 1:
                    add_row([(yi(s, t), 1.0) for t in valid], -inf, 1)

    # Objective
    cost = np.zeros(n)
    const = 0.0
    if prev_schedule or prev_staff_assignment:
        if prev_schedule:
            for c in candidates:
                if c in frozen_cands:
                    continue
                pt = prev_schedule.get(c)
                for t in time_slots:
                    if pt is None or pt != t:
                        cost[xi(c, t)] += penalty_scale * w_cand
        if prev_staff_assignment:
            prev_pairs = {(s, t) for t, ids in prev_staff_assignment.items()
                          for s in ids if s in s_idx and t in t_set}
            for s in staff:
                for t in time_slots:
                    if t in frozen:
                        continue
                    if (s, t) in prev_pairs:
                        const += penalty_scale * w_staff
                        cost[yi(s, t)] -= penalty_scale * w_staff
                    else:
                        cost[yi(s, t)] += penalty_scale * w_staff

    if fairness == "min_max":
        cost[aux["max_load"]] += fairness_weight
        for s in staff:
            add_row([(yi(s, t), 1.0) for t in time_slots] + [(aux["max_load"], -1.0)], -inf, 0)
    elif fairness == "balanced":
        from scheduler.model_builder import BALANCED_RANGE_WEIGHT
        for s in balanced_lead_set:     # avoidable extra leads (see build_model)
            for t in time_slots:
                cost[yi(s, t)] += fairness_weight
        for gi, group in balanced_groups:
            hi, lo = aux[("hi", gi)], aux[("lo", gi)]
            cost[hi] += BALANCED_RANGE_WEIGHT * fairness_weight
            cost[lo] -= BALANCED_RANGE_WEIGHT * fairness_weight
            for s in group:
                cnt = [(yi(s, t), 1.0) for t in time_slots]
                add_row(cnt + [(hi, -1.0)], -inf, 0)                       # cnt <= hi
                add_row([(j, -v) for j, v in cnt] + [(lo, 1.0)], -inf, 0)  # lo <= cnt
    elif fairness in ("min_dev", "variance"):
        avg_int = (C * min_staff) // max(S, 1)
        for s in staff:
            d = aux[("dev", s)]
            cost[d] += fairness_weight
            cnt = [(yi(s, t), 1.0) for t in time_slots]
            add_row(cnt + [(d, -1.0)], -inf, avg_int)    # cnt - dev <= avg
            add_row([(j, -v) for j, v in cnt] + [(d, -1.0)], -inf, -avg_int)  # avg - cnt <= dev

    if groups:
        suffix = {m for g in groups.values() for m in g[1:]}
        for c in candidates:
            for t in time_slots:
                if t in suffix:
                    cost[xi(c, t)] += 1

    constraints = []
    if n_rows:
        A = coo_matrix((vals, (rows, cols)), shape=(n_rows, n)).tocsr()
        constraints = [LinearConstraint(A, np.array(row_lo, dtype=float), np.array(row_hi, dtype=float))]

    options = {"disp": False, "mip_rel_gap": float(params.get("mip_rel_gap", 0.0))}
    if params.get("time_limit") is not None:
        options["time_limit"] = float(params["time_limit"])

    start = time.time()
    try:
        res = milp(c=cost, constraints=constraints, integrality=integrality,
                   bounds=Bounds(lb, ub), options=options)
    except Exception:  # malformed model
        return SolveResult(CP_MODEL_INVALID, None, lambda c, t: 0, lambda s, t: 0,
                           time.time() - start)
    main_res = res

    # Stage 2 (tie-break): see tie_break_weight().  Keep the main objective at its optimum
    # (cost . z <= optimum) and minimise the name-derived weights.
    if params.get("tie_break", True) and res.status == 0 and res.x is not None:
        tie = np.zeros(n)
        for c in candidates:
            for t in time_slots:
                tie[xi(c, t)] = tie_break_weight("x", c, t)
        for s_ in staff:
            for t in time_slots:
                tie[yi(s_, t)] = tie_break_weight("y", s_, t)
        cons2 = list(constraints)
        if np.any(cost):
            cons2.append(LinearConstraint(cost.reshape(1, -1), -np.inf,
                                          float(res.fun) + 1e-6 * (1.0 + abs(res.fun))))
        opts2 = dict(options)
        rem = _remaining(params, time.time() - start)
        if rem is not None:
            opts2["time_limit"] = rem
        try:
            res2 = milp(c=tie, constraints=cons2, integrality=integrality,
                        bounds=Bounds(lb, ub), options=opts2)
            if res2.x is not None and res2.status in (0, 1):
                res = res2
        except Exception:
            pass
    solve_time = time.time() - start

    # scipy status: 0 optimal, 1 limit reached, 2 infeasible, 3 unbounded, 4 other
    if main_res.status == 0:
        status = CP_OPTIMAL
    elif main_res.status == 1:
        status = CP_FEASIBLE if main_res.x is not None else CP_UNKNOWN
    elif main_res.status == 2:
        status = CP_INFEASIBLE
    elif main_res.status == 3:
        status = CP_MODEL_INVALID
    else:
        status = CP_UNKNOWN

    xs = res.x
    objective = None
    if status in (CP_OPTIMAL, CP_FEASIBLE) and xs is not None:
        objective = float(main_res.fun) + const     # value of the main objective, not the tie-break

    def value_x(c, t):
        return int(round(xs[xi(c, t)])) if xs is not None else 0

    def value_y(s, t):
        return int(round(xs[yi(s, t)])) if xs is not None else 0

    return SolveResult(status=status, objective_value=objective, value_x=value_x,
                       value_y=value_y, solve_time=solve_time,
                       extra={"mip_gap": getattr(res, "mip_gap", None)})
