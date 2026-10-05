import json
import os
import tempfile

from data_models.store import DataStore


def test_save_and_get_schedule(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    ds = DataStore(config={"base_dir": str(base)})

    mapping = {"cand1": "2025-04-01 09:00-09:45", "cand2": "2025-04-01 09:45-10:30"}
    sid = ds.save_schedule(mapping)
    assert isinstance(sid, str) and sid.startswith("sch-")

    loaded = ds.get_schedule(sid)
    assert loaded == mapping


def test_append_and_iter_events(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    ds = DataStore(config={"base_dir": str(base)})

    e1 = {"type": "staff_unavailable", "staff": "lead1"}
    e2 = {"type": "candidate_withdrawn", "candidate": "cand2"}

    id1 = ds.append_event(e1)
    id2 = ds.append_event(e2)

    events = list(ds.iter_change_events())
    # Should include our two events
    types = {ev.get("event", {}).get("type") for ev in events}
    assert "staff_unavailable" in types and "candidate_withdrawn" in types


def test_sequence_counter_restored_on_reopen(tmp_path):
    """DataStore opened against an existing run_id must continue seq from the
    highest seq already on disk, not reset to 0."""
    base = tmp_path / "data"
    base.mkdir()

    # First instance: save three schedules
    ds1 = DataStore(config={"base_dir": str(base)})
    run_id = ds1.run_id
    ds1.save_schedule({"c1": "t1"})
    ds1.save_schedule({"c1": "t2"})
    ds1.save_schedule({"c1": "t3"})
    # seq should now be 3
    assert ds1._schedule_seq == 3

    # Second instance opening the SAME run_id (simulates session resume)
    ds2 = DataStore(config={"base_dir": str(base), "run_id": run_id})
    # Must detect existing max seq=3 and start from there
    assert ds2._schedule_seq == 3

    # Saving a new schedule must produce seq=4, not seq=1
    sid4 = ds2.save_schedule({"c1": "t4"})
    payloads = list(ds2.list_schedules())
    new_payload = next(p for p in payloads if p["id"] == sid4)
    assert new_payload["seq"] == 4, f"Expected seq=4 but got seq={new_payload['seq']}"


def test_event_seq_counter_restored_on_reopen(tmp_path):
    """Same seq-restoration guarantee for event files."""
    base = tmp_path / "data"
    base.mkdir()

    ds1 = DataStore(config={"base_dir": str(base)})
    run_id = ds1.run_id
    ds1.append_event({"type": "e1"})
    ds1.append_event({"type": "e2"})
    assert ds1._event_seq == 2

    ds2 = DataStore(config={"base_dir": str(base), "run_id": run_id})
    assert ds2._event_seq == 2

    ds2.append_event({"type": "e3"})
    events = list(ds2.iter_change_events())
    seqs = [ev.get("seq", 0) for ev in events]
    assert 3 in seqs, f"Expected seq=3 in events, got seqs: {seqs}"
