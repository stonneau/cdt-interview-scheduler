import os
import tempfile
import textwrap
import unittest

from data_models.loaders import (
    load_prev_schedule_from_csv,
    load_availability_objects_from_csv,
    load_staff_objects_from_csv,
)
from data_models.models import ScheduleAssignment


class TestPrevScheduleLoader(unittest.TestCase):
    def _write_temp_csv(self, content: str) -> str:
        """Helper to write a temp CSV and return its path."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(content).lstrip())
        return path

    def test_load_prev_schedule_happy_path(self):
        csv_path = self._write_temp_csv(
            """
            candidate_id,timeslot_id,staff_ids
            cand1,2025-04-01 09:00-09:45,"Staff A;Staff B"
            cand2,2025-04-01 09:45-10:30,"Staff C;Staff D"
            """
        )
        try:
            mapping, prev_staff = load_prev_schedule_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(
            mapping,
            {
                "cand1": "2025-04-01 09:00-09:45",
                "cand2": "2025-04-01 09:45-10:30",
            },
        )
        self.assertEqual(
            prev_staff,
            {
                "2025-04-01 09:00-09:45": ["Staff A", "Staff B"],
                "2025-04-01 09:45-10:30": ["Staff C", "Staff D"],
            },
        )

    def test_load_prev_schedule_missing_columns_raises(self):
        csv_path = self._write_temp_csv(
            """
            candidate_id,timeslot_id
            cand1,2025-04-01 09:00-09:45
            """
        )
        try:
            with self.assertRaises(ValueError):
                load_prev_schedule_from_csv(csv_path)
        finally:
            os.remove(csv_path)

    def test_load_prev_schedule_duplicate_candidate_raises(self):
        csv_path = self._write_temp_csv(
            """
            candidate_id,timeslot_id,staff_ids
            cand1,2025-04-01 09:00-09:45,"Staff A;Staff B"
            cand1,2025-04-01 09:45-10:30,"Staff C;Staff D"
            """
        )
        try:
            with self.assertRaises(ValueError):
                load_prev_schedule_from_csv(csv_path)
        finally:
            os.remove(csv_path)

    def test_load_prev_schedule_empty_staff_ids_raises(self):
        csv_path = self._write_temp_csv(
            """
            candidate_id,timeslot_id,staff_ids
            cand1,2025-04-01 09:00-09:45,
            """
        )
        try:
            with self.assertRaises(ValueError):
                load_prev_schedule_from_csv(csv_path)
        finally:
            os.remove(csv_path)


class TestAvailabilityAndStaffLoadersSmoke(unittest.TestCase):
    """
    Very small smoke tests that loaders can parse a minimal CSV structure.
    These use synthetic mini-CSVs rather than the big real data files.
    """

    def _write_temp_csv(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(content).lstrip())
        return path

    def test_load_availability_objects_from_csv_minimal(self):
        # 2 header rows + 1 candidate with one available slot
        csv_path = self._write_temp_csv(
            """
            ,2025-04-01
            NAMES,09:00-09:45
            cand_name,Yes
            """
        )
        try:
            candidates, slots = load_availability_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(slots), 1)
        # With use_real_names=True (default), the CSV name is used
        self.assertEqual(candidates[0].id, "cand_name")
        self.assertTrue(candidates[0].is_available(slots[0]))

    def test_load_availability_real_names(self):
        """Real names from column 0 are used as candidate IDs by default."""
        csv_path = self._write_temp_csv(
            """\
,2025-04-01,2025-04-01
,9,9.45
Alice Smith,Yes,No
Bob Jones,No,Yes
"""
        )
        try:
            candidates, slots = load_availability_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual([c.id for c in candidates], ["Alice Smith", "Bob Jones"])
        self.assertEqual(slots, ["2025-04-01 09:00", "2025-04-01 09:45"])
        self.assertTrue(candidates[0].is_available(slots[0]))
        self.assertFalse(candidates[0].is_available(slots[1]))

    def test_load_availability_anonymous_names(self):
        """use_real_names=False falls back to cand1, cand2, …"""
        csv_path = self._write_temp_csv(
            """\
,2025-04-01
,9
Alice,Yes
"""
        )
        try:
            candidates, _ = load_availability_objects_from_csv(
                csv_path, use_real_names=False,
            )
        finally:
            os.remove(csv_path)

        self.assertEqual(candidates[0].id, "cand1")

    def test_load_availability_empty_name_falls_back(self):
        """Empty name column (like last_year applicants) falls back to candN."""
        csv_path = self._write_temp_csv(
            """\
,2025-04-01
,9
,Yes
"""
        )
        try:
            candidates, _ = load_availability_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(candidates[0].id, "cand1")

    def test_if_needed_treated_as_available(self):
        """'If needed' is treated as not available (0) for both candidates and staff."""
        csv_path = self._write_temp_csv(
            """\
,2025-04-01,2025-04-01,2025-04-01,2025-04-01
,9,9.45,10.3,11
person,Yes,If needed,No,
"""
        )
        try:
            candidates, slots = load_availability_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        c = candidates[0]
        self.assertEqual(c.availability[slots[0]], 1, "Yes → 1")
        self.assertEqual(c.availability[slots[1]], 0, "If needed → 0")
        self.assertEqual(c.availability[slots[2]], 0, "No → 0")
        self.assertEqual(c.availability[slots[3]], 0, "empty → 0")

    def test_if_needed_staff(self):
        """'If needed' is treated as not available for staff too."""
        csv_path = self._write_temp_csv(
            """\
,2025-04-01
,9
staffA,If needed
"""
        )
        try:
            staff_objs, slots = load_staff_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(staff_objs[0].availability[slots[0]], 0)

    def test_decimal_slot_normalisation(self):
        """Slot labels '10.30' and '10.3' both normalise to '10:30'."""
        from data_models.loaders import _normalize_slot_label
        self.assertEqual(_normalize_slot_label("10.30"), "10:30")
        self.assertEqual(_normalize_slot_label("10.3"), "10:30")
        self.assertEqual(_normalize_slot_label("9"), "09:00")
        self.assertEqual(_normalize_slot_label("9.45"), "09:45")
        self.assertEqual(_normalize_slot_label("1"), "01:00")
        self.assertEqual(_normalize_slot_label("1.45"), "01:45")
        # Non-numeric labels pass through unchanged
        self.assertEqual(_normalize_slot_label("9-09:45"), "9-09:45")

    def test_start_time_slot_format(self):
        """Start-time-only slot labels (new format) are converted to HH:MM."""
        csv_path = self._write_temp_csv(
            """\
,2026-03-11,2026-03-11
,9,9.45
person,Yes,No
"""
        )
        try:
            candidates, slots = load_availability_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(slots, ["2026-03-11 09:00", "2026-03-11 09:45"])
        self.assertTrue(candidates[0].is_available(slots[0]))

    def test_load_staff_objects_from_csv_minimal(self):
        # 2 header rows + 1 staff with one available slot
        csv_path = self._write_temp_csv(
            """
            ,2025-04-01 09:00-09:45
            NAMES,09:00-09:45
            staff1,Yes
            """
        )
        try:
            staff_objs, slots = load_staff_objects_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(len(staff_objs), 1)
        self.assertEqual(len(slots), 1)
        self.assertTrue(staff_objs[0].can_attend(slots[0]))


class TestForbiddenPairs(unittest.TestCase):
    """Tests for forbidden candidate-staff pair loading and parsing."""

    def _write_temp_csv(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(content).lstrip())
        return path

    def test_load_forbidden_pairs_csv(self):
        from data_models.loaders import load_forbidden_pairs_from_csv
        csv_path = self._write_temp_csv(
            """\
candidate_id,staff_id
Alice,Prof X
Bob,Prof Y
"""
        )
        try:
            pairs = load_forbidden_pairs_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(pairs, {("Alice", "Prof X"), ("Bob", "Prof Y")})

    def test_load_forbidden_pairs_csv_skips_nan(self):
        from data_models.loaders import load_forbidden_pairs_from_csv
        csv_path = self._write_temp_csv(
            """\
candidate_id,staff_id
Alice,Prof X
,Prof Y
Bob,
"""
        )
        try:
            pairs = load_forbidden_pairs_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        self.assertEqual(pairs, {("Alice", "Prof X")})

    def test_load_forbidden_pairs_csv_missing_columns(self):
        from data_models.loaders import load_forbidden_pairs_from_csv
        csv_path = self._write_temp_csv(
            """\
candidate,staff
Alice,Prof X
"""
        )
        try:
            with self.assertRaises(ValueError):
                load_forbidden_pairs_from_csv(csv_path)
        finally:
            os.remove(csv_path)

    def test_parse_forbidden_pairs_inline(self):
        from data_models.loaders import parse_forbidden_pairs_inline
        result = parse_forbidden_pairs_inline("Alice:Prof X, Bob:Prof Y")
        self.assertEqual(result, {("Alice", "Prof X"), ("Bob", "Prof Y")})

    def test_parse_forbidden_pairs_inline_empty(self):
        from data_models.loaders import parse_forbidden_pairs_inline
        self.assertEqual(parse_forbidden_pairs_inline(""), set())
        self.assertEqual(parse_forbidden_pairs_inline("  "), set())

    def test_parse_forbidden_pairs_inline_whitespace(self):
        from data_models.loaders import parse_forbidden_pairs_inline
        result = parse_forbidden_pairs_inline("  Alice : Prof X ,  Bob : Prof Y  ")
        self.assertEqual(result, {("Alice", "Prof X"), ("Bob", "Prof Y")})

    def test_objects_to_solver_with_forbidden_pairs(self):
        from data_models.loaders import objects_to_solver_inputs_from_models
        from data_models.models import Candidate, Staff
        cand = Candidate(id="cand1")
        staff_obj = Staff(id="staff1")
        fp = {("cand1", "staff1")}
        _, _, _, _, _, result_fp = objects_to_solver_inputs_from_models(
            [cand], [staff_obj], forbidden_pairs=fp,
        )
        self.assertEqual(result_fp, {("cand1", "staff1")})

    def test_objects_to_solver_preserves_all_forbidden_pairs(self):
        """All forbidden pairs are preserved — including those referencing
        candidates or staff not yet present — so they persist for future
        staged changes."""
        from data_models.loaders import objects_to_solver_inputs_from_models
        from data_models.models import Candidate, Staff
        cand = Candidate(id="cand1")
        staff_obj = Staff(id="staff1")
        fp = {("cand1", "staff1"), ("cand1", "ghost_staff"), ("ghost_cand", "staff1")}
        _, _, _, _, _, result_fp = objects_to_solver_inputs_from_models(
            [cand], [staff_obj], forbidden_pairs=fp,
        )
        self.assertEqual(result_fp, fp)

    def test_load_forbidden_pairs_real_csv_format(self):
        """Real-data CSV format with Surname, First name(s), Potential Supervisors."""
        from data_models.loaders import load_forbidden_pairs_from_csv
        csv_path = self._write_temp_csv(
            '''\
Applicant,,,Comments,,Interview,
Surname,First name(s),Potential Supervisors,,,,
Fenwick,Maya,Nora Whitlock,,,,
Marlow,Theo,"Idris Calder, Felix Ashworth",,,,
Harlow,Jonas Peter Wren,,,,,
'''
        )
        try:
            pairs = load_forbidden_pairs_from_csv(csv_path)
        finally:
            os.remove(csv_path)

        expected = {
            ("Maya Fenwick", "Nora Whitlock"),
            ("Theo Marlow", "Idris Calder"),
            ("Theo Marlow", "Felix Ashworth"),
        }
        self.assertEqual(pairs, expected)

    def test_load_forbidden_pairs_real_csv_file(self):
        """Test loading the actual real-data ForbiddenPairs.csv file."""
        from data_models.loaders import load_forbidden_pairs_from_csv
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "actual_run_this_year", "real_data", "ForbiddenPairs.csv",
        )
        if not os.path.exists(csv_path):
            self.skipTest("Real data file not available")
        pairs = load_forbidden_pairs_from_csv(csv_path)
        # Should produce non-empty pairs
        self.assertGreater(len(pairs), 0)
        # Spot-check a known pair
        self.assertIn(("Maya Fenwick", "Nora Whitlock"), pairs)
        self.assertIn(("Theo Marlow", "Idris Calder"), pairs)
        self.assertIn(("Theo Marlow", "Felix Ashworth"), pairs)
        # Candidates with no supervisors should NOT produce any pair
        harlow_pairs = {(c, s) for c, s in pairs if "Harlow" in c}
        self.assertEqual(harlow_pairs, set(), "Harlow has no supervisors → no pairs")



if __name__ == "__main__":
    unittest.main()
