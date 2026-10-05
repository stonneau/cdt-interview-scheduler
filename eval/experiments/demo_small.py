"""
Demo harness: small reproducible experiment on demo_small dataset.
Library function for running controlled demo runs with configurable parameters.
"""

from typing import Any, Dict, List

from data_models.store import DataStore
from scheduler import solver as solver_module
from eval.data_generators import generate_synthetic_dataset
from eval.noise_generators import apply_noise
from eval.change_analyzer import (
    compute_staff_unavailable_details,
    compute_candidate_unavailable_details,
    compute_removal_details,
)

import uuid


def _print_schedule(schedule, staff_assignment):
    """Print schedule assignments to stdout.

    :param schedule: Mapping ``{candidate_id: timeslot_id}``.
    :param staff_assignment: Mapping ``{timeslot_id: [staff_id, ...]}``.
    """
    if not schedule:
        print("No schedule available.")
        return
    print("\nSchedule:")
    for c, t in sorted(schedule.items()):
        staff = staff_assignment.get(t, [])
        print(f"  {c} -> {t} | Staff: {', '.join(staff)}")
    print()


def run_demo_small(
        random_seed: int = None, 
        base_dir: str = "data",
        *,
        persist: bool = False,
        strategies: List[str] = None,
        run_id: str = None,
        noise_type: str = "random_staff_unavailable",
        noise_intensity: int = 1,
        allow_parallel: bool = False,
        max_parallel: int = 2,
    ) -> DataStore:
    """Load demo_small CSVs, compute initial schedule, apply scripted changes,
    reschedule per strategy. Returns DataStore with persisted schedules/events.

    If the demo_small CSV files are not present (``data/demo_small/``), the
    function automatically falls back to a small synthetic dataset so that
    tests and fresh checkouts work without additional data files.
    
    Parameters
    ----------
    random_seed : int, optional
        If provided, solver runs deterministically.
    base_dir : str
        Output base directory for DataStore.
    persist : bool
        If True, persist schedules/events to disk.
    strategies : List[str], optional
        List of strategy names; defaults to all three.
    run_id : str, optional
        Run identifier for grouping artifacts.
    noise_type, noise_intensity : str, int
        Currently unused; reserved for future noise injection.
    
    Returns
    -------
    DataStore
        Populated DataStore with all persisted schedules/events.
    """
    base = base_dir
    run_id = run_id or f"demo-{uuid.uuid4().hex[:8]}"
    ds = DataStore(config={"base_dir": base, "data_dir": "data/demo_small", "run_id": run_id})

    params = {}
    if random_seed is not None:
        params["random_seed"] = int(random_seed)
        params["deterministic"] = True

    params["persist"] = bool(persist)
    params["allow_parallel"] = bool(allow_parallel)
    params["max_parallel"] = int(max_parallel)

    loaded = ds.load_initial_data() or {}
    candidates_objs = (loaded.get("candidates") or (None, None))[0]
    staff_objs = (loaded.get("staff") or (None, None))[0]

    _synthetic_fallback: Dict[str, Any] = {}
    if candidates_objs is None or staff_objs is None:
        _synthetic_fallback = generate_synthetic_dataset(
            num_candidates=5,
            num_staff=4,
            num_days=1,
            slots_per_day=6,
            complexity="simple",
            seed=random_seed,
        )
        params["_data_store_dict"] = dict(_synthetic_fallback)

    schedule, meta = solver_module.solve_initial_schedule(data_store=ds, params=params)
    staff_assign = meta.get("staff_assignment", {})
    _print_schedule(schedule, staff_assign)
    print("Initial schedule saved id:", meta.get("saved_schedule_id"))
    initial_schedule_id = meta.get("saved_schedule_id")
    last_saved_schedule_id = initial_schedule_id

    candidate_ids: List[str] = []
    staff_ids: List[str] = []
    cand_slots: List[str] = []

    if _synthetic_fallback:
        candidate_ids = list(_synthetic_fallback.get("candidates", []))
        staff_ids = list(_synthetic_fallback.get("staff", []))
        cand_slots = list(_synthetic_fallback.get("time_slots", []))
    else:
        cand_slots_raw = (loaded.get("candidates") or (None, None))[1] if loaded.get("candidates") else None
        cand_slots = list(cand_slots_raw) if cand_slots_raw else []
        try:
            if candidates_objs is not None and staff_objs is not None:
                from data_models.loaders import objects_to_solver_inputs_from_models
                candidate_ids, staff_ids, _, _, _, _ = objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
        except Exception:
            pass

    if not candidate_ids:
        candidate_ids = list(schedule.keys())
    if not staff_ids:
        for lst in staff_assign.values():
            for s in lst:
                if s not in staff_ids:
                    staff_ids.append(s)

    strategies = strategies or ["reschedule_from_scratch", "change_penalty", "local_repair"]

    for strat in strategies:
        p = dict(params)
        p["strategy"] = strat
        p["persist"] = False
        sched_s, meta_s = solver_module.reschedule(data_store=ds, change_event={}, params=p)
        print(f"Strategy {strat} produced (probe) schedule; not persisted")

    change_events = []
    first_slot = cand_slots[0] if cand_slots else None
    if staff_ids and first_slot:
        su = []
        su.append((staff_ids[0], first_slot))
        if len(staff_ids) > 1 and len(cand_slots) > 1:
            su.append((staff_ids[1], cand_slots[1]))
        change_events.append({"staff_unavailable": su})

    if candidate_ids:
        change_events.append({"remove_candidate": [candidate_ids[0]]})

    change_events.append({"add_candidate": ["cand_new"]})

    for i, ce in enumerate(change_events):
        print(f"Applying change_event {i+1}:", ce)
        last_saved_schedule_id = initial_schedule_id
        for strat in strategies:
            p = dict(params)
            p["strategy"] = strat
            if last_saved_schedule_id:
                p["use_saved_schedule_id"] = last_saved_schedule_id
            sched_s, meta_s = solver_module.reschedule(data_store=ds, change_event=ce, params=p)
            print(f"After change {i+1}, strategy {strat} saved schedule id:", meta_s.get("saved_schedule_id"))
            _print_schedule(sched_s, meta_s.get("staff_assignment", {}))

    return ds


def run_generated_demo(
        random_seed: int = None,
        base_dir: str = "data/synthetic_runs",
        *,
        persist: bool = False,
        strategies: List[str] = None,
        run_id: str = None,
        num_candidates: int = 10,
        num_staff: int = 8,
        num_days: int = 2,
        slots_per_day: int = 6,
        complexity: str = "simple",
        require_leads: bool = True,
        noise_type: str = None,
        noise_num_people: int = 1,
        noise_intensity: int = 1,
        allow_parallel: bool = False,
        max_parallel: int = 2,
) -> DataStore:
    """Run demo with synthetically generated dataset (instead of CSV-based demo_small).
    
    Parameters
    ----------
    random_seed : int, optional
        Seed for reproducibility (both dataset generation and solver).
    base_dir : str
        Output base directory for DataStore.
    persist : bool
        If True, persist schedules/events to disk.
    strategies : List[str], optional
        List of strategy names; defaults to all three.
    run_id : str, optional
        Run identifier for grouping artifacts.
    num_candidates, num_staff, num_days, slots_per_day : int
        Synthetic dataset dimensions.
    complexity : str
        "simple", "medium", or "complex".
    noise_type : str, optional
        Type of noise to apply (e.g., "staff_unavailable", "candidate_removal").
        If None, no noise is applied to the initial problem.
    noise_num_people : int
        Number of people (staff or candidates) affected by noise.
    noise_intensity : int
        Intensity level of noise (meaning varies by noise type).
    
    Returns
    -------
    DataStore
        Populated DataStore with all persisted schedules/events.
    """
    base = base_dir
    run_id = run_id or f"synthetic-{uuid.uuid4().hex[:8]}"
    ds = DataStore(config={"base_dir": base, "run_id": run_id})

    # Generate synthetic dataset (clean, no noise applied yet)
    dataset = generate_synthetic_dataset(
        num_candidates=num_candidates,
        num_staff=num_staff,
        num_days=num_days,
        slots_per_day=slots_per_day,
        complexity=complexity,
        require_leads=require_leads,
        seed=random_seed,
    )

    params = {}
    if random_seed is not None:
        params["random_seed"] = int(random_seed)
        params["deterministic"] = True
    params["persist"] = bool(persist)
    params["allow_parallel"] = bool(allow_parallel)
    params["max_parallel"] = int(max_parallel)

    data_store = {
        "candidates": dataset["candidates"],
        "time_slots": dataset["time_slots"],
        "avail": dataset["avail"],
        "staff": dataset["staff"],
        "staff_avail": dataset["staff_avail"],
        "required_staff": dataset["required_staff"],
        "forbidden_pairs": dataset["forbidden_pairs"],
    }

    params_for_solver = dict(params)
    params_for_solver["_data_store_dict"] = dict(data_store)
    schedule, meta = solver_module.solve_initial_schedule(data_store=ds, params=params_for_solver)
    staff_assign = meta.get("staff_assignment", {})
    _print_schedule(schedule, staff_assign)
    print("Initial schedule saved id:", meta.get("saved_schedule_id"))
    initial_schedule_id = meta.get("saved_schedule_id")

    strategies = strategies or ["reschedule_from_scratch", "change_penalty", "local_repair", "fairness_weighted", "greedy_least_loaded", "variance_minimizing"]

    for strat in strategies:
        p = dict(params)
        p["strategy"] = strat
        p["persist"] = False
        p_for_solver = dict(p)
        p_for_solver["_data_store_dict"] = dict(data_store)
        sched_s, meta_s = solver_module.reschedule(data_store=ds, change_event={}, params=p_for_solver)
        print(f"Strategy {strat} produced (probe) schedule; not persisted")

    change_events = []

    if noise_type:
        print(f"\n=== Noise mode: {noise_type} ===")
        print(f"Parameters: num_people={noise_num_people}, intensity={noise_intensity}")

        staff_assignment = meta.get("staff_assignment", {})

        noisy_avail, noisy_staff_avail = apply_noise(
            avail=dataset["avail"],
            staff_avail=dataset["staff_avail"],
            noise_type=noise_type,
            num_people=noise_num_people,
            intensity=noise_intensity,
            seed=random_seed,
            staff_assignment=staff_assignment,
            schedule=schedule,
        )

        change_details = None
        if noise_type == "candidate_unavailable":
            change_details = compute_candidate_unavailable_details(dataset["avail"], noisy_avail)
        elif noise_type in ("staff_unavailable", "random_staff_unavailable"):
            change_details = compute_staff_unavailable_details(dataset["staff_avail"], noisy_staff_avail)
        
        # Extract actual unavailability tuples (what the solver needs to apply)
        # For staff_unavailable noise, extract (staff_id, timeslot) pairs
        staff_unavailable_tuples = []
        if noise_type in ("staff_unavailable", "random_staff_unavailable"):
            all_staff = set(dataset["staff_avail"].keys()) | set(noisy_staff_avail.keys())
            all_slots = set()
            for s_avail in [dataset["staff_avail"], noisy_staff_avail]:
                for slots in s_avail.values():
                    all_slots.update(slots.keys())
            
            for staff_id in sorted(all_staff):
                before_slots = dataset["staff_avail"].get(staff_id, {})
                after_slots = noisy_staff_avail.get(staff_id, {})
                for slot in sorted(all_slots):
                    before_avail = before_slots.get(slot, 1)
                    after_avail = after_slots.get(slot, 1)
                    if before_avail == 1 and after_avail == 0:
                        staff_unavailable_tuples.append((staff_id, slot))
        # For candidate_unavailable noise, extract (candidate_id, timeslot) pairs
        candidate_unavailable_tuples = []
        if noise_type == "candidate_unavailable":
            all_cands = set(dataset["avail"].keys()) | set(noisy_avail.keys())
            all_slots = set()
            for a_dict in [dataset["avail"], noisy_avail]:
                for slots in a_dict.values():
                    all_slots.update(slots.keys())
            
            for cand_id in sorted(all_cands):
                before_slots = dataset["avail"].get(cand_id, {})
                after_slots = noisy_avail.get(cand_id, {})
                for slot in sorted(all_slots):
                    before_avail = before_slots.get(slot, 1)
                    after_avail = after_slots.get(slot, 1)
                    if before_avail == 1 and after_avail == 0:
                        candidate_unavailable_tuples.append((cand_id, slot))
        
        ce = {
            "noise_applied": {
                "type": noise_type,
                "num_people": noise_num_people,
                "intensity": noise_intensity,
                "description": f"{noise_type} applied to initial problem"
            }
        }

        if staff_unavailable_tuples:
            ce["staff_unavailable"] = staff_unavailable_tuples
        if candidate_unavailable_tuples:
            ce["candidate_unavailable"] = candidate_unavailable_tuples

        if change_details:
            ce["change_details"] = change_details

        change_events.append(ce)
    else:
        print(f"\n=== Scripted mode: standard change events ===")
        
        if dataset["staff"] and dataset["time_slots"]:
            su = [(dataset["staff"][0], dataset["time_slots"][0])]
            if len(dataset["staff"]) > 1 and len(dataset["time_slots"]) > 1:
                su.append((dataset["staff"][1], dataset["time_slots"][1]))
            change_events.append({"staff_unavailable": su})

        if dataset["candidates"]:
            change_events.append({"remove_candidate": [dataset["candidates"][0]]})

        change_events.append({"add_candidate": ["cand_new"]})

    for i, ce in enumerate(change_events):
        print(f"Applying change_event {i+1}:", ce)
        for strat in strategies:
            p = dict(params)
            p["strategy"] = strat
            if initial_schedule_id:
                p["use_saved_schedule_id"] = initial_schedule_id
            p_for_solver = dict(p)
            p_for_solver["_data_store_dict"] = dict(data_store)
            sched_s, meta_s = solver_module.reschedule(data_store=ds, change_event=ce, params=p_for_solver)
            print(f"After change {i+1}, strategy {strat} saved schedule id:", meta_s.get("saved_schedule_id"))
            _print_schedule(sched_s, meta_s.get("staff_assignment", {}))

    return ds