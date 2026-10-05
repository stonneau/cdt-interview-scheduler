"""
Tests for specifying availability when adding new candidates/staff:
  1. _parse_add_csv validates format and slots
  2. Solver respects pre-set availability from ds (does not overwrite with all-available)
"""
import io
import pytest
import tempfile

from scheduler.solver import reschedule
from data_models.store import DataStore


# ---------------------------------------------------------------------------
# 1. _parse_add_csv tests
# ---------------------------------------------------------------------------

def _import_parse_add_csv():
    """Import _parse_add_csv from the web_app module."""
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from ui.web_app import _parse_add_csv
    return _parse_add_csv


def _make_csv_bytes(content: str) -> io.BytesIO:
    """Create a BytesIO CSV file (simulates Streamlit UploadedFile)."""
    return io.BytesIO(content.encode("utf-8"))


class TestParseAddCsv:
    """Tests for the _parse_add_csv helper."""

    def setup_method(self):
        self._parse_add_csv = _import_parse_add_csv()

    def test_happy_path_candidate(self):
        csv = _make_csv_bytes(
            ",2025-04-01,2025-04-01\n"
            "NAMES,09:00-09:45,10:00-10:45\n"
            "newcand1,Yes,No\n"
            "newcand2,No,Yes\n"
        )
        expected_slots = ["2025-04-01 09:00-09:45", "2025-04-01 10:00-10:45"]
        avail_map, new_ids = self._parse_add_csv(csv, expected_slots, entity_kind="candidate")

        assert new_ids == ["newcand1", "newcand2"]
        assert avail_map["newcand1"]["2025-04-01 09:00-09:45"] == 1
        assert avail_map["newcand1"]["2025-04-01 10:00-10:45"] == 0
        assert avail_map["newcand2"]["2025-04-01 09:00-09:45"] == 0
        assert avail_map["newcand2"]["2025-04-01 10:00-10:45"] == 1

    def test_happy_path_staff(self):
        # Staff CSV dates may include extra timestamp info (load_staff does .split()[0])
        csv = _make_csv_bytes(
            ",2025-04-01 00:00:00,2025-04-01 00:00:00\n"
            "NAMES,09:00-09:45,10:00-10:45\n"
            "newstaff1,Yes,Yes\n"
        )
        expected_slots = ["2025-04-01 09:00-09:45", "2025-04-01 10:00-10:45"]
        avail_map, new_ids = self._parse_add_csv(csv, expected_slots, entity_kind="staff")

        assert new_ids == ["newstaff1"]
        assert avail_map["newstaff1"]["2025-04-01 09:00-09:45"] == 1
        assert avail_map["newstaff1"]["2025-04-01 10:00-10:45"] == 1

    def test_mismatched_slots_raises(self):
        csv = _make_csv_bytes(
            ",2025-04-01\n"
            "NAMES,09:00-09:45\n"
            "cand1,Yes\n"
        )
        expected_slots = ["2025-04-01 09:00-09:45", "2025-04-01 10:00-10:45"]
        with pytest.raises(ValueError, match="do not match"):
            self._parse_add_csv(csv, expected_slots, entity_kind="candidate")

    def test_too_few_rows_raises(self):
        csv = _make_csv_bytes(
            ",2025-04-01\n"
            "NAMES,09:00-09:45\n"
        )
        expected_slots = ["2025-04-01 09:00-09:45"]
        with pytest.raises(ValueError, match="at least 3 rows"):
            self._parse_add_csv(csv, expected_slots, entity_kind="candidate")

    def test_empty_data_rows_raises(self):
        # Only blank entity IDs after header rows
        csv = _make_csv_bytes(
            ",2025-04-01\n"
            "NAMES,09:00-09:45\n"
            ",Yes\n"
        )
        expected_slots = ["2025-04-01 09:00-09:45"]
        with pytest.raises(ValueError, match="no data rows"):
            self._parse_add_csv(csv, expected_slots, entity_kind="candidate")


# ---------------------------------------------------------------------------
# 2. Solver respects pre-set availability (does not overwrite with all-available)
# ---------------------------------------------------------------------------

def test_solver_respects_preset_candidate_availability():
    """When ds['avail'] already has availability for a new candidate,
    the solver should NOT overwrite it with all-available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ds_obj = DataStore(config={"base_dir": tmpdir})

        time_slots = ["t1", "t2", "t3"]
        ds = {
            "candidates": ["c1", "c2_new"],  # c2_new pre-inserted by UI
            "time_slots": time_slots,
            "avail": {
                "c1": {"t1": 1, "t2": 1, "t3": 1},
                # c2_new is only available at t3
                "c2_new": {"t1": 0, "t2": 0, "t3": 1},
            },
            "staff": ["lead_a", "b"],
            "staff_avail": {
                "lead_a": {"t1": 1, "t2": 1, "t3": 1},
                "b": {"t1": 1, "t2": 1, "t3": 1},
            },
            "required_staff": {"c1": ["lead_a"]},
            "forbidden_pairs": [],
            "prev_schedule": {"c1": "t1"},
            "prev_staff_assignment": {"t1": ["lead_a", "b"]},
            "lead_ids": ["lead_a"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": ds,
            "lead_ids": ["lead_a"],
        }

        schedule, meta = reschedule(
            data_store=ds_obj,
            change_event={"add_candidate": ["c2_new"]},
            params=params,
        )

        assert "c2_new" in schedule
        # c2_new should only be in t3 (the only available slot)
        assert schedule["c2_new"] == "t3", (
            f"Expected c2_new at t3 (only available slot), got {schedule['c2_new']}"
        )


def test_solver_respects_preset_staff_availability():
    """When ds['staff_avail'] already has availability for a new staff member,
    the solver should NOT overwrite it with all-available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ds_obj = DataStore(config={"base_dir": tmpdir})

        time_slots = ["t1", "t2", "t3"]
        ds = {
            "candidates": ["c1"],
            "time_slots": time_slots,
            "avail": {
                "c1": {"t1": 1, "t2": 1, "t3": 1},
            },
            "staff": ["lead_a", "new_staff"],  # new_staff pre-inserted by UI
            "staff_avail": {
                "lead_a": {"t1": 1, "t2": 1, "t3": 1},
                # new_staff is only available at t2
                "new_staff": {"t1": 0, "t2": 1, "t3": 0},
            },
            "required_staff": {"c1": ["lead_a"]},
            "forbidden_pairs": [],
            "prev_schedule": {"c1": "t1"},
            "prev_staff_assignment": {"t1": ["lead_a"]},
            "lead_ids": ["lead_a"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": ds,
            "lead_ids": ["lead_a"],
        }

        schedule, meta = reschedule(
            data_store=ds_obj,
            change_event={"staff_added": ["new_staff"]},
            params=params,
        )

        # Verify new_staff is only assigned where available
        staff_assign = meta.get("staff_assignment", {})
        for slot, assigned_staff in staff_assign.items():
            if "new_staff" in assigned_staff:
                assert slot == "t2", (
                    f"new_staff should only be assigned at t2, found at {slot}"
                )
