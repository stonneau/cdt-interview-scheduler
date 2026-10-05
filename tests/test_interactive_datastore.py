"""
Test that interactive reschedules persist to the same DataStore run_id directory.
"""
import pytest
import os
import json
from pathlib import Path
import tempfile
import shutil
from data_models.store import DataStore
from scheduler.solver import solve_initial_schedule, reschedule

def test_interactive_reschedule_same_run_id():
    """
    Test that when using interactive mode with persist=True, all schedules
    (initial and reschedules) go to the same run_id directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a minimal data store
        base_dir = Path(tmpdir)
        
        # Create DataStore object for persistence
        ds = DataStore(config={"base_dir": str(base_dir)})
        run_id_1 = ds.run_id
        
        # Minimal dataset
        data_dict = {
            "candidates": ["cand1", "cand2"],
            "time_slots": ["9:00", "10:00"],
            "avail": {
                "cand1": {"9:00": 1, "10:00": 1},
                "cand2": {"9:00": 1, "10:00": 1},
            },
            "staff": ["s1", "s2"],
            "staff_avail": {
                "s1": {"9:00": 1, "10:00": 1},
                "s2": {"9:00": 1, "10:00": 1},
            },
            "required_staff": {"cand1": "s1", "cand2": "s2"},
            "forbidden_pairs": [],
        }
        
        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "min_max",
            "staff_change_penalty_weight": 1,
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,  # Pass the in-memory data
        }
        
        # Initial schedule
        schedule1, meta1 = solve_initial_schedule(data_store=ds, params=params)
        assert schedule1, "Initial schedule should be produced"
        sid1 = meta1.get("saved_schedule_id")
        assert sid1, "Schedule should be saved"
        
        # Check that schedule was saved to the correct run_id directory
        schedule_path1 = base_dir / run_id_1 / "schedules" / f"{sid1}.json"
        assert schedule_path1.exists(), f"Schedule should exist at {schedule_path1}"
        
        # Count initial events
        initial_events = list(ds.iter_change_events())
        assert len(initial_events) > 0, "At least one event should be recorded"
        
        # Now reschedule using the same DataStore object with _data_store_dict override
        # This simulates what interactive mode does
        data_dict_for_reschedule = dict(data_dict)
        data_dict_for_reschedule["prev_schedule"] = schedule1
        data_dict_for_reschedule["prev_staff_assignment"] = meta1.get("staff_assignment", {})
        
        change_event = {
            "staff_unavailable": [("s1", "10:00")]
        }
        
        params_reschedule = dict(params)
        params_reschedule["_data_store_dict"] = data_dict_for_reschedule
        
        schedule2, meta2 = reschedule(data_store=ds, change_event=change_event, params=params_reschedule)
        assert schedule2, "Rescheduled schedule should be produced"
        sid2 = meta2.get("saved_schedule_id")
        assert sid2, "Rescheduled schedule should be saved"
        assert sid2 != sid1, "New schedule should have different ID"
        
        # Check that rescheduled schedule was ALSO saved to the SAME run_id directory
        schedule_path2 = base_dir / run_id_1 / "schedules" / f"{sid2}.json"
        assert schedule_path2.exists(), f"Rescheduled schedule should exist at {schedule_path2}"
        
        # Verify both schedules are in the same run_id directory
        assert schedule_path1.parent == schedule_path2.parent, \
            "Both schedules should be in the same directory"
        
        # Check that events were appended to the same run_id
        all_events = list(ds.iter_change_events())
        assert len(all_events) > len(initial_events), "New event should be appended"
        
        # Ensure no new run_id directories were created
        run_dirs = list(base_dir.glob("run-*"))
        assert len(run_dirs) == 1, f"Should have exactly 1 run directory, got {len(run_dirs)}"
        assert run_dirs[0].name == run_id_1, "The run directory should match the original run_id"


if __name__ == "__main__":
    test_interactive_reschedule_same_run_id()
    print("✓ Test passed: Interactive reschedules go to same run_id directory")
