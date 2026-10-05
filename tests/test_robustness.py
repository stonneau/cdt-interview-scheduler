# TODO: this whole test needs to be done with native solver and not build its own model
import unittest

from scheduler.model_builder import build_model
from eval.metrics import ScheduleMetrics
from ortools.sat.python import cp_model

class TestScheduleRobustness(unittest.TestCase):
    def setUp(self):
        # Small synthetic instance for deterministic testing
        self.candidates = ["c1", "c2", "c3","c4","c5","c6","c7","c8","c9","c10","c11"]
        self.time_slots = [
            "2025-04-01 09:00-09:45",
            "2025-04-01 09:45-10:30",
            "2025-04-01 10:30-11:15",
            "2025-04-01 11:15-12:00",
            "2025-04-02 09:00-09:45",
            "2025-04-02 09:45-10:30",
            "2025-04-02 10:30-11:15",
            "2025-04-02 11:15-12:00",
            "2025-04-03 09:00-09:45",
            "2025-04-03 09:45-10:30",
            "2025-04-03 10:30-11:15",
            "2025-04-03 11:15-12:00",
            "2025-04-04 09:00-09:45",
            "2025-04-04 09:45-10:30",
            "2025-04-04 10:30-11:15",
            "2025-04-04 11:15-12:00",
        ]
        self.staff = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"]

        # Everyone can attend any slot initially
        self.avail = {c: {t: 1 for t in self.time_slots} for c in self.candidates}
        self.staff_avail = {s: {t: 1 for t in self.time_slots} for s in self.staff}

        # No special required staff / forbidden pairs for this synthetic test
        self.required_staff = {c: [] for c in self.candidates}
        self.forbidden_pairs = set()

    def _solve_and_extract(self, prev_schedule=None, fairness="min_max"):
        """
        Build and solve the CP-SAT model, then extract:
        - schedule: {candidate -> timeslot}
        - staff_assignment: {timeslot -> [staff]}
        """
        model, x, y = build_model(
            self.candidates,
            self.time_slots,
            self.avail,
            self.staff,
            self.staff_avail,
            self.required_staff,
            self.forbidden_pairs,
            prev_schedule=prev_schedule,
            fairness=fairness,
        )
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None

        schedule = {}
        staff_assignment = {t: [] for t in self.time_slots}
        for c in self.candidates:
            for t in self.time_slots:
                if solver.Value(x[c, t]):
                    schedule[c] = t
                    break

        for s in self.staff:
            for t in self.time_slots:
                if solver.Value(y[s, t]):
                    staff_assignment.setdefault(t, []).append(s)

        return schedule, staff_assignment

    def test_staff_unavailability_impact(self):
        """
        How schedule adapts to a single staff member losing availability on the
        earliest slot. We expect:
        - A valid new schedule is still found.
        - Not too many candidates are moved.
        - Temporal deviation is bounded.
        """
        print("Running test_staff_unavailability_impact...")

        # Baseline schedule
        base_schedule, base_staff_assignment = self._solve_and_extract()
        self.assertIsNotNone(base_schedule, "Baseline schedule should be solvable")

        base_metrics = ScheduleMetrics(base_schedule, None, base_staff_assignment, self.time_slots)

        # Perturbation: s1 becomes unavailable at the first slot
        perturbed_staff_avail = {
            s: slots.copy() for s, slots in self.staff_avail.items()
        }
        perturbed_staff_avail["s1"][self.time_slots[0]] = 0
        self.staff_avail = perturbed_staff_avail  # update instance

        # Re-schedule with minimal disturbance objective
        new_schedule, new_staff_assignment = self._solve_and_extract(
            prev_schedule=base_schedule, fairness="min_max"
        )
        self.assertIsNotNone(new_schedule, "Perturbed schedule should still be solvable")

        new_metrics = ScheduleMetrics(
            new_schedule,
            base_schedule,
            new_staff_assignment,
            self.time_slots,
        )

        stability = new_metrics.stability_metrics()
        robustness = new_metrics.robustness_metrics()

        # At most one candidate should move in this simple instance
        self.assertLessEqual(
            stability["changed_assignments"],
            1.0,
            "Too many assignments changed for single staff unavailability",
        )

        # Temporal deviation should be less than 2 slots (90 minutes)
        self.assertLessEqual(
            stability["temporal_deviation_minutes"],
            90.0,
            "Temporal deviation too large for small perturbation",
        )

        # Feasibility ratio should remain 1.0 for a model-derived schedule
        self.assertAlmostEqual(
            robustness["feasibility_ratio"],
            1.0,
            msg="Schedule should remain fully feasible after re-optimisation",
        )

        # Fairness variance after perturbation should not blow up
        # TODO: might just have this be in test_fairness_preservation()
        var_after = robustness["staff_fairness_variance"]
        var_before = base_metrics._staff_load_variance()
        self.assertLessEqual(
            abs(var_after - var_before),
            4.0,
            "Fairness variance changed too much after small perturbation",
        )

    def test_candidate_rescheduling_impact(self):
        """Test impact of forcing one candidate off their original slot."""
        # TODO: implement next – e.g. set avail[c1][base_slot] = 0, re-solve and
        # assert on metrics similarly to `test_staff_unavailability_impact`.
        print("Running test_candidate_rescheduling_impact...")

        base_schedule, base_staff_assignment = self._solve_and_extract()

        self.assertIsNotNone(base_schedule)

        # Remove candidate 1's availability slot
        target_cand = self.candidates[0]
        original_slot = base_schedule[target_cand]
        self.avail[target_cand][original_slot] = 0

        new_schedule, new_staff_assignment = self._solve_and_extract(prev_schedule=base_schedule)
        self.assertIsNotNone(new_schedule)

        metrics = ScheduleMetrics(new_schedule, base_schedule, new_staff_assignment, self.time_slots)
        stability = metrics.stability_metrics()

        self.assertNotEqual(new_schedule[target_cand], original_slot, "Candidate must move")
        self.assertGreaterEqual(stability["changed_assignments"], 1.0, "At least one change expected")
        self.assertLess(stability["changed_assignments"], 3.0, "Ripple effect shouldn't be total")

    def test_fairness_preservation(self):
        """Test if fairness is maintained (not drastically worsened) after random perturbations."""
        # TODO: implement a proper set of changes to stress test the algorithm
        print("Running test_fairness_preservation...")

        base_schedule, base_staff_assignment = self._solve_and_extract()
        base_metrics = ScheduleMetrics(base_schedule, None, base_staff_assignment, self.time_slots)
        base_variance = base_metrics.robustness_metrics()["staff_fairness_variance"]

        # simulate disruption
        self.staff_avail["s2"][self.time_slots[1]] = 0

        new_schedule, new_staff_assignment = self._solve_and_extract(prev_schedule=base_schedule)
        new_metrics = ScheduleMetrics(new_schedule, base_schedule, new_staff_assignment, self.time_slots)
        new_variance = new_metrics.robustness_metrics()["staff_fairness_variance"]

        # Might worse but 5 for now for synthetic data as a threshold
        self.assertLess(abs(new_variance - base_variance), 5.0)

    def test_staff_change_penalty_weight_smoke(self):
        """
        Smoke test: providing prev_staff_assignment and a non-zero
        staff_change_penalty_weight should still yield a feasible model.
        """
        # Simple baseline: everyone available everywhere
        prev_schedule = {
            c: self.time_slots[0] for c in self.candidates
        }
        # Previous staff assignment: all staff in first slot
        prev_staff_assignment = {
            self.time_slots[0]: list(self.staff)
        }

        model, x, y = build_model(
            self.candidates,
            self.time_slots,
            self.avail,
            self.staff,
            self.staff_avail,
            self.required_staff,
            self.forbidden_pairs,
            prev_schedule=prev_schedule,
            prev_staff_assignment=prev_staff_assignment,
            fairness="none",
            staff_change_penalty_weight=5,
        )

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        self.assertIn(
            status,
            (cp_model.OPTIMAL, cp_model.FEASIBLE),
            "Model with staff_change_penalty_weight should be solvable",
        )


        
