from scheduler import strategies


def make_minimal_ds():
    candidates = ["c1", "c2"]
    time_slots = ["t1", "t2"]
    avail = {c: {t: 1 for t in time_slots} for c in candidates}
    staff = ["lead1", "panel1"]
    staff_avail = {s: {t: 1 for t in time_slots} for s in staff}
    required_staff = {c: ["lead1"] for c in candidates}
    prev_schedule = {"c1": "t1", "c2": "t2"}
    prev_staff_assignment = {"t1": ["lead1"], "t2": ["lead1"]}
    return {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": set(),
        "prev_schedule": prev_schedule,
        "prev_staff_assignment": prev_staff_assignment,
    }


def test_candidate_change_param_runs():
    ds = make_minimal_ds()
    params = {"time_limit": 1, "random_seed": 1, "deterministic": True, "candidate_change_penalty_weight": 5}
    schedule, meta = strategies.change_penalty(ds, {}, params)
    assert isinstance(schedule, dict)
    assert "num_changed_assignments" in meta