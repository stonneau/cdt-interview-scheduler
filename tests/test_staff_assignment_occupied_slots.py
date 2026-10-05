"""
Test that staff_assignment only includes slots with scheduled candidates.

This verifies the fix where staff allocation is constrained only for slots
with candidates, not for all slots.
"""

import pytest
from scheduler.solver import solve_initial_schedule


def test_staff_assignment_only_occupied_slots():
    """Staff should only be assigned to slots with candidates, not all slots."""
    # Simple scenario: 2 candidates, 5 timeslots
    # Candidates can only be scheduled in 2 specific slots
    data_store = {
        "candidates": ["cand1", "cand2"],
        "time_slots": ["slot1", "slot2", "slot3", "slot4", "slot5"],
        "avail": {
            "cand1": {"slot1": 1, "slot2": 0, "slot3": 0, "slot4": 0, "slot5": 0},
            "cand2": {"slot1": 0, "slot2": 1, "slot3": 0, "slot4": 0, "slot5": 0},
        },
        "staff": ["staff1", "staff2"],
        "staff_avail": {
            "staff1": {"slot1": 1, "slot2": 1, "slot3": 1, "slot4": 1, "slot5": 1},
            "staff2": {"slot1": 1, "slot2": 1, "slot3": 1, "slot4": 1, "slot5": 1},
        },
        "required_staff": {},
        "forbidden_pairs": [],
    }
    
    schedule, metadata = solve_initial_schedule(data_store=data_store, params={})
    staff_assignment = metadata.get("staff_assignment", {})
    
    # Verify schedule has 2 candidates assigned
    assert len(schedule) == 2, f"Expected 2 candidates in schedule, got {len(schedule)}"
    
    # Verify staff_assignment only includes occupied slots
    occupied_slots = set(s for s in schedule.values() if s is not None)
    assert len(occupied_slots) == 2, f"Expected 2 occupied slots, got {len(occupied_slots)}"
    
    # Check that staff_assignment keys are only occupied slots
    staff_assign_slots = set(staff_assignment.keys())
    assert staff_assign_slots == occupied_slots, (
        f"staff_assignment slots {staff_assign_slots} should match occupied slots {occupied_slots}. "
        f"Extra slots: {staff_assign_slots - occupied_slots}"
    )
    
    # Verify no empty slot assignments
    for slot in staff_assignment:
        assert len(staff_assignment[slot]) >= 2, (
            f"Slot {slot} should have at least 2 staff (min_staff_per_slot=2), got {staff_assignment[slot]}"
        )


def test_staff_assignment_matches_schedule_size():
    """Number of staff assignments should be <= number of candidates scheduled."""
    data_store = {
        "candidates": ["c1", "c2", "c3"],
        "time_slots": ["t1", "t2", "t3", "t4"],
        "avail": {
            "c1": {"t1": 1, "t2": 0, "t3": 0, "t4": 0},
            "c2": {"t1": 0, "t2": 1, "t3": 0, "t4": 0},
            "c3": {"t1": 0, "t2": 0, "t3": 1, "t4": 0},
        },
        "staff": ["s1", "s2", "s3"],
        "staff_avail": {
            "s1": {t: 1 for t in ["t1", "t2", "t3", "t4"]},
            "s2": {t: 1 for t in ["t1", "t2", "t3", "t4"]},
            "s3": {t: 1 for t in ["t1", "t2", "t3", "t4"]},
        },
        "required_staff": {},
        "forbidden_pairs": [],
    }
    
    schedule, metadata = solve_initial_schedule(data_store=data_store, params={})
    staff_assignment = metadata.get("staff_assignment", {})
    
    # Should have at most 3 staff assignments (one per candidate)
    assert len(staff_assignment) <= 3, (
        f"Expected at most 3 staff assignments (num candidates), got {len(staff_assignment)}"
    )
    
    # All staff assignments should correspond to a scheduled candidate
    for slot in staff_assignment:
        assert slot in schedule.values(), (
            f"Staff assigned to slot {slot}, but no candidate scheduled there"
        )


def test_empty_slots_have_no_staff():
    """Empty slots (no candidate) should have empty or no staff list."""
    data_store = {
        "candidates": ["cand1"],
        "time_slots": ["slot1", "slot2", "slot3"],
        "avail": {
            "cand1": {"slot1": 1, "slot2": 0, "slot3": 0},
        },
        "staff": ["staff1", "staff2"],
        "staff_avail": {
            "staff1": {"slot1": 1, "slot2": 1, "slot3": 1},
            "staff2": {"slot1": 1, "slot2": 1, "slot3": 1},
        },
        "required_staff": {},
        "forbidden_pairs": [],
    }
    
    schedule, metadata = solve_initial_schedule(data_store=data_store, params={})
    staff_assignment = metadata.get("staff_assignment", {})
    
    # slot2 and slot3 have no candidates, should not have staff assignments
    assert "slot2" not in staff_assignment or len(staff_assignment.get("slot2", [])) == 0, (
        "slot2 (no candidate) should not have staff"
    )
    assert "slot3" not in staff_assignment or len(staff_assignment.get("slot3", [])) == 0, (
        "slot3 (no candidate) should not have staff"
    )
