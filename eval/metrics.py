from typing import Dict, List, Tuple, Optional
import numpy as np
from datetime import datetime
import re

class ScheduleMetrics:
    def __init__(
            self,
            schedule: Dict[str, str],
            prev_schedule: Optional[Dict[str, str]],
            staff_assignment: Dict[str, List[str]],
            time_slots: Optional[List[str]] = None,
            prev_staff_assignment: Optional[Dict[str, List[str]]] = None,
    ):
        self.schedule = schedule or {}  # {candidate: timeslot}
        self.prev_schedule = prev_schedule or {}
        self.staff_assignment = staff_assignment or {}  # {timeslot: [staff]}
        self.prev_staff_assignment = prev_staff_assignment or {}  # {timeslot: [staff]}

        if time_slots is None:
            # filter out None values which can appear when a candidate is unassigned
            ts = set(v for v in self.schedule.values() if v is not None)
            ts |= set(v for v in self.prev_schedule.values() if v is not None)
            ts |= set(k for k in self.staff_assignment.keys() if k is not None)
            self.time_slots = sorted(ts)
        else:
            self.time_slots = list(time_slots)

            # Precompute parsed start times for temporal metrics
        self._slot_start_cache: Dict[str, datetime] = {}
    def stability_metrics(self) -> Dict[str, float]:
        """
        Stability metrics comparing new schedule vs prev_schedule.
        """
        num_changed = self._count_changes()
        num_cand_changed = self._count_candidate_changes()
        num_staff_changed = self._count_staff_changes()
        total = max(1, len(self.prev_schedule))
        prop_changed = float(num_changed) / float(total) if total > 0 else 0.0
        return {
            "changed_assignments": float(num_changed),
            "num_changed_assignments": float(num_changed),
            "changed_candidate_assignments": float(num_cand_changed),
            "changed_staff_assignments": float(num_staff_changed),
            "prop_changed": prop_changed,
            "temporal_deviation_minutes": float(self._temporal_deviation()),
            "weighted_change_distance": float(self._weighted_change_distance()),
        }

    def robustness_metrics(self) -> Dict[str, float]:
        """
        Robustness metrics on the *new* schedule.

        NOTE: For fairness variance we expose both absolute and delta (if a
        previous staff_assignment is available via a separate metrics object).
        This method only looks at the loads implied by `self.staff_assignment`.
        """
        loads = self._staff_loads()
        gini = self._gini(list(loads.values())) if loads else 0.0
        max_load = float(max(loads.values())) if loads else 0.0
        min_load = float(min(loads.values())) if loads else 0.0
        median_load = float(np.median(list(loads.values()))) if loads else 0.0
        return {
            "staff_fairness_variance": float(self._staff_load_variance()),
            "staff_fairness_gini": float(gini),
            "staff_load_max": max_load,
            "staff_load_min": min_load,
            "staff_load_median": median_load,
            # Slack definition is intentionally simple for now; can be replaced
            # by slack-based approaches from the literature.
            "slack_utilisation": float(self._slack_utilisation()),
            "feasibility_ratio": float(self._feasibility_ratio()),
        }

    # ---------- Core measures ----------

    def _count_changes(self) -> int:
        """
        Count of total changes: candidates whose assigned slot changed plus
        staff (slot) assignment changes between prev and new schedule.
        """
        changed = self._count_candidate_changes()
        changed += self._count_staff_changes()
        return changed

    def _count_candidate_changes(self) -> int:
        """Count of candidates whose assigned slot changed."""
        if not self.prev_schedule:
            return 0
        changed = 0
        for c, new_t in self.schedule.items():
            old_t = self.prev_schedule.get(c)
            if old_t is not None and old_t != new_t:
                changed += 1
        return changed

    def _count_staff_changes(self) -> int:
        """Count of (staff, slot) pairs that differ between prev and new
        staff assignments."""
        if not self.prev_staff_assignment:
            return 0
        # Build sets of (staff, slot) pairs
        prev_pairs = set()
        for slot, staff_list in self.prev_staff_assignment.items():
            for s in staff_list:
                prev_pairs.add((s, slot))
        new_pairs = set()
        for slot, staff_list in self.staff_assignment.items():
            for s in staff_list:
                new_pairs.add((s, slot))
        # Symmetric difference = added + removed assignments
        return len(prev_pairs.symmetric_difference(new_pairs))

    def _temporal_deviation(self) -> float:
        """
        Sum of time differences between original and updated start times, in minutes.
        Only considers candidates present in both schedules and whose slot changed.
        """
        if not self.prev_schedule:
            return 0.0

        total_minutes = 0.0
        for c, new_t in self.schedule.items():
            old_t = self.prev_schedule.get(c)
            if old_t is None or old_t == new_t:
                continue
            try:
                dt_old = self._parse_slot_start(old_t)
                dt_new = self._parse_slot_start(new_t)
            except ValueError:
                # If parsing fails, fall back to 0 contribution for this candidate
                continue
            delta = abs((dt_new - dt_old).total_seconds()) / 60.0
            total_minutes += delta
        return total_minutes

    def _weighted_change_distance(self) -> float:
        """
        Weighted measure of how far each candidate moved.

        Current simple version:
        - Weight = 1 per candidate
        - Distance = temporal deviation in minutes

        This is intentionally factored out so that, later, candidate-specific
        weights or non-linear penalties can be plugged in without changing
        callers.
        """
        # For now, reuse the temporal deviation definition
        return self._temporal_deviation()

    def _staff_loads(self) -> Dict[str, int]:
        """
        Compute how many slots each staff member is assigned to in this schedule.
        """
        loads: Dict[str, int] = {}
        for staff_list in self.staff_assignment.values():
            for s in staff_list:
                loads[s] = loads.get(s, 0) + 1
        return loads

    def _staff_load_variance(self) -> float:
        """
        Degree to which workload balance is uneven across staff *in this schedule*.
        """
        loads = self._staff_loads()
        if not loads:
            return 0.0
        return float(np.var(list(loads.values())))

    def _gini(self, values: List[float]) -> float:
        """
        Compute Gini coefficient for a list of non-negative values.
        Returns 0 for empty or all-zero lists.
        """
        if not values:
            return 0.0
        arr = np.array(values, dtype=float)
        if np.all(arr == 0):
            return 0.0
        # Mean absolute difference approach
        arr = np.sort(arr)
        n = arr.size
        cumvals = np.cumsum(arr)
        sum_arr = cumvals[-1]
        # Gini formula
        index = np.arange(1, n + 1)
        gini = (2.0 * np.sum(index * arr) - (n + 1) * sum_arr) / (n * sum_arr)
        return float(gini)

    def _slack_utilisation(self) -> float:
        """
        Simple slack utilisation proxy.

        Assumptions (can be refined later to match slack-based approaches):
        - Each staff member has capacity = number of distinct timeslots.
        - Slack for staff s = capacity - load_s (capped at >= 0).
        - We interpret this metric *relative* to an implicit "perfectly empty"
          baseline where load_s = 0 for all s, i.e. initial_slack = capacity * |S|.
        - slack_used = initial_slack - current_slack

        So:
            slack_utilisation = slack_used / initial_slack  in [0,1]
        """
        loads = self._staff_loads()
        if not loads:
            return 0.0

        capacity = len(self.time_slots)
        if capacity <= 0:
            return 0.0

        staff_ids = list(loads.keys())
        initial_slack = capacity * len(staff_ids)
        current_slack = 0
        for s in staff_ids:
            load_s = loads[s]
            slack_s = max(0, capacity - load_s)
            current_slack += slack_s
        slack_used = max(0, initial_slack - current_slack)
        if initial_slack == 0:
            return 0.0
        return slack_used / initial_slack

    def _feasibility_ratio(self) -> float:
        """
        Proportion of high-level constraint families satisfied by this schedule.

        NOTE: This requires (or assumes) that the schedule provided was obtained
        from a feasible CP-SAT model. If you want to measure feasibility w.r.t.
        a *different* set of availabilities/constraints, you can extend this
        method to accept those as arguments.

        For now, we treat a schedule that is structurally valid as fully feasible:
        - Each candidate appears at most once.
        - Each slot has at most one candidate.
        """
        # Candidates at most once
        cand_seen = set()
        c1_ok = True
        for c, t in self.schedule.items():
            if c in cand_seen:
                c1_ok = False
                break
            cand_seen.add(c)

        # Slots at most one candidate
        slot_to_cand = {}
        c2_ok = True
        for c, t in self.schedule.items():
            if t in slot_to_cand and slot_to_cand[t] != c:
                c2_ok = False
                break
            slot_to_cand[t] = c

        families = [c1_ok, c2_ok]
        satisfied = sum(1 for ok in families if ok)
        total = len(families)
        return float(satisfied) / float(total) if total > 0 else 1.0

    def _buffer_slots(self) -> int:
        """Count timeslots with no candidate assigned.

        Buffer (empty) slots represent available capacity for future
        insertions without displacing existing assignments.

        .. note::

           This value equals ``len(time_slots) - len(candidates)`` for
           every strategy (all strategies must assign every candidate to
           exactly one slot).  It is kept for informational purposes but
           does **not** differentiate strategies.  To evaluate
           ``slack_based``'s resilience advantage, use the *infeasibility
           rate* under high-noise conditions instead.
        """
        occupied = set(self.schedule.values())
        return sum(1 for t in self.time_slots if t not in occupied)

    # ---------- Helpers ----------

    _SLOT_RE = re.compile(
        r"""
        ^\s*
        (?P<date>\d{4}-\d{2}-\d{2})    # YYYY-MM-DD
        \s+
        (?P<start>\d{1,2}:\d{2})       # HH:MM
        -
        (?P<end>\d{1,2}:\d{2})         # HH:MM
        \s*$
        """,
        re.VERBOSE,
    )

    def _parse_slot_start(self, slot: str) -> datetime:
        """
        Parse the *start* datetime from a slot string like "2025-04-02 16:45-17:30".

        Raises ValueError if the format is not recognised.
        """
        if slot in self._slot_start_cache:
            return self._slot_start_cache[slot]

        m = self._SLOT_RE.match(slot)
        if not m:
            raise ValueError(f"Unrecognised slot format: {slot!r}")
        date_str = m.group("date")
        start_str = m.group("start")
        dt = datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M")
        self._slot_start_cache[slot] = dt
        return dt
