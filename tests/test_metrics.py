import pytest

from eval.metrics import ScheduleMetrics


def test_staff_loads_and_variance():
    # two slots, staff assignments:
    staff_assignment = {
        "slot1": ["s1", "s2"],
        "slot2": ["s1"],
    }
    sched = {"c1": "slot1", "c2": "slot2"}
    prev = {"c1": "slot1", "c2": "slot1"}
    sm = ScheduleMetrics(schedule=sched, prev_schedule=prev, staff_assignment=staff_assignment, time_slots=["slot1","slot2"]) 

    loads = sm._staff_loads()
    assert loads["s1"] == 2
    assert loads["s2"] == 1

    var = sm._staff_load_variance()
    # variance of [2,1] is 0.25
    assert abs(var - 0.25) < 1e-6


def test_count_changes_and_temporal():
    sched = {"c1": "2025-04-01 09:00-09:45", "c2": "2025-04-01 09:45-10:30"}
    prev = {"c1": "2025-04-01 09:00-09:45", "c2": "2025-04-01 10:30-11:15"}
    sm = ScheduleMetrics(schedule=sched, prev_schedule=prev, staff_assignment={}, time_slots=["2025-04-01 09:00-09:45","2025-04-01 09:45-10:30","2025-04-01 10:30-11:15"]) 
    # Only candidate changes counted here (no prev_staff_assignment)
    assert sm._count_candidate_changes() == 1
    assert sm._count_staff_changes() == 0
    assert sm._count_changes() == 1
    td = sm._temporal_deviation()
    # c2 moved from 10:30 to 09:45 => 45 minutes
    assert abs(td - 45.0) < 1e-6


def test_count_staff_changes():
    """changed_assignments should count both candidate and staff changes."""
    sched = {"c1": "slot1", "c2": "slot2"}
    prev = {"c1": "slot1", "c2": "slot1"}
    prev_staff = {"slot1": ["s1", "s2"], "slot2": ["s1"]}
    new_staff = {"slot1": ["s1"], "slot2": ["s1", "s2"]}
    sm = ScheduleMetrics(
        schedule=sched,
        prev_schedule=prev,
        staff_assignment=new_staff,
        time_slots=["slot1", "slot2"],
        prev_staff_assignment=prev_staff,
    )
    # c2 moved from slot1 to slot2 → 1 candidate change
    assert sm._count_candidate_changes() == 1
    # s2 was at slot1, now at slot2 → 2 staff changes (removed from slot1, added to slot2)
    assert sm._count_staff_changes() == 2
    # Total = 1 + 2 = 3
    assert sm._count_changes() == 3

    stability = sm.stability_metrics()
    assert stability["changed_assignments"] == 3.0
    assert stability["changed_candidate_assignments"] == 1.0
    assert stability["changed_staff_assignments"] == 2.0
