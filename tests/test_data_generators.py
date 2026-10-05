"""Tests for data generators."""

import pytest
from eval.data_generators import (
    generate_time_slots,
    generate_candidates,
    generate_staff,
    generate_availability_matrix,
    generate_synthetic_dataset,
)


def test_generate_time_slots():
    slots = generate_time_slots(num_days=2, slots_per_day=4, start_date="2025-04-01", slot_duration_min=45)
    assert len(slots) == 8
    assert slots[0] == "2025-04-01 08:00-08:45"
    assert slots[4] == "2025-04-02 08:00-08:45"


def test_generate_candidates():
    cands = generate_candidates(5)
    assert len(cands) == 5
    assert cands[0] == "cand1"
    assert cands[4] == "cand5"


def test_generate_staff():
    staff = generate_staff(6, num_leads=2)
    assert len(staff) == 6
    assert staff[0] == "lead1"
    assert staff[1] == "lead2"
    assert staff[2] == "panel1"


def test_generate_availability_matrix():
    ids = ["person1", "person2"]
    slots = ["2025-04-01 08:00-08:45", "2025-04-01 08:45-09:30"]
    avail = generate_availability_matrix(ids, slots, complexity="simple", seed=42)
    
    assert len(avail) == 2
    assert len(avail["person1"]) == 2
    # Values should be 0 or 1
    assert all(v in (0, 1) for v in avail["person1"].values())


def test_generate_synthetic_dataset_small():
    ds = generate_synthetic_dataset(
        num_candidates=5,
        num_staff=3,
        num_days=2,
        slots_per_day=2,
        complexity="simple",
        seed=123,
    )
    
    assert len(ds["candidates"]) == 5
    assert len(ds["staff"]) == 3
    assert len(ds["time_slots"]) == 4
    assert len(ds["avail"]) == 5
    assert len(ds["staff_avail"]) == 3
    # avail[cand][slot] should exist
    for cand in ds["candidates"]:
        for slot in ds["time_slots"]:
            assert slot in ds["avail"][cand]
            assert ds["avail"][cand][slot] in (0, 1)


def test_generate_synthetic_dataset_reproducible():
    ds1 = generate_synthetic_dataset(
        num_candidates=10,
        num_staff=6,
        num_days=3,
        slots_per_day=4,
        complexity="medium",
        seed=999,
    )
    ds2 = generate_synthetic_dataset(
        num_candidates=10,
        num_staff=6,
        num_days=3,
        slots_per_day=4,
        complexity="medium",
        seed=999,
    )
    
    # Same seed should produce identical outputs
    assert ds1["avail"] == ds2["avail"]
    assert ds1["staff_avail"] == ds2["staff_avail"]
    assert ds1["required_staff"] == ds2["required_staff"]


def test_generate_synthetic_dataset_complexity_levels():
    """Verify complexity affects unavailability."""
    simple_ds = generate_synthetic_dataset(
        num_candidates=9, num_staff=3, num_days=1, slots_per_day=2,
        complexity="simple", seed=42
    )
    complex_ds = generate_synthetic_dataset(
        num_candidates=9, num_staff=3, num_days=1, slots_per_day=2,
        complexity="complex", seed=42
    )
    
    # Count unavailabilities (0s)
    simple_zeros = sum(1 for cand_avail in simple_ds["avail"].values() 
                       for v in cand_avail.values() if v == 0)
    complex_zeros = sum(1 for cand_avail in complex_ds["avail"].values() 
                        for v in cand_avail.values() if v == 0)
    
    # Complex should have more unavailability
    assert complex_zeros >= simple_zeros
