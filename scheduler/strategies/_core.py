"""
Core solver helper shared by all rescheduling strategies.
"""

from typing import Any, Dict, List, Tuple
import copy
import time
from ortools.sat.python import cp_model

from scheduler import model_builder


def _solve_model(data_store: Dict[str, Any], params: Dict[str, Any], use_prev: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build and solve a CP-SAT model, returning the schedule and metadata.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data containing candidates, time_slots, avail, staff,
        staff_avail, required_staff, forbidden_pairs, and optionally
        prev_schedule / prev_staff_assignment.
    params : Dict[str, Any]
        Solver and objective parameters such as time_limit, num_workers,
        penalty_scale, fairness, fairness_weight, min_staff_per_slot,
        staff_change_penalty_weight, candidate_change_penalty_weight,
        random_seed, and deterministic.
    use_prev : bool
        Whether to pass previous schedule information to the model builder
        for change-penalty objectives.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata). *schedule* maps each candidate to
        its assigned time-slot (or ``None``). *metadata* contains solver
        statistics and the staff_assignment mapping.
    """
    ds = copy.deepcopy(data_store)
    candidates = list(ds.get("candidates", []))
    time_slots = list(ds.get("time_slots", []))
    if not candidates or not time_slots:
        raise ValueError("data_store must contain 'candidates' and 'time_slots'")

    avail = ds.get("avail", {c: {t: 1 for t in time_slots} for c in candidates})
    staff = list(ds.get("staff", []))
    staff_avail = ds.get("staff_avail", {s: {t: 1 for t in time_slots} for s in staff})
    for s in list(staff):
        if s not in staff_avail:
            staff_avail[s] = {t: 1 for t in time_slots}
    required_staff = ds.get("required_staff", {})
    forbidden_pairs = ds.get("forbidden_pairs", [])
    candidate_set = set(candidates)
    staff_set = set(staff)
    active_forbidden_pairs = {
        (c, s) for c, s in forbidden_pairs
        if c in candidate_set and s in staff_set
    }
    prev_schedule = ds.get("prev_schedule") if use_prev else None
    prev_staff_assignment = ds.get("prev_staff_assignment") if use_prev else None

    min_staff_per_slot = params.get("min_staff_per_slot", 2)
    fairness = params.get("fairness", "min_max")
    staff_change_penalty_weight = params.get("staff_change_penalty_weight", 1)
    candidate_change_penalty_weight = params.get("candidate_change_penalty_weight", 5)
    penalty_scale = params.get("penalty_scale", 1000)
    fairness_weight = params.get("fairness_weight", 1)
    parallel_slot_groups = ds.get("parallel_slot_groups")
    frozen_slots = params.get("frozen_slots") or ds.get("frozen_slots")

    model, x, y = model_builder.build_model(
        candidates=candidates,
        time_slots=time_slots,
        avail=avail,
        staff=staff,
        staff_avail=staff_avail,
        required_staff=required_staff,
        forbidden_pairs=active_forbidden_pairs,
        prev_schedule=prev_schedule,
        prev_staff_assignment=prev_staff_assignment,
        min_staff_per_slot=min_staff_per_slot,
        fairness=fairness,
        staff_change_penalty_weight=staff_change_penalty_weight,
        penalty_scale=penalty_scale,
        fairness_weight=fairness_weight,
        candidate_change_penalty_weight=candidate_change_penalty_weight,
        parallel_slot_groups=parallel_slot_groups,
        frozen_slots=frozen_slots,
    )

    solver = cp_model.CpSolver()
    if params.get("time_limit") is not None:
        solver.parameters.max_time_in_seconds = float(params["time_limit"])
    if params.get("num_workers") is not None:
        solver.parameters.num_search_workers = int(params["num_workers"])

    if params.get("random_seed") is not None:
        try:
            solver.parameters.random_seed = int(params.get("random_seed"))
        except Exception:
            pass
    if params.get("deterministic") is not None:
        try:
            solver.parameters.randomize_search = not bool(params.get("deterministic"))
        except Exception:
            pass

    start = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start

    schedule: Dict[str, Any] = {}
    staff_assignment: Dict[str, List[str]] = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in candidates:
            assigned = None
            for t in time_slots:
                try:
                    if solver.Value(x[c, t]) == 1:
                        assigned = t
                        break
                except Exception:
                    continue
            schedule[c] = assigned

        occupied_slots = set(s for s in schedule.values() if s is not None)

        for t in time_slots:
            staff_list: List[str] = []
            for s in staff:
                try:
                    if solver.Value(y[s, t]) == 1:
                        staff_list.append(s)
                except Exception:
                    continue
            if t in occupied_slots:
                staff_assignment[t] = staff_list

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_name = status_map.get(status, str(status))

    num_changed = None
    if prev_schedule and schedule:
        num_changed = 0
        for c, new_t in schedule.items():
            old_t = prev_schedule.get(c)
            if old_t != new_t:
                num_changed += 1

    metadata = {
        "status": status_name,
        "cp_status": int(status),
        "solve_time_seconds": solve_time,
        "num_conflicts": solver.NumConflicts(),
        "num_branches": solver.NumBranches(),
        "objective_value": None,
        "staff_assignment": staff_assignment,
        "num_changed_assignments": num_changed,
    }
    try:
        if hasattr(solver, "ObjectiveValue") and status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            metadata["objective_value"] = solver.ObjectiveValue()
    except Exception:
        metadata["objective_value"] = None

    return schedule, metadata
