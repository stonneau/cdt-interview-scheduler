"""
I mean to use this as a way of testing that the most basic stuff is held:
    - Candidates, Staff and Slots that are in final schedule exist.
    - Candidates are allocated to slots they are available in.
    - Staff are allocated to slots they are available in.
    - Every slot contains at least one Lead staff member.
    - Every slot contains exactly 2 staff members.
    - Every forbidden pair is respected.
    -  

"""
# Even though this should all be held by the model's design, 
# it is good practice to check externally at the end of the pipeline.


import unittest

from scheduler.model_builder import build_model
from eval.metrics import ScheduleMetrics
from ortools.sat.python import cp_model
from scheduler.solver import solve_initial_schedule

class TestBasics(unittest.TestCase):
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

    def test_exactly_two_staff(self):
        print("Running test_exactly_two_staff")
       
        data_store = {
                "candidates": self.candidates,
                "time_slots": self.time_slots,
                "avail": self.avail,
                "staff": self.staff,
                "staff_avail": self.staff_avail,
                "required_staff": self.required_staff,
                "forbidden_pairs": self.forbidden_pairs,
                "prev_schedule": None,
                "prev_staff_assignment": None,
        }
        params = {
        "min_staff_per_slot": 2,
        "fairness": "min_max",
        "staff_change_penalty_weight": None,
        "time_limit": 10,
        }



        _, metadata = solve_initial_schedule(data_store=data_store, params=params) 
        staff_assignment = metadata["staff_assignment"]
        for panel in dict.values(staff_assignment):
            self.assertEqual(len(panel), 2)
                
        
        
