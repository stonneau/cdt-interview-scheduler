from pathlib import Path

from eval.harness import run_demo_small


def test_run_demo_small_saves(tmp_path):
    out_base = tmp_path / "demo_out"
    out_base.mkdir(parents=True)

    ds = run_demo_small(random_seed=1234, base_dir=str(out_base), persist=True)

    # With the new nested structure, schedules are under {base_dir}/{run_id}/schedules
    schedules_dir = ds.schedules_dir
    events_dir = ds.events_dir

    # Ensure at least one schedule and one event were saved
    sched_files = list(schedules_dir.glob("*.json"))
    evt_files = list(events_dir.glob("*.json"))

    assert len(sched_files) >= 1
    assert len(evt_files) >= 1
