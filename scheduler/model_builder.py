"""Build the CP-SAT constraint model for the interview scheduling problem."""


#: In the "balanced" fairness mode, one unit of (max - min) load counts this many times an
#: extra lead assignment (see build_model).
BALANCED_RANGE_WEIGHT = 4


def _lead_set(required_staff, staff):
    """Staff members that appear in some candidate's required list (the leads)."""
    pool = set(staff)
    out = set()
    for req in (required_staff or {}).values():
        for s in ([req] if isinstance(req, str) else (req or [])):
            if s in pool:
                out.add(s)
    return out


def build_model(
        candidates,
        time_slots,
        avail,
        staff,
        staff_avail,
        required_staff,
        forbidden_pairs,
        prev_schedule=None,
        prev_staff_assignment=None,
        min_staff_per_slot=2,
        max_staff_per_slot=2,
        fairness="none",
        staff_change_penalty_weight=1,
    penalty_scale: int = 1,
    fairness_weight: int = 1,
    candidate_change_penalty_weight: int = 5,
    parallel_slot_groups=None,
    frozen_slots=None,
    allow_idle_staff: bool = False,
):
    """Build the CP-SAT model for the interview scheduling problem.

    Constructs decision variables, hard constraints (availability, frozen
    slots, staff limits, forbidden pairs, parallel exclusivity), and a
    weighted-sum objective combining change penalties and fairness.

    Decision variables
    ~~~~~~~~~~~~~~~~~~
    - ``x[c, t]`` (bool) — candidate *c* is assigned to slot *t*.
    - ``y[s, t]`` (bool) — staff *s* is assigned to slot *t*.
    - ``staff_counts[s]`` (int) — total slots assigned to staff *s* (fairness).
    - ``max_load`` (int, ``min_max`` only) — maximum staff load.
    - ``dev_s`` (int, ``min_dev``/``variance`` only) — per-staff deviation from
      average load.

    Hard constraints
    ~~~~~~~~~~~~~~~~
    1. Each candidate is assigned to exactly one slot.
    2. At most one candidate per slot.
    3. Candidate and staff availability (missing keys → unavailable).
    4. Frozen slots: previously-scheduled candidates/staff are hard-fixed;
       empty frozen slots are blocked for new assignments.
    5. Min/max staff counts enforced only when a candidate occupies the slot.
    6. Required staff: at least one required member must attend each
       candidate's slot.
    7. Forbidden pairs: prevent conflicting candidate–staff co-assignment.
    8. Parallel exclusivity: each staff member attends at most one slot per
       parallel group.

    Objective
    ~~~~~~~~~
    ``penalty_scale × Σ(change_penalties) + fairness_weight × fairness_term
    + Σ(suffix_slot_penalties)``

    Change penalties penalise candidate-slot moves
    (weight ``candidate_change_penalty_weight``) and staff-assignment
    changes (weight ``staff_change_penalty_weight``) relative to the
    previous schedule.  Frozen candidates/slots are excluded.

    The fairness term depends on the ``fairness`` parameter (see below).
    Suffix-slot penalties are a unit-weight tiebreaker that prefers base
    slots over parallel duplicates.

    Parameters
    ----------
    candidates : list
        Ordered collection of candidate identifiers to schedule.
    time_slots : list
        Ordered collection of timeslot identifiers available for scheduling.
    avail : dict
        Nested mapping ``{candidate_id: {timeslot_id: 0|1}}`` indicating
        candidate availability.  Missing keys default to unavailable.
    staff : list
        Ordered collection of staff (panel-member) identifiers.
    staff_avail : dict
        Nested mapping ``{staff_id: {timeslot_id: 0|1}}`` indicating staff
        availability.  Missing keys default to unavailable.
    required_staff : dict
        Mapping ``{candidate_id: staff_id | [staff_id, ...]}`` specifying
        staff members that *must* be present when a candidate is scheduled.
    forbidden_pairs : list of tuple
        List of ``(candidate_id, staff_id)`` pairs that must not overlap in
        any timeslot.
    prev_schedule : dict or None
        Optional mapping ``{candidate_id: timeslot_id}`` from a previous
        schedule.  Used to penalise candidate moves.
    prev_staff_assignment : dict or None
        Optional mapping ``{timeslot_id: [staff_id, ...]}`` from a previous
        schedule.  Used to penalise staff-level changes.
    min_staff_per_slot : int
        Minimum number of staff required per occupied timeslot (default 2).
    max_staff_per_slot : int
        Maximum number of staff allowed per occupied timeslot (default 2).
    fairness : str
        Fairness mode for the objective.  ``"min_max"`` minimises the
        maximum load across staff; ``"min_dev"`` / ``"variance"`` minimises
        sum-of-absolute-deviation from average load; ``"none"`` disables
        the fairness term.
    staff_change_penalty_weight : int
        Weight applied to each staff-assignment change relative to the
        previous schedule.
    penalty_scale : int
        Multiplier for the overall change-penalty term.  Higher values make
        stability dominate over fairness.
    fairness_weight : int
        Multiplier for the fairness term.  Higher values make fairness
        compete more aggressively with change penalties (default 1).
    candidate_change_penalty_weight : int
        Weight applied to each candidate-slot change relative to the
        previous schedule (default 5).
    parallel_slot_groups : dict or None
        Optional mapping ``{base_slot_id: [slot_id, ...]}`` defining groups
        of timeslots that occur in parallel.  Staff members are restricted
        to at most one slot per group, and non-base (suffix) slots receive
        a small penalty so the solver prefers the base slot.
    frozen_slots : set or None
        Set of timeslot IDs that are frozen (already happened).  Candidates
        previously scheduled in a frozen slot are hard-fixed to that slot
        and excluded from change penalties.  Empty frozen slots are also
        blocked — no new candidates or staff can be assigned there.  Staff
        loads from frozen slots still count for the fairness objective.

    allow_idle_staff : bool
        ``False`` (default): staff can only be assigned to occupied slots.  ``True``
        reproduces the original model, where staff could be parked on empty slots
        (those assignments were counted by the workload terms, then discarded).

    Returns
    -------
    model : cp_model.CpModel
        The fully constructed CP-SAT model ready to be solved.
    x : dict
        Decision variables ``{(candidate_id, timeslot_id): BoolVar}``
        indicating candidate-to-slot assignments.
    y : dict
        Decision variables ``{(staff_id, timeslot_id): BoolVar}``
        indicating staff-to-slot assignments.
    """
    from ortools.sat.python import cp_model  # lazy: the MIP backend does not need OR-Tools

    model = cp_model.CpModel()

    x = {}
    for c in candidates:
        for t in time_slots:
            x[c, t] = model.NewBoolVar(f"x[{c},{t}")

    y = {}
    for s in staff:
        for t in time_slots:
            y[s, t] = model.NewBoolVar(f"y[{s},{t}")

    staff_counts = {}
    for s in staff:
        count_s = model.NewIntVar(0, len(time_slots), f"count_{s}")
        model.Add(count_s == sum(y[(s, t)] for t in time_slots))
        staff_counts[s] = count_s

    # ---------- Hard constraints ----------

    for c in candidates:
        model.Add(sum(x[c, t] for t in time_slots) == 1)

    for t in time_slots:
        model.Add(sum(x[c, t] for c in candidates) <= 1)

    for c in candidates:
        for t in time_slots:
            if avail.get(c, {}).get(t, 0) != 1:
                model.Add(x[c, t] == 0)

    _frozen = frozenset(frozen_slots or [])
    _frozen_candidates = set()
    _time_slots_set = set(time_slots)
    if _frozen and prev_schedule:
        for c in candidates:
            prev_t = prev_schedule.get(c)
            if prev_t is not None and prev_t in _frozen and prev_t in _time_slots_set:
                model.Add(x[c, prev_t] == 1)
                _frozen_candidates.add(c)
    if _frozen and prev_staff_assignment:
        for t_frz, staff_ids in prev_staff_assignment.items():
            if t_frz not in _frozen or t_frz not in _time_slots_set:
                continue
            for s in (staff_ids or []):
                if s in staff:
                    model.Add(y[s, t_frz] == 1)

    _prev_staff_by_slot = {}
    if prev_staff_assignment:
        for t_frz, staff_ids in prev_staff_assignment.items():
            _prev_staff_by_slot[t_frz] = set(staff_ids or [])
    if _frozen:
        for t_frz in _frozen:
            if t_frz not in _time_slots_set:
                continue
            for c in candidates:
                if c not in _frozen_candidates:
                    model.Add(x[c, t_frz] == 0)
            prev_staff_here = _prev_staff_by_slot.get(t_frz, set())
            for s in staff:
                if s not in prev_staff_here:
                    model.Add(y[s, t_frz] == 0)

    for s in staff:
        for t in time_slots:
            if staff_avail.get(s, {}).get(t, 0) != 1:
                model.Add(y[s, t] == 0)

    for t in time_slots:
        has_candidate = model.NewBoolVar(f"has_candidate_{t}")
        model.Add(sum(x[c, t] for c in candidates) >= 1).OnlyEnforceIf(has_candidate)
        model.Add(sum(x[c, t] for c in candidates) == 0).OnlyEnforceIf(has_candidate.Not())

        model.Add(sum(y[s, t] for s in staff) >= min_staff_per_slot).OnlyEnforceIf(has_candidate)
        model.Add(sum(y[s, t] for s in staff) <= max_staff_per_slot).OnlyEnforceIf(has_candidate)
        # Nobody is assigned to a slot without an interview.  (Without this the solver could
        # park staff on empty slots to look "fairer": those assignments count in the workload
        # terms but are discarded from the published schedule.)
        if not allow_idle_staff:
            for s in staff:
                model.Add(y[s, t] == 0).OnlyEnforceIf(has_candidate.Not())

    for c in candidates:
        req = required_staff.get(c, [])
        if isinstance(req, str):
            req = [req]
        req_valid = [s for s in req if s in staff]
        if req_valid:
            for t in time_slots:
                model.Add(sum(y[s, t] for s in req_valid) >= x[c, t])

    for (c, s_forbid) in forbidden_pairs:
        for t in time_slots:
            model.Add(y[s_forbid, t] <= 1 - x[c, t])

    if parallel_slot_groups:
        for s in staff:
            for _base, group in parallel_slot_groups.items():
                valid = [t for t in group if t in time_slots]
                if len(valid) > 1:
                    model.Add(sum(y[s, t] for t in valid) <= 1)

    # ---------- Objective: fairness + change penalties ----------

    has_prev_info = bool(prev_schedule) or bool(prev_staff_assignment)

    penalties = []
    if has_prev_info:
        if prev_schedule:
            for c in candidates:
                if c in _frozen_candidates:
                    continue
                prev_t = prev_schedule.get(c)
                for t in time_slots:
                    if prev_t is None:
                        penalties.append(candidate_change_penalty_weight * x[c, t])
                    elif prev_t == t:
                        continue
                    else:
                        penalties.append(candidate_change_penalty_weight * x[c, t])

        if prev_staff_assignment:
            prev_pairs = set()
            for t, staff_list in prev_staff_assignment.items():
                for s in staff_list:
                    if s in staff and t in time_slots:
                        prev_pairs.add((s, t))

            for s in staff:
                for t in time_slots:
                    if t in _frozen:
                        continue
                    if (s, t) in prev_pairs:
                        penalties.append(staff_change_penalty_weight * (1 - y[s, t]))
                    else:
                        penalties.append(staff_change_penalty_weight * y[s, t])

    fairness_term = None
    if fairness == "min_max":
        max_load = model.NewIntVar(0, len(time_slots), "max_load")
        for s in staff:
            model.Add(max_load >= staff_counts[s])
        fairness_term = max_load
    elif fairness == "balanced":
        # Balance each role among itself: leads (staff named in required_staff) and the
        # other staff.  For each group minimise max load - min load.
        lead_set = _lead_set(required_staff, staff)
        ranges = []
        for gi, group in enumerate(g for g in (sorted(lead_set), [s for s in staff if s not in lead_set])
                                   if len(g) > 1):
            hi = model.NewIntVar(0, len(time_slots), f"hi_{gi}")
            lo = model.NewIntVar(0, len(time_slots), f"lo_{gi}")
            for s in group:
                model.Add(hi >= staff_counts[s])
                model.Add(lo <= staff_counts[s])
            ranges.append(hi - lo)
        # Secondary term: a lead beyond the one required per panel is an avoidable extra
        # load on the leads (their total is at least the number of interviews).  A range
        # unit counts BALANCED_RANGE_WEIGHT times an extra lead assignment.
        lead_total = sum(staff_counts[s] for s in lead_set)
        fairness_term = (BALANCED_RANGE_WEIGHT * sum(ranges) + lead_total) if lead_set and ranges else (
            BALANCED_RANGE_WEIGHT * sum(ranges) if ranges else None)
    elif fairness in ("min_dev", "variance"):
        deviations = []
        total_slots_per_staff_upper = len(time_slots)
        avg_int = (len(candidates) * min_staff_per_slot) // max(len(staff), 1)
        for s in staff:
            dev = model.NewIntVar(0, total_slots_per_staff_upper, f"dev_{s}")
            model.Add(dev >= staff_counts[s] - avg_int)
            model.Add(dev >= avg_int - staff_counts[s])
            deviations.append(dev)
        fairness_term = sum(deviations)

    parallel_penalties = []
    if parallel_slot_groups:
        suffix_slots = set()
        for _base, group in parallel_slot_groups.items():
            for member in group[1:]:
                suffix_slots.add(member)
        for c in candidates:
            for t in time_slots:
                if t in suffix_slots:
                    parallel_penalties.append(x[c, t])

    all_terms = []
    if penalties:
        all_terms.append(penalty_scale * sum(penalties))
    if fairness_term is not None:
        all_terms.append(fairness_weight * fairness_term)
    if parallel_penalties:
        all_terms.append(sum(parallel_penalties))

    if all_terms:
        main_objective = sum(all_terms)
        model.Minimize(main_objective)
        model._main_objective = main_objective      # used by the tie-break stage (backends.py)
    # else: no objective — feasibility only

    return model, x, y