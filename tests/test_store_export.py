import json
from pathlib import Path

from data_models.store import DataStore


def test_export_schedule_as_prev_csv(tmp_path):
    # Prepare a DataStore rooted at a temporary directory
    base = tmp_path / "data"
    ds = DataStore(config={"base_dir": str(base)})

    # Create a simple schedule and staff_assignment metadata
    schedule = {"cand1": "2026-02-02 09:00", "cand2": "2026-02-02 09:45"}
    staff_assignment = {
        "2026-02-02 09:00": ["lead1", "panel1"],
        "2026-02-02 09:45": ["lead2", "panel2"],
    }
    metadata = {"staff_assignment": staff_assignment}

    sid = ds.save_schedule(schedule=schedule, metadata=metadata)

    # Export to CSV
    out_csv = tmp_path / "prev_schedule_out.csv"
    out_path = ds.export_schedule_as_prev_csv(sid, str(out_csv))

    assert Path(out_path).exists()

    # Read and validate CSV contents
    text = out_csv.read_text(encoding="utf-8").strip().splitlines()
    # Header + two rows
    assert len(text) == 3
    header = text[0].split(",")
    assert header == ["candidate_id", "timeslot_id", "staff_ids"]

    rows = [r.split(",") for r in text[1:]]
    # Convert staff_ids back to semicolon separated and compare
    row_map = {r[0].strip(): (r[1].strip(), r[2].strip()) for r in rows}
    assert row_map["cand1"][0] == "2026-02-02 09:00"
    assert row_map["cand1"][1] == "lead1;panel1"
    assert row_map["cand2"][1] == "lead2;panel2"
