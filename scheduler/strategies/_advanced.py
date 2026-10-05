"""
Advanced rescheduling strategies: local_repair, slack_based, fairness_weighted,
greedy_least_loaded, and variance_minimizing.
"""

from typing import Any, Dict, List, Set, Tuple
import copy
from ortools.sat.python import cp_model

from scheduler.strategies._core import _solve_model
from scheduler.strategies._basic import change_penalty


def local_repair(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restrict the solver to a local neighbourhood of affected candidates.

    Identifies candidates directly or transitively affected by the disruption,
    expands the neighbourhood by one hop (candidates sharing time-slots), fixes
    all other candidates to their previous assignment, then re-solves.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data including ``prev_schedule``.
    change_event : Dict[str, Any]
        Description of the disruption (candidate_unavailable, staff_unavailable,
        add_candidate, remove_candidate, staff_removed, etc.).
    params : Dict[str, Any]
        Solver parameters. ``max_local_size`` caps the neighbourhood size
        (default: ``max(30, len(candidates) // 2)``).

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    candidates: List[str] = list(ds.get("candidates", []))
    time_slots: List[str] = list(ds.get("time_slots", []))
    prev_schedule: Dict[str, Any] = ds.get("prev_schedule") or {}
    prev_staff_assignment: Dict[str, Any] = ds.get("prev_staff_assignment") or {}

    # Collect initially affected candidates
    affected: Set[str] = set()

    for item in (change_event.get("candidate_unavailable", []) if change_event else []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            c, _ = item
            if c in candidates:
                affected.add(c)
        else:
            c = item
            if c in candidates:
                affected.add(c)

    for c in change_event.get("remove_candidate", []) if change_event else []:
        if c in candidates:
            affected.add(c)
    for c in change_event.get("add_candidate", []) if change_event else []:
        affected.add(c)

    for s_t in (change_event.get("staff_unavailable", []) if change_event else []):
        try:
            s, t = s_t
        except Exception:
            continue
        for c, prev_t in prev_schedule.items():
            if prev_t == t:
                affected.add(c)

    for s in (change_event.get("staff_removed", []) if change_event else []):
        for c, req in (ds.get("required_staff") or {}).items():
            req_list = req if isinstance(req, (list, tuple)) else [req]
            if s in req_list:
                affected.add(c)

    # One-hop expansion
    timeslots_of_affected = {prev_schedule.get(c) for c in affected if prev_schedule.get(c) is not None}
    for c, t in prev_schedule.items():
        if t in timeslots_of_affected:
            affected.add(c)

    # Displacement expansion
    avail_snapshot = ds.get("avail", {})
    candidate_set = set(candidates)
    occupied_by: Dict[str, str] = {}
    for _c, _t in prev_schedule.items():
        if _c in candidate_set:
            occupied_by[_t] = _c

    displaced = set()
    for c in list(affected):
        prev_t = prev_schedule.get(c)
        c_avail = avail_snapshot.get(c, {})
        needs_move = prev_t is None or c_avail.get(prev_t, 0) != 1
        if needs_move:
            for t in time_slots:
                if c_avail.get(t, 0) == 1 and t in occupied_by:
                    blocker = occupied_by[t]
                    if blocker not in affected:
                        displaced.add(blocker)
    affected |= displaced

    # Limit size
    default_max_local = max(30, len(candidates) // 2)
    max_local = int(params.get("max_local_size", default_max_local))
    if len(affected) > max_local:
        affected = set(sorted(affected)[:max_local])

    if not affected or not prev_schedule:
        return change_penalty(data_store, change_event, params)

    # Fix unaffected candidates to their previous slot
    avail = ds.get("avail", {})
    for c in candidates:
        if c not in affected:
            prev_t = prev_schedule.get(c)
            if prev_t is None:
                continue
            if c not in avail:
                avail[c] = {t: 1 for t in time_slots}
            for t in time_slots:
                avail[c][t] = 1 if t == prev_t else 0
    ds["avail"] = avail

    return _solve_model(ds, params, use_prev=True)


def slack_based(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reserve a deterministic fraction of time-slots as slack before solving.

    Only blocks slots that are NOT occupied in the previous schedule, so
    existing assignments are never forced to move just to create slack.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data including ``prev_schedule``.
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver parameters. ``slack_fraction`` (0.0–0.5, default 0.25)
        controls how many slots to reserve.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    params = dict(params)
    params.setdefault("penalty_scale", 100)
    time_slots: List[str] = list(ds.get("time_slots", []))
    slack_fraction = float(params.get("slack_fraction", 0.25))
    if slack_fraction <= 0.0:
        return change_penalty(ds, change_event, params)

    num_to_block = int(len(time_slots) * slack_fraction)
    candidates = ds.get("candidates", [])

    prev_schedule = ds.get("prev_schedule") or {}
    occupied_slots = set(v for v in prev_schedule.values() if v is not None)
    unoccupied = [t for t in time_slots if t not in occupied_slots]

    max_blockable = max(0, len(time_slots) - len(candidates))
    num_to_block = min(num_to_block, max_blockable, len(unoccupied))
    if num_to_block <= 0:
        return change_penalty(ds, change_event, params)

    to_block = set(unoccupied[-num_to_block:])
    avail = ds.get("avail", {})
    for c in candidates:
        if c not in avail:
            avail[c] = {t: 1 for t in time_slots}
        for t in to_block:
            if t in avail[c]:
                avail[c][t] = 0
    ds["avail"] = avail

    ds["time_slots"] = [t for t in time_slots if t not in to_block]

    return _solve_model(ds, params, use_prev=True)


def fairness_weighted(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Schedule with an explicit min-max fairness objective for staff load.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data.
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver parameters. ``fairness_weight`` is scaled by problem size
        if not explicitly provided.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    params = dict(params)
    params["fairness"] = "min_max"
    n_cands = len(ds.get("candidates", []))
    params.setdefault("fairness_weight", max(n_cands, 10))
    params.setdefault("penalty_scale", 50)
    return _solve_model(ds, params, use_prev=True)


def greedy_least_loaded(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Greedy heuristic that assigns each candidate to the least-loaded staff/slot.

    This is not an optimal solver run — it iterates over candidates and greedily
    picks the first feasible slot with the least-loaded staff complement.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data.
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver parameters. ``min_staff_per_slot`` (default 2) controls the
        minimum number of staff assigned to each occupied slot.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    candidates: List[str] = list(ds.get("candidates", []))
    time_slots: List[str] = list(ds.get("time_slots", []))
    staff: List[str] = list(ds.get("staff", []))
    avail = ds.get("avail", {})
    staff_avail = ds.get("staff_avail", {})
    required_staff = ds.get("required_staff", {}) or {}
    parallel_slot_groups = ds.get("parallel_slot_groups") or {}

    min_staff_per_slot = int(params.get("min_staff_per_slot", 2))

    _slot_to_group: Dict[str, str] = {}
    for base, group in parallel_slot_groups.items():
        for member in group:
            _slot_to_group[member] = base

    schedule: Dict[str, Any] = {c: None for c in candidates}
    staff_assignment: Dict[str, List[str]] = {}
    staff_load: Dict[str, int] = {s: 0 for s in staff}
    occupied_slots: Set[str] = set()
    staff_group_assignment: Dict[str, Set[str]] = {s: set() for s in staff}

    def _staff_available_for_slot(member: str, slot: str) -> bool:
        """Check basic availability AND parallel-group exclusivity."""
        if staff_avail.get(member, {}).get(slot, 0) != 1:
            return False
        base = _slot_to_group.get(slot)
        if base and base in staff_group_assignment.get(member, set()):
            return False
        return True

    for c in candidates:
        placed = False
        for t in time_slots:
            if t in occupied_slots:
                continue
            c_av = avail.get(c)
            if c_av is not None and c_av.get(t, 0) != 1:
                continue

            req = required_staff.get(c)
            req_list = []
            if req:
                if isinstance(req, (list, tuple)):
                    req_list = list(req)
                else:
                    req_list = [req]
            ok = True
            for r in req_list:
                if not _staff_available_for_slot(r, t):
                    ok = False
                    break
            if not ok:
                continue

            staff_here: List[str] = list(req_list)
            extra_candidates = [s for s in staff if s not in staff_here and _staff_available_for_slot(s, t)]
            extra_candidates.sort(key=lambda s: staff_load.get(s, 0))
            for s in extra_candidates:
                if len(staff_here) >= min_staff_per_slot:
                    break
                staff_here.append(s)

            if len(staff_here) < min_staff_per_slot:
                continue

            schedule[c] = t
            occupied_slots.add(t)
            staff_assignment[t] = staff_here
            for s in staff_here:
                if s in staff_load:
                    staff_load[s] += 1
                base = _slot_to_group.get(t)
                if base:
                    staff_group_assignment.setdefault(s, set()).add(base)
            placed = True
            break
        if not placed:
            continue

    prev_schedule = ds.get("prev_schedule") or {}
    num_changed = None
    if prev_schedule and schedule:
        num_changed = 0
        for c, new_t in schedule.items():
            old_t = prev_schedule.get(c)
            if old_t != new_t:
                num_changed += 1

    all_assigned = all(v is not None for v in schedule.values())
    status_name = "FEASIBLE" if all_assigned else "INFEASIBLE"

    metadata = {
        "status": status_name,
        "cp_status": int(cp_model.FEASIBLE) if all_assigned else int(cp_model.INFEASIBLE),
        "solve_time_seconds": 0.0,
        "num_conflicts": 0,
        "num_branches": 0,
        "objective_value": None,
        "staff_assignment": staff_assignment,
        "num_changed_assignments": num_changed,
    }

    return schedule, metadata


def variance_minimizing(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Schedule with a variance-minimizing fairness objective for staff load.

    Uses ``fairness='variance'`` (sum of absolute deviations from average load)
    and scales ``fairness_weight`` by problem size so the fairness term competes
    with change penalties.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data.
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver parameters. ``fairness_weight`` and ``penalty_scale`` are set
        to defaults that favour load-balancing if not explicitly provided.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    params = dict(params)
    params["fairness"] = "variance"
    n_cands = len(ds.get("candidates", []))
    params.setdefault("fairness_weight", max(n_cands, 10))
    params.setdefault("penalty_scale", 10)
    return _solve_model(ds, params, use_prev=True)
