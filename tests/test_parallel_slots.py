"""
Tests for parallel interview slot support.

Validates that:
- Default behaviour (allow_parallel=False) keeps at most one candidate per slot.
- With allow_parallel=True, multiple candidates can be at the same physical time.
- Staff exclusivity: a staff member cannot attend two parallel instances
  at the same base time.
- Required staff constraints are respected with parallel slots.
- The _expand_parallel_slots helper produces the expected output.
- All strategies produce feasible solutions with parallel enabled.
"""

import copy
import unittest

from scheduler.solver import solve_initial_schedule, _expand_parallel_slots
from scheduler import strategies


# ---------------------------------------------------------------------------
# Shared synthetic data
# ---------------------------------------------------------------------------

def _make_data_store(num_candidates=4, num_staff=6, num_slots=3):
    """Create a small data store where parallel scheduling is useful.

    With 4 candidates but only 3 base slots, the problem is infeasible
    without parallelism (at most one candidate per slot). Enabling
    allow_parallel with max_parallel>=2 should make it feasible.
    """
    candidates = [f"c{i}" for i in range(1, num_candidates + 1)]
    time_slots = [f"t{i}" for i in range(1, num_slots + 1)]
    staff = [f"s{i}" for i in range(1, num_staff + 1)]

    avail = {c: {t: 1 for t in time_slots} for c in candidates}
    staff_avail = {s: {t: 1 for t in time_slots} for s in staff}
    required_staff = {}
    forbidden_pairs = []

    return {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
        "prev_schedule": None,
        "prev_staff_assignment": None,
    }


# ---------------------------------------------------------------------------
# Unit tests for the helper
# ---------------------------------------------------------------------------

class TestExpandParallelSlots(unittest.TestCase):
    """Unit tests for _expand_parallel_slots."""

    def test_basic_expansion(self):
        ts = ["t1", "t2"]
        avail = {"c1": {"t1": 1, "t2": 0}}
        staff_avail = {"s1": {"t1": 1, "t2": 1}}

        exp_ts, exp_av, exp_sa, groups = _expand_parallel_slots(ts, avail, staff_avail, 2)

        # Should have 4 slots: t1, t1.2, t2, t2.2
        self.assertEqual(len(exp_ts), 4)
        self.assertIn("t1", exp_ts)
        self.assertIn("t1.2", exp_ts)
        self.assertIn("t2", exp_ts)
        self.assertIn("t2.2", exp_ts)

        # Groups
        self.assertEqual(groups["t1"], ["t1", "t1.2"])
        self.assertEqual(groups["t2"], ["t2", "t2.2"])

        # Availability replicated
        self.assertEqual(exp_av["c1"]["t1"], 1)
        self.assertEqual(exp_av["c1"]["t1.2"], 1)
        self.assertEqual(exp_av["c1"]["t2"], 0)
        self.assertEqual(exp_av["c1"]["t2.2"], 0)

        self.assertEqual(exp_sa["s1"]["t1"], 1)
        self.assertEqual(exp_sa["s1"]["t1.2"], 1)

    def test_max_parallel_3(self):
        ts = ["t1"]
        avail = {"c1": {"t1": 1}}
        staff_avail = {"s1": {"t1": 1}}

        exp_ts, _, _, groups = _expand_parallel_slots(ts, avail, staff_avail, 3)

        self.assertEqual(exp_ts, ["t1", "t1.2", "t1.3"])
        self.assertEqual(groups["t1"], ["t1", "t1.2", "t1.3"])

    def test_no_expansion_when_max_1(self):
        """max_parallel=1 should not be passed, but if it is nothing changes."""
        ts = ["t1", "t2"]
        avail = {"c1": {"t1": 1, "t2": 1}}
        staff_avail = {}

        exp_ts, _, _, groups = _expand_parallel_slots(ts, avail, staff_avail, 1)

        # No extra slots added
        self.assertEqual(exp_ts, ["t1", "t2"])
        self.assertEqual(groups["t1"], ["t1"])
        self.assertEqual(groups["t2"], ["t2"])


# ---------------------------------------------------------------------------
# Integration tests with the solver
# ---------------------------------------------------------------------------

class TestParallelSolverIntegration(unittest.TestCase):

    def test_default_no_parallel(self):
        """Without allow_parallel, at most one candidate per base slot."""
        ds = _make_data_store(num_candidates=3, num_slots=3)
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": False,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"))

        # All 3 candidates placed in distinct slots
        assigned = list(schedule.values())
        self.assertEqual(len(assigned), len(set(assigned)))

    def test_infeasible_without_parallel(self):
        """4 candidates + 3 slots → infeasible without parallel."""
        ds = _make_data_store(num_candidates=4, num_slots=3)
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": False,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertEqual(meta["status"], "INFEASIBLE")

    def test_feasible_with_parallel(self):
        """4 candidates + 3 slots + allow_parallel → feasible."""
        ds = _make_data_store(num_candidates=4, num_slots=3, num_staff=8)
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": True,
            "max_parallel": 2,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"))
        # All 4 candidates assigned
        self.assertEqual(len(schedule), 4)
        self.assertTrue(all(v is not None for v in schedule.values()))

    def test_staff_exclusivity_across_parallel_slots(self):
        """A staff member must not appear in two parallel slots at the same time."""
        ds = _make_data_store(num_candidates=4, num_slots=3, num_staff=8)
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": True,
            "max_parallel": 2,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"))

        staff_assignment = meta.get("staff_assignment", {})

        # Build slot→base mapping
        _, _, _, groups = _expand_parallel_slots(
            ds["time_slots"], ds["avail"], ds["staff_avail"], 2
        )
        base_for_slot = {}
        for base, members in groups.items():
            for m in members:
                base_for_slot[m] = base

        # For each base time, collect all staff assigned across parallel slots
        from collections import defaultdict
        base_staff = defaultdict(list)
        for slot, staff_list in staff_assignment.items():
            base = base_for_slot.get(slot, slot)
            base_staff[base].extend(staff_list)

        # No staff member should appear more than once per base time
        for base, all_staff in base_staff.items():
            self.assertEqual(
                len(all_staff),
                len(set(all_staff)),
                f"Staff double-booked at base time {base}: {all_staff}",
            )

    def test_required_staff_with_parallel(self):
        """Required-staff constraints must be honoured with parallel enabled."""
        ds = _make_data_store(num_candidates=4, num_slots=3, num_staff=8)
        # c1 requires s1, c2 requires s2
        ds["required_staff"] = {"c1": ["s1"], "c2": ["s2"]}
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": True,
            "max_parallel": 2,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"))

        staff_assignment = meta.get("staff_assignment", {})
        # s1 must attend slot of c1
        slot_c1 = schedule["c1"]
        self.assertIn("s1", staff_assignment.get(slot_c1, []))
        # s2 must attend slot of c2
        slot_c2 = schedule["c2"]
        self.assertIn("s2", staff_assignment.get(slot_c2, []))

    def test_no_unnecessary_suffix_slots(self):
        """Suffix (.2) slots should only appear when parallelism is needed.

        With 3 candidates and 3 base slots there is enough room; the solver
        should prefer base slots and never assign anyone to a .2 slot.
        """
        ds = _make_data_store(num_candidates=3, num_slots=3, num_staff=6)
        params = {
            "min_staff_per_slot": 2,
            "fairness": "none",
            "time_limit": 5,
            "allow_parallel": True,
            "max_parallel": 2,
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"))

        # None of the assigned slots should have a .2 suffix
        for c, t in schedule.items():
            self.assertFalse(
                t.endswith(".2"),
                f"Candidate {c} unnecessarily assigned to suffix slot {t}",
            )

class TestParallelStrategies(unittest.TestCase):
    """Verify that all strategies produce feasible results with parallel."""

    def _run_strategy(self, strategy_name):
        ds = _make_data_store(num_candidates=4, num_slots=3, num_staff=8)
        # Pre-expand parallel slots (as reschedule() does before calling strategy)
        from scheduler.solver import _expand_parallel_slots
        exp_ts, exp_av, exp_sa, groups = _expand_parallel_slots(
            ds["time_slots"], ds["avail"], ds["staff_avail"], 2
        )
        ds["time_slots"] = exp_ts
        ds["avail"] = exp_av
        ds["staff_avail"] = exp_sa
        ds["parallel_slot_groups"] = groups

        # Provide a prev_schedule for strategies that need one
        ds["prev_schedule"] = {"c1": "t1", "c2": "t2", "c3": "t3"}
        ds["prev_staff_assignment"] = {
            "t1": ["s1", "s2"],
            "t2": ["s3", "s4"],
            "t3": ["s5", "s6"],
        }

        params = {"min_staff_per_slot": 2, "time_limit": 5}
        strategy_fn = strategies.get_strategy(strategy_name)
        schedule, meta = strategy_fn(ds, {}, params)
        self.assertIn(meta["status"], ("OPTIMAL", "FEASIBLE"),
                       f"Strategy {strategy_name} not feasible: {meta['status']}")
        return schedule, meta

    def test_change_penalty(self):
        self._run_strategy("change_penalty")

    def test_full(self):
        self._run_strategy("full")

    def test_local_repair(self):
        self._run_strategy("local_repair")

    def test_greedy_least_loaded(self):
        self._run_strategy("greedy_least_loaded")


if __name__ == "__main__":
    unittest.main()
