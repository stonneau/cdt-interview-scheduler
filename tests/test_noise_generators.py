"""
Tests for noise generation system.
"""

import pytest
from eval.noise_generators import (
    StaffUnavailableNoise,
    CandidateUnavailableNoise,
    CandidateRemovalNoise,
    StaffRemovalNoise,
    get_noise_generator,
    apply_noise,
    NOISE_GENERATORS,
)


@pytest.fixture
def sample_availability():
    """Create sample availability dictionaries."""
    avail = {
        "cand1": {"slot1": 1, "slot2": 1, "slot3": 0},
        "cand2": {"slot1": 1, "slot2": 0, "slot3": 1},
        "cand3": {"slot1": 0, "slot2": 1, "slot3": 1},
    }
    
    staff_avail = {
        "lead1": {"slot1": 1, "slot2": 1, "slot3": 1},
        "lead2": {"slot1": 1, "slot2": 1, "slot3": 1},
        "panel1": {"slot1": 0, "slot2": 1, "slot3": 1},
    }
    
    return avail, staff_avail


def test_staff_unavailable_noise(sample_availability):
    """Test staff unavailability noise."""
    avail, staff_avail = sample_availability
    generator = StaffUnavailableNoise(seed=42)
    
    new_avail, new_staff_avail = generator.generate(
        avail, staff_avail, num_people=1, intensity=1
    )
    
    # Verify copies were made (not mutated originals)
    assert avail != new_avail or staff_avail != new_staff_avail
    
    # Verify at least one staff member has reduced availability
    someone_reduced = False
    for staff_id in new_staff_avail:
        original_count = sum(staff_avail[staff_id].values())
        new_count = sum(new_staff_avail[staff_id].values())
        if new_count < original_count:
            someone_reduced = True
    
    assert someone_reduced, "Expected at least one staff to become unavailable"


def test_candidate_unavailable_noise(sample_availability):
    """Test candidate unavailability noise."""
    avail, staff_avail = sample_availability
    generator = CandidateUnavailableNoise(seed=42)
    
    new_avail, new_staff_avail = generator.generate(
        avail, staff_avail, num_people=1, intensity=1
    )
    
    # Verify at least one candidate has reduced availability
    someone_reduced = False
    for cand_id in new_avail:
        original_count = sum(avail[cand_id].values())
        new_count = sum(new_avail[cand_id].values())
        if new_count < original_count:
            someone_reduced = True
    
    assert someone_reduced, "Expected at least one candidate to become unavailable"


def test_candidate_removal_noise(sample_availability):
    """Test candidate removal noise."""
    avail, staff_avail = sample_availability
    generator = CandidateRemovalNoise(seed=42)
    
    original_cand_count = len(avail)
    new_avail, new_staff_avail = generator.generate(
        avail, staff_avail, num_people=1, intensity=None
    )
    
    # Verify one candidate was removed
    assert len(new_avail) == original_cand_count - 1
    assert len(new_staff_avail) == len(staff_avail)  # Staff unaffected


def test_candidate_removal_percentage(sample_availability):
    """Test candidate removal with percentage."""
    avail, staff_avail = sample_availability
    generator = CandidateRemovalNoise(seed=42)
    
    original_cand_count = len(avail)
    new_avail, new_staff_avail = generator.generate(
        avail, staff_avail, num_people=0.5, intensity=None  # Remove 50%
    )
    
    # Verify approximately half were removed
    expected_removed = max(1, int(original_cand_count * 0.5))
    assert len(new_avail) == original_cand_count - expected_removed


def test_staff_removal_noise(sample_availability):
    """Test staff removal noise."""
    avail, staff_avail = sample_availability
    generator = StaffRemovalNoise(seed=42)
    
    original_staff_count = len(staff_avail)
    new_avail, new_staff_avail = generator.generate(
        avail, staff_avail, num_people=1, intensity=None
    )
    
    # Verify one staff was removed
    assert len(new_staff_avail) == original_staff_count - 1
    assert len(new_avail) == len(avail)  # Candidates unaffected


def test_get_noise_generator():
    """Test noise generator registry."""
    gen = get_noise_generator("staff_unavailable", seed=42)
    assert isinstance(gen, StaffUnavailableNoise)
    
    gen = get_noise_generator("candidate_removal", seed=42)
    assert isinstance(gen, CandidateRemovalNoise)


def test_get_noise_generator_invalid():
    """Test error on invalid noise type."""
    with pytest.raises(ValueError, match="Unknown noise type"):
        get_noise_generator("invalid_noise_type")


def test_apply_noise_convenience(sample_availability):
    """Test apply_noise convenience function."""
    avail, staff_avail = sample_availability
    
    new_avail, new_staff_avail = apply_noise(
        avail, staff_avail,
        noise_type="staff_unavailable",
        num_people=1,
        intensity=1,
        seed=42
    )
    
    # Verify noise was applied
    assert new_avail is not avail  # Different objects
    assert new_staff_avail is not staff_avail


def test_noise_preserves_structure(sample_availability):
    """Test that noise preserves overall structure."""
    avail, staff_avail = sample_availability
    
    new_avail, new_staff_avail = apply_noise(
        avail, staff_avail,
        noise_type="staff_unavailable",
        num_people=2,
        intensity=1,
        seed=42
    )
    
    # All original keys should still exist (no removals)
    assert set(new_avail.keys()) == set(avail.keys())
    assert set(new_staff_avail.keys()) == set(staff_avail.keys())
    
    # All slots should still exist
    for cand in new_avail:
        assert set(new_avail[cand].keys()) == set(avail[cand].keys())
    
    for staff in new_staff_avail:
        assert set(new_staff_avail[staff].keys()) == set(staff_avail[staff].keys())


def test_high_intensity_noise(sample_availability):
    """Test high intensity noise."""
    avail, staff_avail = sample_availability
    
    new_avail, new_staff_avail = apply_noise(
        avail, staff_avail,
        noise_type="staff_unavailable",
        num_people=3,  # All staff
        intensity=3,   # Many slots per staff
        seed=42
    )
    
    # At least some staff should have reduced availability
    someone_reduced = False
    for staff_id in staff_avail:
        if sum(new_staff_avail[staff_id].values()) < sum(staff_avail[staff_id].values()):
            someone_reduced = True
    
    assert someone_reduced


def test_noise_reproducibility(sample_availability):
    """Test that same seed produces same noise."""
    avail, staff_avail = sample_availability
    
    result1 = apply_noise(
        avail, staff_avail,
        noise_type="staff_unavailable",
        num_people=1,
        intensity=1,
        seed=12345
    )
    
    result2 = apply_noise(
        avail, staff_avail,
        noise_type="staff_unavailable",
        num_people=1,
        intensity=1,
        seed=12345
    )
    
    # Same seed should produce same noise
    assert result1[0] == result2[0]
    assert result1[1] == result2[1]


def test_available_noise_types():
    """Test that all noise types are registered."""
    expected_types = {
        "staff_unavailable",
        "candidate_unavailable",
        "candidate_removal",
        "staff_removal",
    }
    
    assert set(NOISE_GENERATORS.keys()) == expected_types
