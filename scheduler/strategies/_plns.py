"""Parallel Large Neighborhood Search (PLNS) — Destroy and Repair strategy.

Based on the "Destroy and Repair" framework described by Shaw (1998).
"""

from typing import Any, Dict, List, Set, Tuple
import copy

from scheduler.strategies._core import _solve_model
from scheduler.strategies._basic import change_penalty


def plns(
    data_store: Dict[str, Any],
    change_event: Dict[str, Any],
    params: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parallel Large Neighborhood Search (PLNS) – Destroy and Repair.

    Identifies a neighbourhood of the schedule affected by the disruption,
    "destroys" (removes) those assignments so the repair solver can reassign
    them optimally, then fixes everything outside the neighbourhood and
    re-solves.

    Parameters
    ----------
    data_store : dict
        Solver input data including candidates, time_slots, avail,
        staff, staff_avail, prev_schedule, prev_staff_assignment, etc.
    change_event : dict
        Disruption descriptor with keys such as ``staff_unavailable``,
        ``candidate_unavailable``, ``remove_candidate``, ``add_candidate``,
        and ``staff_removed``.
    params : dict
        Solver parameters.  ``penalty_scale`` defaults to 100 for PLNS.

    Returns
    -------
    tuple[dict, dict]
        ``(schedule, metadata)`` — the repaired schedule and solver metadata.
    """
    ds = copy.deepcopy(data_store)
    params = dict(params)
    # PLNS repairs a destroyed neighbourhood; a moderate penalty_scale
    # lets the repair solver find better sub-solutions while still
    # preferring to keep non-destroyed assignments stable.
    params.setdefault("penalty_scale", 100)
    candidates: List[str] = list(ds.get("candidates", []))
    time_slots: List[str] = list(ds.get("time_slots", []))
    prev_schedule: Dict[str, Any] = ds.get("prev_schedule") or {}
    prev_staff_assignment: Dict[str, Any] = ds.get("prev_staff_assignment") or {}

    # ------------------------------------------------------------------
    # DESTROY PHASE – identify candidates and slots in the neighbourhood
    # ------------------------------------------------------------------
    destroyed_candidates: Set[str] = set()
    destroyed_slots: Set[str] = set()

    ce = change_event if change_event else {}

    # 1. Staff unavailability disruptions
    for s_t in ce.get("staff_unavailable", []):
        try:
            s, t = s_t
        except Exception:
            continue
        destroyed_slots.add(t)
        for c, prev_t in prev_schedule.items():
            if prev_t == t:
                destroyed_candidates.add(c)
        for c, req in (ds.get("required_staff") or {}).items():
            req_list = req if isinstance(req, (list, tuple)) else [req]
            if s in req_list:
                destroyed_candidates.add(c)

    # 2. Candidate unavailability disruptions
    for item in ce.get("candidate_unavailable", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            c, t = item
            if c in candidates:
                destroyed_candidates.add(c)
                destroyed_slots.add(t)
        else:
            c = item
            if c in candidates:
                destroyed_candidates.add(c)

    # 3. Removed / added candidates
    for c in ce.get("remove_candidate", []):
        if c in candidates:
            destroyed_candidates.add(c)
    for c in ce.get("add_candidate", []):
        destroyed_candidates.add(c)

    # 4. Staff removed entirely
    for s in ce.get("staff_removed", []):
        for c, req in (ds.get("required_staff") or {}).items():
            req_list = req if isinstance(req, (list, tuple)) else [req]
            if s in req_list:
                destroyed_candidates.add(c)

    # --- Sub-scope expansion (related slots / one-hop) -----------------
    for c in list(destroyed_candidates):
        prev_t = prev_schedule.get(c)
        if prev_t is not None:
            destroyed_slots.add(prev_t)

    for c, t in prev_schedule.items():
        if t in destroyed_slots:
            destroyed_candidates.add(c)

    # Ensure destroyed_candidates only contains currently active candidates
    destroyed_candidates &= set(candidates)

    # --- Feasibility-driven expansion ----------------------------------
    avail_raw = ds.get("avail", {})
    staff_avail_raw = ds.get("staff_avail", {})
    required_staff_raw = ds.get("required_staff", {}) or {}
    candidate_set = set(candidates)
    max_expand = len(candidates)

    def _slot_feasible_for(cand: str, slot: str) -> bool:
        """Check candidate availability AND required-staff availability."""
        if avail_raw.get(cand, {}).get(slot, 0) != 1:
            return False
        req = required_staff_raw.get(cand)
        if req:
            req_list = req if isinstance(req, (list, tuple)) else [req]
            for r in req_list:
                if staff_avail_raw.get(r, {}).get(slot, 0) != 1:
                    return False
        return True

    for _ in range(max_expand):
        fixed_slots = {
            prev_schedule[c2]
            for c2 in candidates
            if c2 not in destroyed_candidates and prev_schedule.get(c2) is not None
        }
        needs_more = False
        for c in sorted(destroyed_candidates):
            if c not in candidate_set:
                continue
            has_free = any(
                _slot_feasible_for(c, t) and t not in fixed_slots
                for t in time_slots
            )
            if has_free:
                continue
            for t in sorted(time_slots):
                if not _slot_feasible_for(c, t):
                    continue
                for c2 in sorted(candidates):
                    if c2 in destroyed_candidates:
                        continue
                    if prev_schedule.get(c2) == t:
                        destroyed_candidates.add(c2)
                        destroyed_slots.add(t)
                        needs_more = True
                        break
                if needs_more:
                    break
        if not needs_more:
            break

    # If nothing was destroyed or there is no baseline, fall back to
    # change_penalty which handles re-solving with a penalty objective.
    if not destroyed_candidates or not prev_schedule:
        return change_penalty(data_store, change_event, params)

    # ------------------------------------------------------------------
    # REPAIR PHASE – fix the rest, re-solve the destroyed neighbourhood
    # ------------------------------------------------------------------

    # Remove destroyed candidates from the previous-schedule baseline so
    # the solver does not penalise moving them.
    for c in destroyed_candidates:
        prev_schedule.pop(c, None)

    # Remove staff assignments at destroyed slots so the solver is free
    # to reassign staff there.
    for t in destroyed_slots:
        prev_staff_assignment.pop(t, None)

    ds["prev_schedule"] = prev_schedule
    ds["prev_staff_assignment"] = prev_staff_assignment

    # Fix non-destroyed candidates to their current slot.
    avail = ds.get("avail", {})
    for c in candidates:
        if c not in destroyed_candidates:
            prev_t = prev_schedule.get(c)
            if prev_t is None:
                continue
            if c not in avail:
                avail[c] = {t: 1 for t in time_slots}
            for t in time_slots:
                avail[c][t] = 1 if t == prev_t else 0
    ds["avail"] = avail

    return _solve_model(ds, params, use_prev=True)
