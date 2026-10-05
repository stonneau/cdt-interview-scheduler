"""
Tests that noise only affects provided active slots when requested.
"""

from eval.noise_generators import apply_noise


def test_apply_noise_respects_active_slots():
    avail = {
        "cand1": {"slot1": 1, "slot2": 1},
    }

    staff_avail = {
        "lead1": {"slot1": 1, "slot2": 1, "slot3": 1},
        "lead2": {"slot1": 1, "slot2": 1, "slot3": 1},
    }

    # Only slots 1 and 2 are active in the schedule
    active_slots = {"slot1", "slot2"}

    # Define a staff_assignment mapping where lead1 is assigned to slot1,
    # and lead2 is assigned to slot2. slot3 is unassigned.
    staff_assignment = {"slot1": ["lead1"], "slot2": ["lead2"]}

    # Call with explicit staff_assignment so only those staff/slots may be altered
    new_avail, new_staff_avail = apply_noise(
        avail,
        staff_avail,
        noise_type="staff_unavailable",
        num_people=2,
        intensity=1,
        seed=123,
        staff_assignment=staff_assignment,
    )

    # Verify that non-assigned slots (slot3) were not changed
    for staff in staff_avail:
        assert new_staff_avail[staff]["slot3"] == staff_avail[staff]["slot3"]

    # Verify that changes happened only on assigned slots (slot1 or slot2)
    changed = False
    for s in staff_avail:
        for slot in ["slot1", "slot2"]:
            if new_staff_avail[s][slot] < staff_avail[s][slot]:
                changed = True
    assert changed
