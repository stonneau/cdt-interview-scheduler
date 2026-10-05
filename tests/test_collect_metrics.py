"""
Tests for metrics collection module.
"""
import pytest
from pathlib import Path
from eval.collect_metrics import collect_metrics_for_run, collect_and_save_metrics
from eval.experiments.demo_small import run_generated_demo
import tempfile


def test_collect_metrics_from_run():
    """Test collecting metrics from a generated run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate a small synthetic run
        ds = run_generated_demo(
            random_seed=42,
            base_dir=tmpdir,
            persist=True,
            num_candidates=3,
            num_staff=2,
            num_days=1,
            slots_per_day=2,
            noise_type="staff_unavailable",
            noise_num_people=1,
        )
        
        # Collect metrics
        rows = collect_metrics_for_run(base_dir=tmpdir, run_id=ds.run_id)
        
        # Should have 6 rows (1 change event × 6 strategies)
        assert len(rows) == 6
        
        # Check required columns
        required_cols = {
            "iteration", "strategy", "change_event", 
            "changed_assignments", "changed_candidate_assignments",
            "changed_staff_assignments", "fairness_variance", "solve_time", "feasible"
        }
        for row in rows:
            assert required_cols.issubset(set(row.keys()))
        
        # Check expected values
        strategies = {row["strategy"] for row in rows}
        assert strategies == {
            "reschedule_from_scratch", "change_penalty", "local_repair",
            "fairness_weighted", "greedy_least_loaded", "variance_minimizing",
        }
        
        change_events = {row["change_event"] for row in rows}
        assert "staff_unavailable" in change_events


def test_save_metrics_csv():
    """Test saving metrics to CSV."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate a small synthetic run
        ds = run_generated_demo(
            random_seed=99,
            base_dir=tmpdir,
            persist=True,
            num_candidates=3,
            num_staff=2,
            num_days=1,
            slots_per_day=2,
        )
        
        # Collect and save
        csv_path = collect_and_save_metrics(base_dir=tmpdir, run_id=ds.run_id)
        
        # Verify CSV file exists
        assert csv_path.exists()
        
        # Read and verify CSV contents
        rows_read = []
        with open(csv_path) as f:
            import csv
            reader = csv.DictReader(f)
            rows_read = list(reader)
        
        # Should have 18 rows (3 change events × 6 strategies)
        assert len(rows_read) == 18
        
        # Verify header
        assert rows_read[0].get("strategy") is not None
        assert rows_read[0].get("change_event") is not None
