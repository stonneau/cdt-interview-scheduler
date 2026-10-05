"""
Unit tests for eval.change_analyzer module.

Tests the human-readable change detail computation functions.
"""

import pytest
from eval.change_analyzer import (
    compute_staff_unavailable_details,
    compute_candidate_unavailable_details,
    compute_removal_details,
)


class TestComputeStaffUnavailableDetails:
    """Test staff availability change detection."""

    def test_no_changes(self):
        """When availability unchanged, return empty string."""
        before = {"lead1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1}}
        after = {"lead1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1}}
        result = compute_staff_unavailable_details(before, after)
        assert result == ""

    def test_single_staff_one_slot_unavailable(self):
        """Single staff becomes unavailable at one slot."""
        before = {"lead1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1}}
        after = {"lead1": {"2025-04-01 08:00": 0, "2025-04-01 09:00": 1}}
        result = compute_staff_unavailable_details(before, after)
        assert result == "lead1 on 2025-04-01 08:00"

    def test_multiple_staff_multiple_slots(self):
        """Multiple staff become unavailable at different slots."""
        before = {
            "lead1": {"slot1": 1, "slot2": 1},
            "lead2": {"slot1": 1, "slot2": 1},
        }
        after = {
            "lead1": {"slot1": 0, "slot2": 1},  # lead1 unavailable at slot1
            "lead2": {"slot1": 1, "slot2": 0},  # lead2 unavailable at slot2
        }
        result = compute_staff_unavailable_details(before, after)
        assert "lead1 on slot1" in result
        assert "lead2 on slot2" in result

    def test_truncation_with_max_items(self):
        """When changes exceed max_items, show truncation indicator."""
        before = {f"staff{i}": {f"slot{j}": 1 for j in range(3)} for i in range(10)}
        after = {f"staff{i}": {f"slot{j}": 0 if j == 0 else 1 for j in range(3)} for i in range(10)}
        result = compute_staff_unavailable_details(before, after, max_items=3)
        assert "(+7 more)" in result
        # Should have 3 items in the main part, with truncation indicator appended to last one
        parts = result.split("; ")
        assert len(parts) == 3  # 3 items; the last one has the "+X more" appended

    def test_empty_dicts(self):
        """Empty input dicts return empty string."""
        result = compute_staff_unavailable_details({}, {})
        assert result == ""

    def test_already_unavailable_not_counted(self):
        """Transitions from unavailable to unavailable (0->0) not counted."""
        before = {"lead1": {"slot1": 0, "slot2": 1}}
        after = {"lead1": {"slot1": 0, "slot2": 1}}
        result = compute_staff_unavailable_details(before, after)
        assert result == ""

    def test_available_to_available_not_counted(self):
        """Transitions from available to available (1->1) not counted."""
        before = {"lead1": {"slot1": 1}}
        after = {"lead1": {"slot1": 1}}
        result = compute_staff_unavailable_details(before, after)
        assert result == ""

    def test_newly_added_staff(self):
        """Staff added in after but not before are ignored (0->1 not tracked)."""
        before = {"lead1": {"slot1": 1}}
        after = {"lead1": {"slot1": 1}, "lead2": {"slot1": 1}}
        result = compute_staff_unavailable_details(before, after)
        assert result == ""


class TestComputeCandidateUnavailableDetails:
    """Test candidate availability change detection."""

    def test_no_changes(self):
        """When availability unchanged, return empty string."""
        before = {"cand1": {"slot1": 1, "slot2": 1}}
        after = {"cand1": {"slot1": 1, "slot2": 1}}
        result = compute_candidate_unavailable_details(before, after)
        assert result == ""

    def test_single_candidate_unavailable(self):
        """Single candidate becomes unavailable at one slot."""
        before = {"cand1": {"slot1": 1, "slot2": 1}}
        after = {"cand1": {"slot1": 0, "slot2": 1}}
        result = compute_candidate_unavailable_details(before, after)
        assert result == "cand1 on slot1"

    def test_multiple_candidates_multiple_slots(self):
        """Multiple candidates become unavailable."""
        before = {
            "cand1": {"slot1": 1, "slot2": 1, "slot3": 1},
            "cand2": {"slot1": 1, "slot2": 1, "slot3": 1},
        }
        after = {
            "cand1": {"slot1": 0, "slot2": 1, "slot3": 1},
            "cand2": {"slot1": 1, "slot2": 0, "slot3": 1},
        }
        result = compute_candidate_unavailable_details(before, after)
        assert "cand1 on slot1" in result
        assert "cand2 on slot2" in result

    def test_truncation(self):
        """Truncation works for candidates."""
        before = {f"cand{i}": {f"s{j}": 1 for j in range(2)} for i in range(8)}
        after = {f"cand{i}": {f"s{j}": 0 if j == 0 else 1 for j in range(2)} for i in range(8)}
        result = compute_candidate_unavailable_details(before, after, max_items=2)
        assert "(+6 more)" in result

    def test_empty_dicts(self):
        """Empty dicts return empty string."""
        result = compute_candidate_unavailable_details({}, {})
        assert result == ""


class TestComputeRemovalDetails:
    """Test removal details formatting."""

    def test_single_removal(self):
        """Single removed ID."""
        result = compute_removal_details(["cand1"], removal_type="candidate")
        assert result == "cand1"

    def test_multiple_removals(self):
        """Multiple removed IDs joined by comma."""
        result = compute_removal_details(["cand1", "cand2", "cand3"], removal_type="candidate")
        assert result == "cand1, cand2, cand3"

    def test_truncation_many_removals(self):
        """When removals exceed max_items, show truncation."""
        removed = [f"cand{i}" for i in range(10)]
        result = compute_removal_details(removed, removal_type="candidate", max_items=5)
        assert result == "cand0, cand1, cand2, cand3, cand4 (+5 more)"

    def test_empty_list(self):
        """Empty removal list returns empty string."""
        result = compute_removal_details([])
        assert result == ""

    def test_staff_removal(self):
        """Removal type param is accepted (for documentation)."""
        result = compute_removal_details(["lead1", "lead2"], removal_type="staff")
        assert result == "lead1, lead2"


class TestIntegration:
    """Integration tests combining multiple change types."""

    def test_realistic_noise_scenario(self):
        """Realistic scenario: several staff become unavailable."""
        before = {
            "lead1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1, "2025-04-01 10:00": 1},
            "lead2": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1, "2025-04-01 10:00": 1},
            "panel1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1, "2025-04-01 10:00": 1},
        }
        after = {
            "lead1": {"2025-04-01 08:00": 0, "2025-04-01 09:00": 1, "2025-04-01 10:00": 1},
            "lead2": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 0, "2025-04-01 10:00": 1},
            "panel1": {"2025-04-01 08:00": 1, "2025-04-01 09:00": 1, "2025-04-01 10:00": 0},
        }
        result = compute_staff_unavailable_details(before, after)
        assert "lead1 on 2025-04-01 08:00" in result
        assert "lead2 on 2025-04-01 09:00" in result
        assert "panel1 on 2025-04-01 10:00" in result

    def test_combined_removals_and_unavailability(self):
        """Combine staff removals with availability changes."""
        staff_changes = compute_staff_unavailable_details(
            {"lead1": {"s1": 1, "s2": 1}},
            {"lead1": {"s1": 0, "s2": 1}},
        )
        removals = compute_removal_details(["staff2", "staff3"], removal_type="staff")
        assert staff_changes == "lead1 on s1"
        assert removals == "staff2, staff3"
