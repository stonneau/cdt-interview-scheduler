from scheduler.solver import solve_initial_schedule, reschedule


def make_minimal_ds():
    # 3 candidates, 3 slots, 3 staff
    candidates = ["c1", "c2", "c3"]
    time_slots = ["t1", "t2", "t3"]
    avail = {c: {t: 1 for t in time_slots} for c in candidates}
    staff = ["lead1", "panel1", "panel2"]
    staff_avail = {s: {t: 1 for t in time_slots} for s in staff}
    required_staff = {c: ["lead1"] for c in candidates}
    forbidden_pairs = set()
    return {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
    }


def test_solve_initial_deterministic():
    ds = make_minimal_ds()
    params = {"time_limit": 1, "random_seed": 12345, "deterministic": True, "persist": False}
    sched1, meta1 = solve_initial_schedule(data_store=ds, params=params)
    sched2, meta2 = solve_initial_schedule(data_store=ds, params=params)

    assert sched1 == sched2
    # metadata fields should be equal for deterministic runs (status and objective)
    assert meta1.get("status") == meta2.get("status")
    assert meta1.get("objective_value") == meta2.get("objective_value")


def test_reschedule_deterministic_strategy():
    ds = make_minimal_ds()
    params = {"time_limit": 1, "random_seed": 9999, "deterministic": True, "persist": False, "strategy": "change_penalty"}
    # Run reschedule twice with same input and same seed
    sched1, meta1 = reschedule(data_store=ds, change_event={}, params=params)
    sched2, meta2 = reschedule(data_store=ds, change_event={}, params=params)

    assert sched1 == sched2
    assert meta1.get("status") == meta2.get("status")