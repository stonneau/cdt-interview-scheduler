"""High-level solver façade for interview scheduling.

Provides two public entry points for building and solving CP-SAT models:

- ``solve_initial_schedule(data_store, params)`` – compute a brand-new
  schedule from candidate/staff availability data.
- ``reschedule(data_store, change_event, params)`` – produce an updated
  schedule in response to availability or roster changes.

Internally the module delegates model construction to
``scheduler.model_builder``, configures the OR-Tools CP-SAT solver,
extracts assignments, and optionally persists results via ``DataStore``.
"""

from typing import Any, Dict, List, Tuple
import time
from scheduler import backends
import copy
from scheduler import strategies
from data_models.store import DataStore
from data_models.loaders import objects_to_solver_inputs_from_models
from data_models.loaders import unify_slots


def _diagnose_infeasibility(candidates, time_slots, avail, staff, staff_avail,
                            required_staff, min_staff_per_slot) -> None:
    """Print diagnostic info when the solver reports INFEASIBLE.

    Checks each candidate for feasible slots (available, with enough
    available staff including any required leads) and reports candidates
    that have zero feasible slots.  Also warns about candidates with very
    few options that may cause contention.

    :param candidates: Iterable of candidate identifiers.
    :type candidates: list[str]
    :param time_slots: Iterable of time-slot identifiers.
    :type time_slots: list[str]
    :param avail: Candidate availability mapping
        ``{candidate: {slot: 0|1}}``.
    :type avail: dict[str, dict[str, int]]
    :param staff: Iterable of staff identifiers.
    :type staff: list[str]
    :param staff_avail: Staff availability mapping
        ``{staff: {slot: 0|1}}``.
    :type staff_avail: dict[str, dict[str, int]]
    :param required_staff: Mapping of candidate to required staff
        member(s).  Values may be a single staff id or a list.
    :type required_staff: dict[str, str | list[str]]
    :param min_staff_per_slot: Minimum number of staff required at each
        slot for it to be considered feasible.
    :type min_staff_per_slot: int
    :returns: Nothing.  Diagnostic output is printed to stdout.
    :rtype: None
    """
    # Pre-compute per-slot staff availability count
    slot_staff_count = {}
    for t in time_slots:
        slot_staff_count[t] = sum(
            1 for s in staff if staff_avail.get(s, {}).get(t, 0) == 1
        )

    issues = []
    warnings = []
    for c in candidates:
        req = required_staff.get(c, [])
        if isinstance(req, str):
            req = [req]
        avail_slots = [t for t in time_slots if avail.get(c, {}).get(t, 0) == 1]
        feasible = []
        for t in avail_slots:
            if slot_staff_count[t] < min_staff_per_slot:
                continue
            # The model needs at least ONE required staff member on the panel (not all).
            req_in_pool = [s for s in req if s in staff]
            if req_in_pool and not any(
                staff_avail.get(s, {}).get(t, 0) == 1 for s in req_in_pool
            ):
                continue
            feasible.append(t)
        if not feasible:
            issues.append((c, len(avail_slots), 0))
        elif len(feasible) <= 3:
            warnings.append((c, len(avail_slots), len(feasible)))

    if issues or warnings:
        print("\n--- Infeasibility diagnostics ---")
        if issues:
            print("Candidates with NO feasible slot (guaranteed infeasible):")
            for c, n_avail, _ in issues:
                print(f"  {c}: available at {n_avail} slot(s), "
                      f"but none have >= {min_staff_per_slot} available staff"
                      + (" (+ required leads)" if required_staff.get(c) else ""))
        if warnings:
            print("Candidates with very few feasible slots (may cause contention):")
            for c, n_avail, n_feas in warnings:
                print(f"  {c}: {n_feas} feasible slot(s) out of {n_avail} available")
        print("---\n")


def _expand_parallel_slots(time_slots, avail, staff_avail, max_parallel):
    """Expand each base time slot into *max_parallel* parallel instances.

    The first instance keeps the original slot name.  Additional instances
    are suffixed with ``.2``, ``.3``, …  Candidate and staff availability
    is replicated from the base slot to every parallel instance so that
    entities available at time *T* are also available at *T.2*, *T.3*, etc.

    :param time_slots: Original list of base time-slot identifiers.
    :type time_slots: list[str]
    :param avail: Candidate availability mapping
        ``{candidate: {slot: 0|1}}``.
    :type avail: dict[str, dict[str, int]]
    :param staff_avail: Staff availability mapping
        ``{staff: {slot: 0|1}}``.
    :type staff_avail: dict[str, dict[str, int]]
    :param max_parallel: Maximum number of parallel instances per base
        slot (including the base itself).
    :type max_parallel: int
    :returns: A 4-tuple of:
        - **expanded_time_slots** (*list[str]*) – all slot ids after
          expansion.
        - **expanded_avail** (*dict[str, dict[str, int]]*) – candidate
          availability replicated across parallel instances.
        - **expanded_staff_avail** (*dict[str, dict[str, int]]*) – staff
          availability replicated across parallel instances.
        - **parallel_slot_groups** (*dict[str, list[str]]*) – mapping
          from each base slot to the full list of its parallel instances
          (including the base).
    :rtype: tuple[list[str], dict, dict, dict[str, list[str]]]
    """
    expanded_time_slots: List[str] = []
    parallel_slot_groups: Dict[str, List[str]] = {}

    for t in time_slots:
        group = [t]
        expanded_time_slots.append(t)
        for i in range(2, max_parallel + 1):
            pt = f"{t}.{i}"
            group.append(pt)
            expanded_time_slots.append(pt)
        parallel_slot_groups[t] = group

    expanded_avail: Dict[str, Dict[str, int]] = {}
    for c, slots_dict in avail.items():
        cand_dict: Dict[str, int] = {}
        for t in time_slots:
            val = slots_dict.get(t, 0)
            cand_dict[t] = val
            for i in range(2, max_parallel + 1):
                cand_dict[f"{t}.{i}"] = val
        expanded_avail[c] = cand_dict

    expanded_staff_avail: Dict[str, Dict[str, int]] = {}
    for s, slots_dict in staff_avail.items():
        staff_dict: Dict[str, int] = {}
        for t in time_slots:
            val = slots_dict.get(t, 0)
            staff_dict[t] = val
            for i in range(2, max_parallel + 1):
                staff_dict[f"{t}.{i}"] = val
        expanded_staff_avail[s] = staff_dict

    return expanded_time_slots, expanded_avail, expanded_staff_avail, parallel_slot_groups


def solve_initial_schedule(*args: Any, **kwargs: Any) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Compute an initial schedule using the OR-Tools CP-SAT model.

    Accepts arguments as positional (``data_store, params``) or as keyword
    arguments.  When *data_store* is a
    :class:`~data_models.store.DataStore` instance, canonical data is
    loaded and converted automatically.

    :param data_store: Scheduling data.  Either a plain ``dict`` with keys
        ``candidates``, ``time_slots``, ``avail``, ``staff``,
        ``staff_avail``, ``required_staff``, ``forbidden_pairs``, and
        optionally ``prev_schedule`` / ``prev_staff_assignment``; or a
        :class:`~data_models.store.DataStore` instance.
    :type data_store: dict[str, Any] | DataStore
    :param params: Solver parameters.  Optional keys include
        ``time_limit`` (float, seconds), ``num_workers`` (int),
        ``min_staff_per_slot``, ``max_staff_per_slot``, ``fairness``,
        ``staff_change_penalty_weight``, ``candidate_change_penalty_weight``,
        ``penalty_scale``, ``allow_parallel``, ``max_parallel``,
        ``frozen_slots``, ``persist``, ``random_seed``, ``deterministic``,
        and ``use_saved_schedule_id``.
    :type params: dict[str, Any]
    :returns: A 2-tuple of:
        - **schedule** (*dict[str, str | None]*) – mapping of candidate
          id to assigned time-slot (or ``None`` if unassigned).
        - **metadata** (*dict[str, Any]*) – solver statistics and
          auxiliary data including ``status``, ``solve_time_seconds``,
          ``staff_assignment``, ``objective_value``, and optionally
          ``saved_schedule_id``.
    :rtype: tuple[dict[str, str], dict[str, Any]]
    :raises ValueError: If *data_store* lacks ``candidates`` or
        ``time_slots``.
    """

    raw_data_store = kwargs.get("data_store", args[0] if len(args) >= 1 else {})
    params = kwargs.get("params", args[1] if len(args) >= 2 else {})

    # Support either a plain dict data_store or a DataStore instance. If a
    # DataStore is provided, we attempt to load canonical data and convert it
    # into the in-memory dict shape expected by the solver. We keep a reference
    # to the original object so we can persist results and append events.
    data_store_obj = raw_data_store if isinstance(raw_data_store, DataStore) else None
    if data_store_obj is not None:
        loaded = data_store_obj.load_initial_data() or {}
        candidates_objs = (loaded.get("candidates") or (None, None))[0]
        cand_slots = (loaded.get("candidates") or (None, None))[1] if loaded.get("candidates") else None
        staff_objs = (loaded.get("staff") or (None, None))[0]
        staff_slots = (loaded.get("staff") or (None, None))[1] if loaded.get("staff") else None
        # Try to convert model objects into solver input shapes
        try:
            if candidates_objs is not None and staff_objs is not None:
                candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = (
                    objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
                )
                time_slots = cand_slots or staff_slots or []
            else:
                # Fallback to empty
                candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = [], [], {}, {}, {}, set()
                time_slots = cand_slots or staff_slots or []
        except Exception:
            candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = [], [], {}, {}, {}, set()
            time_slots = cand_slots or staff_slots or []
        data_store = {
            "candidates": candidate_ids,
            "time_slots": time_slots,
            "avail": avail,
            "staff": staff_ids,
            "staff_avail": staff_avail,
            "required_staff": required_staff,
            "forbidden_pairs": forbidden_pairs,
            "prev_schedule": (loaded.get("prev_schedule") or (None))[0] if loaded.get("prev_schedule") else None,
            "prev_staff_assignment": (loaded.get("prev_schedule") or (None))[1] if loaded.get("prev_schedule") else None,
        }
    else:
        data_store = raw_data_store

    # Allow callers to provide an in-memory data dict while still passing a
    # DataStore object for persistence. This is useful for synthetic datasets
    # where we want to persist results into a controlled run_id/dirs but don't
    # have canonical CSVs to load. Use params key '_data_store_dict' to pass
    # the override dict.
    if data_store_obj is not None and isinstance(params, dict):
        override = params.get("_data_store_dict")
        if isinstance(override, dict) and override:
            data_store = override

    # Allow overriding prev_schedule by loading a saved schedule id from params.
    # This is useful for replaying or bootstrapping experiments from persisted schedules.
    use_saved_id = params.get("use_saved_schedule_id")
    if use_saved_id:
        try:
            ds_for_load = data_store_obj if data_store_obj is not None else DataStore(config={"base_dir": "data"})
            payload = ds_for_load.get_schedule_metadata(use_saved_id)
            loaded_sched = payload.get("schedule", {}) or {}
            loaded_meta = payload.get("metadata", {}) or {}
            loaded_staff_assignment = loaded_meta.get("staff_assignment") or {}
            # Inject into data_store so model builder and objectives see it as previous baseline
            data_store["prev_schedule"] = loaded_sched
            data_store["prev_staff_assignment"] = loaded_staff_assignment
        except Exception:
            # If unable to load saved schedule, continue without overriding
            pass

    # defaults and validation
    candidates = data_store.get("candidates")
    time_slots = data_store.get("time_slots")
    if not candidates or not time_slots:
        raise ValueError("data store must contain 'candidates' and 'time_slots'")
    
    avail = data_store.get("avail", {c: {t: 1 for t in time_slots} for c in candidates})
    staff = data_store.get("staff", [])
    staff_avail = data_store.get("staff_avail", {s: {t: 1 for t in time_slots} for s in staff})
    required_staff = data_store.get("required_staff", {})
    forbidden_pairs = data_store.get("forbidden_pairs", [])
    # Filter to pairs where both the candidate and staff actually exist in
    # the current model. The data_store may contain pairs that reference
    # candidates/staff not yet present (they persist for future reschedules
    # when those entities are added via staged changes).
    candidate_set = set(candidates)
    staff_set = set(staff)
    active_forbidden_pairs = {
        (c, s) for c, s in forbidden_pairs
        if c in candidate_set and s in staff_set
    }
    prev_schedule = data_store.get("prev_schedule")
    prev_staff_assignment = data_store.get("prev_staff_assignment")

    # model builder parameters
    min_staff_per_slot = params.get("min_staff_per_slot", 2)
    max_staff_per_slot = params.get("max_staff_per_slot", 2)
    fairness = params.get("fairness", "min_dev")
    staff_change_penalty_weight = params.get("staff_change_penalty_weight", 1)
    penalty_scale = params.get("penalty_scale", 1000)
    candidate_change_penalty_weight = params.get("candidate_change_penalty_weight", 5)
    frozen_slots = params.get("frozen_slots") or data_store.get("frozen_slots")

    # Parallel slot expansion: when enabled, each base time slot is replicated
    # into *max_parallel* instances so that multiple candidates can interview
    # at the same physical time (with different staff panels).
    allow_parallel = params.get("allow_parallel", False)
    max_parallel = int(params.get("max_parallel", 2))
    parallel_slot_groups = None

    if allow_parallel and max_parallel > 1:
        time_slots, avail, staff_avail, parallel_slot_groups = _expand_parallel_slots(
            time_slots, avail, staff_avail, max_parallel,
        )

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
            candidate_change_penalty_weight=candidate_change_penalty_weight,
            parallel_slot_groups=parallel_slot_groups,
            frozen_slots=frozen_slots,
        ),
        params,
    )
    solve_time = result.solve_time
    status_name = result.status_name

    # When the solver reports INFEASIBLE, run a quick diagnostic to identify
    # candidates that cannot possibly be assigned to any slot.
    if result.infeasible:
        _diagnose_infeasibility(
            candidates, time_slots, avail, staff, staff_avail,
            required_staff, min_staff_per_slot,
        )

    schedule: Dict[str, Any] = {}
    staff_assignment: Dict[str, Any] = {}
    if result.has_solution:
        for c in candidates:
            assigned = None
            for t in time_slots:
                if result.value_x(c, t) == 1:
                    assigned = t
                    break
            # Candidate left unassigned (shouldn't happen given hard constraint)
            # is kept as None to indicate a missing assignment.
            schedule[c] = assigned

        # Extract staff assignments, but ONLY for slots with scheduled candidates
        occupied_slots = set(s for s in schedule.values() if s is not None)

        for t in time_slots:
            staff_list = [s for s in staff if result.value_y(s, t) == 1]
            if t in occupied_slots:
                staff_assignment[t] = staff_list

    metadata: Dict[str, Any] = {
        "status": status_name,
        "cp_status": int(result.status),
        "solve_time_seconds": solve_time,
        "num_conflicts": result.num_conflicts,
        "num_branches": result.num_branches,
        "objective_value": result.objective_value if result.has_solution else None,
        "staff_assignment": staff_assignment,
    }

    # Persist schedule and append an event if persistence is enabled (default
    # True). Include source paths from params in the saved metadata when
    # provided.
    try:
        persist_enabled = bool(params.get("persist", True))
        if persist_enabled:
            ds_to_use = data_store_obj if data_store_obj is not None else DataStore(config={"base_dir": "data"})
            save_meta = dict(metadata or {})
            # add source info if available in params
            if params.get("source_applicants"):
                save_meta.setdefault("source_applicants", params.get("source_applicants"))
            if params.get("source_staff"):
                save_meta.setdefault("source_staff", params.get("source_staff"))
            # Persist lead_ids so session-resume can reconstruct required_staff
            # without re-uploading CSVs.
            if "lead_ids" in params:
                save_meta.setdefault("lead_ids", list(params["lead_ids"]))
            # Persist forbidden_pairs so session-resume can apply them to
            # candidates added later via staged changes.
            fp_to_persist = data_store.get("forbidden_pairs", [])
            if fp_to_persist:
                save_meta.setdefault(
                    "forbidden_pairs", [list(p) for p in fp_to_persist]
                )
            # Persist the full time_slots universe so session-resume can restore
            # it accurately. Without this, _resume_run() can only infer
            # occupied slots (one per candidate), which makes the model
            # infeasible as soon as a new candidate is added.
            save_meta.setdefault("time_slots", list(time_slots))
            # Persist availability so session-resume can restore original
            # CSV-based availability instead of defaulting to all-available.
            save_meta.setdefault("avail", avail)
            save_meta.setdefault("staff_avail", staff_avail)
            # mark initial schedules without a change_idx; reschedules will set one
            sid = ds_to_use.save_schedule(schedule, metadata=save_meta)
            event = {"type": "initial_schedule_saved", "schedule_id": sid, "metadata": save_meta}
            ds_to_use.append_event(event)
            metadata["saved_schedule_id"] = sid
    except Exception:
        # Persistence must not break solver behaviour; ignore failures.
        pass

    return schedule, metadata



def reschedule(*args: Any, **kwargs: Any) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Reschedule given a change event.

    Accepts arguments as positional (``data_store, change_event, params``)
    or as keyword arguments.  Applies the *change_event* mutations to the
    data, then delegates to a pluggable strategy (defaulting to
    ``change_penalty``) to produce an updated schedule.

    :param data_store: Scheduling data.  Either a plain ``dict`` (same
        shape as for :func:`solve_initial_schedule`) or a
        :class:`~data_models.store.DataStore` instance.
    :type data_store: dict[str, Any] | DataStore
    :param change_event: Description of what changed.  Supported keys
        (all optional):
        - ``staff_unavailable``: list of ``(staff_id, slot_id)``
        - ``candidate_unavailable``: list of ``(candidate_id, slot_id)``
          or list of ``candidate_id`` (marks all slots unavailable)
        - ``remove_candidate``: list of candidate ids to remove
        - ``add_candidate``: list of candidate ids to add
        - ``staff_removed``: list of staff ids to remove
        - ``staff_added``: list of staff ids to add
    :type change_event: dict[str, Any]
    :param params: Solver / strategy parameters.  Notable keys include
        ``strategy`` (``"change_penalty"`` or ``"full"``), plus all keys
        accepted by :func:`solve_initial_schedule`.
    :type params: dict[str, Any]
    :returns: A 2-tuple of:
        - **schedule** (*dict[str, str | None]*) – updated candidate
          assignments.
        - **metadata** (*dict[str, Any]*) – solver statistics, strategy
          name, and optionally ``saved_schedule_id``.
    :rtype: tuple[dict[str, str], dict[str, Any]]
    :raises ValueError: If *data_store* lacks ``candidates`` or
        ``time_slots``.
    """
    raw_data_store = kwargs.get("data_store", args[0] if len(args) >= 1 else {})
    change_event = kwargs.get("change_event", args[1] if len(args) >= 2 else {}) or {}
    params = kwargs.get("params", args[2] if len(args) >= 3 else {}) or {}

    # Defensive copy so caller's data_store isn't mutated.
    # Support DataStore instance by unwrapping it into a plain dict first.
    data_store_obj = raw_data_store if isinstance(raw_data_store, DataStore) else None
    if data_store_obj is not None:
        loaded = data_store_obj.load_initial_data() or {}
        candidates_objs = (loaded.get("candidates") or (None, None))[0]
        cand_slots = (loaded.get("candidates") or (None, None))[1] if loaded.get("candidates") else None
        staff_objs = (loaded.get("staff") or (None, None))[0]
        staff_slots = (loaded.get("staff") or (None, None))[1] if loaded.get("staff") else None
        try:
            if candidates_objs is not None and staff_objs is not None:
                candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = (
                    objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
                )
                time_slots = cand_slots or staff_slots or []
            else:
                candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = [], [], {}, {}, {}, set()
                time_slots = cand_slots or staff_slots or []
        except Exception:
            candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = [], [], {}, {}, {}, set()
            time_slots = cand_slots or staff_slots or []
        ds = {
            "candidates": candidate_ids,
            "time_slots": time_slots,
            "avail": avail,
            "staff": staff_ids,
            "staff_avail": staff_avail,
            "required_staff": required_staff,
            "forbidden_pairs": forbidden_pairs,
            "prev_schedule": (loaded.get("prev_schedule") or (None))[0] if loaded.get("prev_schedule") else None,
            "prev_staff_assignment": (loaded.get("prev_schedule") or (None))[1] if loaded.get("prev_schedule") else None,
        }
    else:
        ds = copy.deepcopy(raw_data_store)

    # If a DataStore object was provided but the caller wants to supply an
    # in-memory dataset (synthetic), allow overriding the ds dict via
    # params['_data_store_dict']. This keeps the DataStore instance for
    # persistence while using the provided candidate/staff data.
    if data_store_obj is not None and isinstance(params, dict):
        override = params.get("_data_store_dict")
        if isinstance(override, dict) and override:
            # Use a deep copy to avoid accidental shared-state mutations
            # between successive reschedule calls. Shallow copies can leave
            # nested dict references (like `avail`) shared and cause
            # inconsistent state leading to KeyError when candidates are
            # removed.
            try:
                ds = copy.deepcopy(override)
            except Exception:
                ds = dict(override)

    # If a saved schedule id is provided in params, attempt to load it and
    # use it as the prev_schedule/prev_staff_assignment baseline for rescheduling.
    use_saved_id = params.get("use_saved_schedule_id")
    if use_saved_id:
        try:
            ds_for_load = data_store_obj if data_store_obj is not None else DataStore(config={"base_dir": "data"})
            payload = ds_for_load.get_schedule_metadata(use_saved_id)
            loaded_sched = payload.get("schedule", {}) or {}
            loaded_meta = payload.get("metadata", {}) or {}
            loaded_staff_assignment = loaded_meta.get("staff_assignment") or {}
            ds["prev_schedule"] = loaded_sched
            ds["prev_staff_assignment"] = loaded_staff_assignment
        except Exception:
            pass

    candidates = list(ds.get("candidates", []))
    time_slots = list(ds.get("time_slots", []))
    if not candidates or not time_slots:
        raise ValueError("data store must contain 'candidates' and 'time_slots'")

    avail = ds.get("avail", {c: {t: 1 for t in time_slots} for c in candidates})
    # Ensure avail contains entries for all candidates (may be missing after
    # upstream mutations). This prevents KeyError in model_builder when a
    # candidate appears in the candidates list but has no avail mapping.
    for c in list(candidates):
        if c not in avail:
            avail[c] = {t: 1 for t in time_slots}
    staff = list(ds.get("staff", []))
    staff_avail = ds.get("staff_avail", {s: {t: 1 for t in time_slots} for s in staff})
    # Ensure staff_avail contains entries for all staff members.  The same
    # defensive pattern as for avail above — guards against state mutations
    # that leave staff and staff_avail out of sync.
    for s in list(staff):
        if s not in staff_avail:
            staff_avail[s] = {t: 1 for t in time_slots}
    required_staff = ds.get("required_staff", {})
    forbidden_pairs = ds.get("forbidden_pairs", [])
    prev_schedule = ds.get("prev_schedule")
    prev_staff_assignment = ds.get("prev_staff_assignment")

    # Apply change_event (best-effort, non-exhaustive)
    if change_event:
        # staff_unavailable: list of (s, t)
        for s_t in change_event.get("staff_unavailable", []):
            try:
                s, t = s_t
                if s in staff and t in time_slots:
                    if s not in staff_avail:
                        staff_avail[s] = {ti: 1 for ti in time_slots}
                    staff_avail[s][t] = 0
            except Exception:
                continue

        # candidate_unavailable: list of (c, t) or list of c (mark all slots unavailable)
        for item in change_event.get("candidate_unavailable", []):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                c, t = item
                if c in candidates and t in time_slots:
                    if c not in avail:
                        avail[c] = {ti: 1 for ti in time_slots}
                    avail[c][t] = 0
            else:
                c = item
                if c in candidates:
                    if c not in avail:
                        avail[c] = {ti: 1 for ti in time_slots}
                    for t in time_slots:
                        avail[c][t] = 0

        # remove_candidate: remove from candidate pool
        for c in change_event.get("remove_candidate", []):
            if c in candidates:
                candidates.remove(c)
                avail.pop(c, None)
                required_staff.pop(c, None)

        # add_candidate: add with availability from ds if pre-set by UI,
        # otherwise default to fully available.
        for c in change_event.get("add_candidate", []):
            if c not in candidates:
                candidates.append(c)
                # Use pre-set availability from ds if the UI already inserted
                # it (e.g. from CSV upload or slot selection); fall back to
                # all-available.
                if c not in avail:
                    avail[c] = {t: 1 for t in time_slots}
            # Always ensure required_staff is set for added candidates.  This
            # runs even when the UI has already pre-inserted the candidate into
            # ds["candidates"] (without touching required_staff), which would
            # cause the `c not in candidates` gate above to be skipped.
            if c not in required_staff:
                _lead_ids = ds.get("lead_ids")
                if _lead_ids:
                    # Explicit, non-empty lead list — use it directly.
                    required_staff[c] = list(_lead_ids)
                elif _lead_ids is None:
                    # Key is absent: infer leads from the union of existing
                    # required_staff values (backwards compat with older runs).
                    required_staff[c] = sorted(set(
                        lead
                        for leads in required_staff.values()
                        for lead in (leads or [])
                    ))
                # _lead_ids == [] means user explicitly disabled lead
                # requirements — leave required_staff[c] unset.

        # staff_removed
        for s in change_event.get("staff_removed", []):
            if s in staff:
                staff.remove(s)
                staff_avail.pop(s, None)
                required_staff = {k: [x for x in (required_staff.get(k) or []) if x != s] for k in required_staff}

        # staff_added: use pre-set availability from ds if available,
        # otherwise default to fully available.
        for s in change_event.get("staff_added", []):
            if s not in staff:
                staff.append(s)
                if s not in staff_avail:
                    staff_avail[s] = {t: 1 for t in time_slots}

        # update ds copies
        ds["candidates"] = candidates
        ds["avail"] = avail
        ds["staff"] = staff
        ds["staff_avail"] = staff_avail
        ds["required_staff"] = required_staff

    # Parallel slot expansion (after change events are applied so new
    # entities get availability for expanded slots as well).
    allow_parallel = params.get("allow_parallel", False)
    max_parallel_val = int(params.get("max_parallel", 2))
    if allow_parallel and max_parallel_val > 1:
        exp_ts, exp_av, exp_sa, p_groups = _expand_parallel_slots(
            list(ds.get("time_slots", [])),
            ds.get("avail", {}),
            ds.get("staff_avail", {}),
            max_parallel_val,
        )
        ds["time_slots"] = exp_ts
        ds["avail"] = exp_av
        ds["staff_avail"] = exp_sa
        ds["parallel_slot_groups"] = p_groups

    strategy = params.get("strategy", "change_penalty")
    strategy_fn = strategies.get_strategy(strategy)
    
    # Call selected strategy implementation. Each strategy receives the already-applied
    # change_event reflected in `ds` and the params dict. Strategy should return
    # (schedule, metadata)
    try:
        schedule, metadata = strategy_fn(ds, change_event, params)
    except Exception as exc:
        # Fall back to change_penalty if strategy fails
        try:
            schedule, metadata = strategies.change_penalty(ds, change_event, params)
            metadata = metadata or {}
            metadata["fallback_from"] = strategy
            metadata["fallback_error"] = str(exc)
        except Exception:
            raise

    # Ensure strategy name included
    if isinstance(metadata, dict):
        metadata.setdefault("strategy", strategy)

    # Persist schedule and append an event if persistence is enabled in params.
    try:
        persist_enabled = bool(params.get("persist", True))
        if persist_enabled:
            ds_to_use = data_store_obj if data_store_obj is not None else DataStore(config={"base_dir": "data"})
            save_meta = dict(metadata or {})
            if params.get("source_applicants"):
                save_meta.setdefault("source_applicants", params.get("source_applicants"))
            if params.get("source_staff"):
                save_meta.setdefault("source_staff", params.get("source_staff"))
            # Persist lead_ids so session-resume can reconstruct required_staff.
            if "lead_ids" in params:
                save_meta.setdefault("lead_ids", list(params["lead_ids"]))
            # Persist forbidden_pairs so session-resume can apply them to
            # candidates added later via staged changes.
            fp_to_persist = ds.get("forbidden_pairs", [])
            if fp_to_persist:
                save_meta.setdefault(
                    "forbidden_pairs", [list(p) for p in fp_to_persist]
                )
            # Persist the current time_slots universe so _resume_run() can
            # restore it and avoid an infeasible skeleton with only occupied
            # slots (which makes adding new candidates impossible).
            save_meta.setdefault("time_slots", list(time_slots))
            # Persist availability so session-resume can restore original
            # CSV-based availability instead of defaulting to all-available.
            save_meta.setdefault("avail", ds.get("avail", {}))
            save_meta.setdefault("staff_avail", ds.get("staff_avail", {}))

            # Compute a change index for reschedules so plots can reliably label events.
            try:
                existing_events = list(ds_to_use.iter_change_events())
                # Count previous reschedule-type events (inner payload stored under 'event')
                prev_reschedules = 0
                for ev in existing_events:
                    inner = ev.get("event") if isinstance(ev, dict) else None
                    if inner and (inner.get("type") == "reschedule" or inner.get("change_event") is not None):
                        prev_reschedules += 1
                change_idx = prev_reschedules
            except Exception:
                change_idx = 0

            # Attach a short human label describing the change_event for plotting
            try:
                if isinstance(change_event, dict) and change_event:
                    # Special case: if noise_applied is present, extract the actual noise type
                    if "noise_applied" in change_event:
                        noise_meta = change_event.get("noise_applied", {})
                        if isinstance(noise_meta, dict):
                            noise_type = noise_meta.get("type", "noise_applied")
                            save_meta.setdefault("change_event_label", noise_type)
                        else:
                            save_meta.setdefault("change_event_label", ",".join(list(change_event.keys())))
                    else:
                        save_meta.setdefault("change_event_label", ",".join(list(change_event.keys())))
                else:
                    save_meta.setdefault("change_event_label", "reschedule")
            except Exception:
                save_meta.setdefault("change_event_label", "reschedule")

            # Persist the change index in metadata
            save_meta["change_idx"] = change_idx

            # Store the previous schedule ID so metrics can correctly compute changes
            prev_sched_id = params.get("use_saved_schedule_id")
            if prev_sched_id:
                save_meta["prev_schedule_id"] = prev_sched_id

            sid = ds_to_use.save_schedule(schedule, metadata=save_meta)
            event = {
                "type": "reschedule",
                "schedule_id": sid,
                "change_event": change_event,
                "metadata": save_meta,
            }
            try:
                eid = ds_to_use.append_event(event)
                # Update the saved schedule metadata with the event id for round-trip
                try:
                    ds_to_use.update_schedule_metadata(sid, {"change_event_id": eid, "event_id": eid})
                    metadata["change_event_id"] = eid
                except Exception:
                    pass
            except Exception:
                pass

            metadata["saved_schedule_id"] = sid
    except Exception:
        pass

    return schedule, metadata