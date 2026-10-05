"""Demo harness for actual CSV data with optional noise injection.

Loads candidate and staff availability from real CSV files, solves the
initial schedule, then applies either noise-based or scripted change
events and reschedules with each configured strategy.

In **noise mode** (``noise_type`` is set), availability perturbations are
generated via ``noise_generators.apply_noise`` and restricted to
staff/candidates/slots present in the initial schedule.  Unavailability
tuples are extracted by diffing the original and noisy availability
matrices and attached to the change event for the solver.

In **scripted mode** (``noise_type`` is ``None``), standard change events
(staff unavailable, remove candidate, add candidate) are applied
sequentially.

All strategies work from the same initial schedule baseline so that
comparisons are fair.
"""

from typing import List

from data_models.store import DataStore
from data_models.loaders import (
    load_availability_objects_from_csv,
    load_prev_schedule_from_csv,
    load_staff_objects_from_csv,
    unify_slots,
    objects_to_solver_inputs_from_models,
)
from scheduler import solver as solver_module

from eval.noise_generators import apply_noise
from eval.change_analyzer import (
    compute_candidate_unavailable_details, 
    compute_staff_unavailable_details,
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

def run_actual_data_demo(
        applicants_csv: str,
        staff_csv: str,
        base_dir: str = "data/actual_runs",
        random_seed: int = None,
        persist: bool = True,
        strategies: List[str] = None,
        run_id: str = None,
        noise_type: str = None,
        noise_num_people: int = 1,
        noise_intensity: int = 1,
        allow_parallel: bool = False,
        max_parallel: int = 2,
) -> DataStore:
    """Run demo with actual data so we can apply noise and different runs

    Parameters
    ----------
    applicants_csv : str
        csv with the intended format of actual applicants' availability data
    staff_csv : str
        same but for staff
    base_dir : str
        Output base directory for DataStore.
    random_seed : int, optional
        Seed for solver reproducibility.
    persist : bool
        If True, persist schedules/events to disk.
    strategies : List[str], optional
        List of strategy names; defaults to all three.
    run_id : str, optional
        Run identifier for grouping artifacts.
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
    run_id = run_id or f"actual_run-{uuid.uuid4().hex[:8]}"
    ds = DataStore(config = {"base_dir": base, "run_id": run_id})

    candidates_objs, time_slots1 = load_availability_objects_from_csv(applicants_csv)
    staff_objs, time_slots2 = load_staff_objects_from_csv(staff_csv)
    candidates, staff, avail, staff_avail, required_staff, forbidden_pairs = (
        objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
    )
    time_slots = unify_slots(time_slots1, time_slots2)

    params = {}
    if random_seed is not None:
        params["random_seed"] = int(random_seed)
        params["deterministic"] = True
    params["persist"] = bool(persist)
    params["allow_parallel"] = bool(allow_parallel)
    params["max_parallel"] = int(max_parallel)

    data_store = {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
    }

    params_for_solver = dict(params)
    params_for_solver["_data_store_dict"] = dict(data_store)
    schedule, meta = solver_module.solve_initial_schedule(data_store=ds, params=params_for_solver)
    staff_assign = meta.get("staff_assignment", {})
    _print_schedule(schedule, staff_assign)
    print("[Actual Data Demo] Initial schedule saved id:", meta.get("saved_schedule_id"))
    initial_schedule_id = meta.get("saved_schedule_id")

    strategies = strategies or ["reschedule_from_scratch", "change_penalty", "local_repair"]

    change_events = []
    if noise_type:
        print(f"\n[Actual Data Demo] === Noise mode: {noise_type} ===")
        print(f"[Actual Data Demo] Parameters: num_people={noise_num_people}, intensity={noise_intensity}")

        noisy_avail, noisy_staff_avail = apply_noise(
            avail=avail,
            staff_avail=staff_avail,
            noise_type=noise_type,
            num_people=noise_num_people,
            intensity=noise_intensity,
            seed=random_seed,
            staff_assignment=staff_assign,
            schedule=schedule,
        )

        change_details = None
        if noise_type == "candidate_unavailable":
            change_details = compute_candidate_unavailable_details(avail, noisy_avail)
        elif noise_type in ("staff_unavailable", "random_staff_unavailable"):
            change_details = compute_staff_unavailable_details(staff_avail, noisy_staff_avail)

        staff_unavailable_tuples = []
        if noise_type in ("staff_unavailable", "random_staff_unavailable"):
            all_staff = set(staff_avail.keys()) | set(noisy_staff_avail.keys())
            all_slots = set()
            for s_avail in [staff_avail, noisy_staff_avail]:
                for slots in s_avail.values():
                        all_slots.update(slots.keys())
                
                for staff_id in sorted(all_staff):
                    before_slots = staff_avail.get(staff_id, {})
                    after_slots = noisy_staff_avail.get(staff_id, {})
                    for slot in sorted(all_slots):
                        before_avail = before_slots.get(slot, 1)
                        after_avail = after_slots.get(slot, 1)
                        if before_avail == 1 and after_avail == 0:
                            staff_unavailable_tuples.append((staff_id, slot))

        candidate_unavailable_tuples = []
        if noise_type == "candidate_unavailable":
            all_cands = set(avail.keys()) | set(noisy_avail.keys())
            all_slots = set()
            for a_dict in [avail, noisy_avail]:
                for slots in a_dict.values():
                    all_slots.update(slots.keys())
            
            for cand_id in sorted(all_cands):
                before_slots = avail.get(cand_id, {})
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
        
        if staff and time_slots:
            su = [(staff[0], time_slots[0])]
            if len(staff) > 1 and len(time_slots) > 1:
                su.append((staff[1], time_slots[1]))
            change_events.append({"staff_unavailable": su})

        if candidates:
            change_events.append({"remove_candidate": [candidates[0]]})

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