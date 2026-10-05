"""
Core solver helper shared by all rescheduling strategies.
"""

from typing import Any, Dict, List, Tuple
import copy
import time

from scheduler import backends


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
    max_staff_per_slot = params.get("max_staff_per_slot", 2)
    fairness = params.get("fairness", "min_max")
    staff_change_penalty_weight = params.get("staff_change_penalty_weight", 1)
    candidate_change_penalty_weight = params.get("candidate_change_penalty_weight", 5)
    penalty_scale = params.get("penalty_scale", 1000)
    fairness_weight = params.get("fairness_weight", 1)
    parallel_slot_groups = ds.get("parallel_slot_groups")
    frozen_slots = params.get("frozen_slots") or ds.get("frozen_slots")

    result = backends.solve(
        dict(
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
            max_staff_per_slot=max_staff_per_slot,
            fairness=fairness,
            staff_change_penalty_weight=staff_change_penalty_weight,
            penalty_scale=penalty_scale,
            fairness_weight=fairness_weight,
            candidate_change_penalty_weight=candidate_change_penalty_weight,
            parallel_slot_groups=parallel_slot_groups,
            frozen_slots=frozen_slots,
            allow_idle_staff=bool(params.get("allow_idle_staff", False)),
        ),
        params,
    )
    solve_time = result.solve_time

    schedule: Dict[str, Any] = {}
    staff_assignment: Dict[str, List[str]] = {}
    if result.has_solution:
        for c in candidates:
            assigned = None
            for t in time_slots:
                if result.value_x(c, t) == 1:
                    assigned = t
                    break
            schedule[c] = assigned

        occupied_slots = set(s for s in schedule.values() if s is not None)

        for t in time_slots:
            staff_list: List[str] = [s for s in staff if result.value_y(s, t) == 1]
            if t in occupied_slots:
                staff_assignment[t] = staff_list

    num_changed = None
    if prev_schedule and schedule:
        num_changed = 0
        for c, new_t in schedule.items():
            old_t = prev_schedule.get(c)
            if old_t != new_t:
                num_changed += 1

    metadata = {
        "status": result.status_name,
        "cp_status": int(result.status),
        "solve_time_seconds": solve_time,
        "num_conflicts": result.num_conflicts,
        "num_branches": result.num_branches,
        "objective_value": result.objective_value if result.has_solution else None,
        "staff_assignment": staff_assignment,
        "num_changed_assignments": num_changed,
    }

    return schedule, metadata
