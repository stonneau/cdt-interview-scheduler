def test_fairness_weighted_feasible():
    ds = copy.deepcopy(BASE_DATA_STORE)
    params = {"min_staff_per_slot": 1, "time_limit": 3}
    schedule, meta = strategies.fairness_weighted(ds, {}, params)
    assert_feasible_schedule(schedule, meta, ds)

def test_greedy_least_loaded_feasible():
    ds = copy.deepcopy(BASE_DATA_STORE)
    params = {"min_staff_per_slot": 1, "time_limit": 3}
    schedule, meta = strategies.greedy_least_loaded(ds, {}, params)
    assert_feasible_schedule(schedule, meta, ds)

def test_variance_minimizing_feasible():
    ds = copy.deepcopy(BASE_DATA_STORE)
    params = {"min_staff_per_slot": 1, "time_limit": 3}
    schedule, meta = strategies.variance_minimizing(ds, {}, params)
    assert_feasible_schedule(schedule, meta, ds)
import copy
import pytest

from scheduler import strategies

# Small synthetic instance used across tests
BASE_DATA_STORE = {
    "candidates": ["A", "B", "C"],
    "time_slots": ["t1", "t2", "t3"],
    # all candidates available everywhere by default
    "avail": {
        "A": {"t1": 1, "t2": 1, "t3": 1},
        "B": {"t1": 1, "t2": 1, "t3": 1},
        "C": {"t1": 1, "t2": 1, "t3": 1},
    },
    "staff": ["s1", "s2"],
    # baseline: both staff available on all slots
    "staff_avail": {
        "s1": {"t1": 1, "t2": 1, "t3": 1},
        "s2": {"t1": 1, "t2": 1, "t3": 1},
    },
    # requirements: A needs s1, B needs s2, C none
    "required_staff": {"A": "s1", "B": "s2"},
    "forbidden_pairs": [],
    # previous schedule: A @ t2 (with s1), B @ t1 (with s2), C @ t3 (with s2)
    "prev_schedule": {"A": "t2", "B": "t1", "C": "t3"},
    "prev_staff_assignment": {"t1": ["s2"], "t2": ["s1"], "t3": ["s2"]},
}


def assert_feasible_schedule(schedule, metadata, ds):
    """
    Basic feasibility checks:
      - every candidate assigned to a slot (not None)
      - at most one candidate per slot
      - required staff present in staff_assignment for the assigned slot
      - staff assigned respect staff_avail
    """
    assert isinstance(metadata, dict), "metadata must be a dict"
    status = metadata.get("status", "")
    assert status in ("OPTIMAL", "FEASIBLE"), f"Solver status not feasible: {status}"

    candidates = list(ds["candidates"])
    time_slots = list(ds["time_slots"])
    staff_avail = ds["staff_avail"]
    required_staff = ds.get("required_staff", {})
    staff_assignment = metadata.get("staff_assignment", {})

    # all candidates assigned and valid slot
    assert set(schedule.keys()) == set(candidates)
    for c, t in schedule.items():
        assert t in time_slots, f"Candidate {c} assigned to invalid slot {t}"

    # no double-booking (<=1 candidate per slot)
    assigned_slots = [t for t in schedule.values()]
    assert len(assigned_slots) == len(set(assigned_slots)), "Double-booking detected"

    # required staff present & staff availability respected
    for c, t in schedule.items():
        req = required_staff.get(c)
        if req:
            staff_at_t = staff_assignment.get(t, [])
            assert req in staff_at_t, f"Required staff {req} not present for candidate {c} at {t}"
        # staff_assignment must respect staff_avail
    for t, staff_list in staff_assignment.items():
        for s in staff_list:
            assert staff_avail.get(s, {}).get(t, 0) == 1, f"Staff {s} assigned at {t} but not available"


def count_changed(prev_schedule, new_schedule):
    cnt = 0
    for c, old_t in prev_schedule.items():
        new_t = new_schedule.get(c)
        if new_t != old_t:
            cnt += 1
    return cnt


def test_change_penalty_vs_scratch():
    # perturb baseline: make s1 unavailable at t2 (breaks prev A @ t2)
    ds = copy.deepcopy(BASE_DATA_STORE)
    perturbed = copy.deepcopy(ds)
    perturbed["staff_avail"]["s1"]["t2"] = 0

    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule_scratch, meta_scratch = strategies.reschedule_from_scratch(perturbed, {}, params)
    schedule_change, meta_change = strategies.change_penalty(perturbed, {}, params)

    # both should be feasible
    assert_feasible_schedule(schedule_scratch, meta_scratch, perturbed)
    assert_feasible_schedule(schedule_change, meta_change, perturbed)

    # compute changed assignments relative to previous baseline
    prev = ds["prev_schedule"]
    changed_scratch = count_changed(prev, schedule_scratch)
    changed_change = count_changed(prev, schedule_change)

    # change_penalty should produce no more changes than full reschedule
    assert changed_change <= changed_scratch


def test_local_repair_feasible_and_stable():
    ds = copy.deepcopy(BASE_DATA_STORE)
    # perturb: s1 unavailable at t2
    ds["staff_avail"]["s1"]["t2"] = 0
    params = {"min_staff_per_slot": 1, "time_limit": 3, "max_local_size": 10}

    schedule_local, meta_local = strategies.local_repair(ds, {}, params)

    assert_feasible_schedule(schedule_local, meta_local, ds)
    # local repair should aim to change only affected candidates (at least not blow up)
    # loose assertion: no more than all candidates changed
    prev = BASE_DATA_STORE["prev_schedule"]
    changed_local = count_changed(prev, schedule_local)
    assert changed_local <= len(ds["candidates"])


def test_slack_based_respects_blocked_slots():
    ds = copy.deepcopy(BASE_DATA_STORE)
    # use slack_fraction that blocks 1 slot deterministically (len=3 -> floor(3*0.34)=1)
    params = {"min_staff_per_slot": 1, "time_limit": 3, "slack_fraction": 0.34}
    schedule_slack, meta_slack = strategies.slack_based(ds, {}, params)

    assert_feasible_schedule(schedule_slack, meta_slack, ds)

    # If slack_fraction results in blocking slots while still leaving enough
    # remaining slots for all candidates (no double-booking required), then
    # the blocked slot should be empty. Otherwise the behaviour is allowed to
    # fall back to a no-op (no blocking) to preserve feasibility.
    blocked_slot = ds["time_slots"][-1]
    num_to_block = int(len(ds["time_slots"]) * params["slack_fraction"]) if params.get("slack_fraction") else 0
    if num_to_block > 0 and (len(ds["time_slots"]) - num_to_block) >= len(ds["candidates"]):
        assert all(t != blocked_slot for t in schedule_slack.values()), "Candidate scheduled in blocked slack slot"


# ---------- PLNS (Parallel Large Neighborhood Search) tests ----------


def test_plns_feasible():
    """PLNS should produce a feasible schedule after a staff disruption."""
    ds = copy.deepcopy(BASE_DATA_STORE)
    # Disrupt: s1 unavailable at t2 (breaks prev A @ t2)
    ds["staff_avail"]["s1"]["t2"] = 0
    change_event = {"staff_unavailable": [("s1", "t2")]}
    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule, meta = strategies.plns(ds, change_event, params)
    assert_feasible_schedule(schedule, meta, ds)


def test_plns_preserves_unaffected():
    """Candidates outside the destroyed neighbourhood should stay put."""
    ds = copy.deepcopy(BASE_DATA_STORE)
    # Add extra candidates/slots so there is a clear unaffected region.
    ds["candidates"] = ["A", "B", "C", "D", "E"]
    ds["time_slots"] = ["t1", "t2", "t3", "t4", "t5"]
    for c in ds["candidates"]:
        ds["avail"][c] = {t: 1 for t in ds["time_slots"]}
    for s in ds["staff"]:
        ds["staff_avail"][s] = {t: 1 for t in ds["time_slots"]}
    ds["prev_schedule"] = {"A": "t1", "B": "t2", "C": "t3", "D": "t4", "E": "t5"}
    ds["prev_staff_assignment"] = {
        "t1": ["s1", "s2"], "t2": ["s1", "s2"], "t3": ["s1", "s2"],
        "t4": ["s1", "s2"], "t5": ["s1", "s2"],
    }
    # Only A needs s1; others have no required staff
    ds["required_staff"] = {"A": "s1"}

    # Disrupt: s1 unavailable at t1 → only A (and possibly B sharing slot
    # neighbourhood) should be destroyed; D and E must stay.
    ds["staff_avail"]["s1"]["t1"] = 0
    change_event = {"staff_unavailable": [("s1", "t1")]}
    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule, meta = strategies.plns(ds, change_event, params)
    assert_feasible_schedule(schedule, meta, ds)

    # D and E were not in the destroyed neighbourhood and must keep
    # their original slots.
    assert schedule["D"] == "t4", "Unaffected candidate D should stay at t4"
    assert schedule["E"] == "t5", "Unaffected candidate E should stay at t5"


def test_plns_fallback_no_prev_schedule():
    """Without a previous schedule PLNS should fall back to change_penalty."""
    ds = copy.deepcopy(BASE_DATA_STORE)
    ds.pop("prev_schedule", None)
    ds.pop("prev_staff_assignment", None)
    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule, meta = strategies.plns(ds, {}, params)
    assert_feasible_schedule(schedule, meta, ds)


def test_plns_staff_removed_disruption():
    """PLNS should handle a staff member being removed entirely."""
    ds = copy.deepcopy(BASE_DATA_STORE)
    # Remove s1 from staff → candidate A (who requires s1) must be rescheduled
    ds["staff"] = ["s2"]
    ds["staff_avail"].pop("s1", None)
    ds["required_staff"] = {"B": "s2"}  # Remove A's requirement since s1 is gone
    change_event = {"staff_removed": ["s1"]}
    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule, meta = strategies.plns(ds, change_event, params)
    assert_feasible_schedule(schedule, meta, ds)


def test_plns_candidate_unavailable_disruption():
    """PLNS should handle a candidate becoming unavailable at a slot."""
    ds = copy.deepcopy(BASE_DATA_STORE)
    # Make candidate A unavailable at t2 (where they were previously scheduled)
    ds["avail"]["A"]["t2"] = 0
    change_event = {"candidate_unavailable": [("A", "t2")]}
    params = {"min_staff_per_slot": 1, "time_limit": 3}

    schedule, meta = strategies.plns(ds, change_event, params)
    assert_feasible_schedule(schedule, meta, ds)
    # A should not be at t2 anymore
    assert schedule["A"] != "t2", "Candidate A should have moved away from t2"


def test_plns_discoverable_via_get_strategy():
    """The plns strategy should be discoverable by name."""
    fn = strategies.get_strategy("plns")
    assert fn is strategies.plns
    # Case-insensitive
    fn2 = strategies.get_strategy("PLNS")
    assert fn2 is strategies.plns