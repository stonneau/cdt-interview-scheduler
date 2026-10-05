"""
Tests for lead requirements:
  1. add_candidate change event inherits lead requirements.
  2. objects_to_solver_inputs_from_models respects explicit lead_ids.
"""
import pytest
from data_models.loaders import objects_to_solver_inputs_from_models
from data_models.models import Candidate, Staff
from scheduler.solver import reschedule
from data_models.store import DataStore
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# 1. objects_to_solver_inputs_from_models
# ---------------------------------------------------------------------------

def _make_candidates(*ids):
    cands = []
    for cid in ids:
        c = Candidate(id=cid)
        c.availability = {"slot1": 1, "slot2": 1}
        cands.append(c)
    return cands


def _make_staff(*ids):
    staff_objs = []
    for sid in ids:
        s = Staff(id=sid)
        s.availability = {"slot1": 1, "slot2": 1}
        s.is_lead = sid.startswith("lead")
        staff_objs.append(s)
    return staff_objs


def test_auto_detect_lead_by_name_prefix():
    """Default (lead_ids=None): staff starting with 'lead' are leads."""
    cands = _make_candidates("c1", "c2")
    staff = _make_staff("lead1", "panel1")
    _, _, _, _, req, _ = objects_to_solver_inputs_from_models(cands, staff, lead_ids=None)
    assert req["c1"] == ["lead1"]
    assert req["c2"] == ["lead1"]


def test_explicit_lead_ids_override():
    """Explicit lead_ids takes precedence over name-based detection."""
    cands = _make_candidates("c1")
    staff = _make_staff("lead1", "alice", "bob")
    # Override: alice and bob are leads, NOT lead1
    _, _, _, _, req, _ = objects_to_solver_inputs_from_models(cands, staff, lead_ids=["alice", "bob"])
    assert set(req["c1"]) == {"alice", "bob"}


def test_explicit_empty_lead_ids_disables_requirement():
    """Empty lead_ids list disables lead requirements entirely."""
    cands = _make_candidates("c1")
    staff = _make_staff("lead1", "panel1")
    _, _, _, _, req, _ = objects_to_solver_inputs_from_models(cands, staff, lead_ids=[])
    assert req["c1"] == []


def test_explicit_lead_ids_filtered_to_known_staff():
    """lead_ids entries that are not in staff are silently ignored."""
    cands = _make_candidates("c1")
    staff = _make_staff("alice")
    _, _, _, _, req, _ = objects_to_solver_inputs_from_models(cands, staff, lead_ids=["alice", "unknown_person"])
    assert req["c1"] == ["alice"]


def test_no_leads_in_staff():
    """When no staff qualify as leads (auto), required_staff has empty lists."""
    cands = _make_candidates("c1")
    staff = _make_staff("panel1", "panel2")  # none start with 'lead'
    _, _, _, _, req, _ = objects_to_solver_inputs_from_models(cands, staff, lead_ids=None)
    assert req["c1"] == []


# ---------------------------------------------------------------------------
# 2. add_candidate change event inherits lead requirements
# ---------------------------------------------------------------------------

def test_add_candidate_inherits_lead_requirements():
    """Newly added candidates must have the same lead requirements as existing ones."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["cand1"],
            "time_slots": ["2025-04-01 09:00-09:45", "2025-04-01 09:45-10:30"],
            "avail": {
                "cand1": {"2025-04-01 09:00-09:45": 1, "2025-04-01 09:45-10:30": 1},
            },
            "staff": ["lead1", "panel1"],
            "staff_avail": {
                "lead1": {"2025-04-01 09:00-09:45": 1, "2025-04-01 09:45-10:30": 1},
                "panel1": {"2025-04-01 09:00-09:45": 1, "2025-04-01 09:45-10:30": 1},
            },
            "required_staff": {"cand1": ["lead1"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "staff_change_penalty_weight": 0,
            "time_limit": 10,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,
        }

        from scheduler.solver import solve_initial_schedule
        schedule1, meta1 = solve_initial_schedule(data_store=ds, params=params)
        assert schedule1, "Initial solve should succeed"

        # Verify lead1 appears in the initial assignment
        staff_assignment = meta1.get("staff_assignment", {})
        assigned_slot = schedule1.get("cand1")
        assert "lead1" in staff_assignment.get(assigned_slot, []), \
            "lead1 should be assigned to cand1's slot in the initial schedule"

        # Now add a new candidate via change event
        data_dict2 = dict(data_dict)
        data_dict2["prev_schedule"] = schedule1
        data_dict2["prev_staff_assignment"] = staff_assignment

        params2 = dict(params)
        params2["_data_store_dict"] = data_dict2

        change_event = {"add_candidate": ["cand_new"]}
        schedule2, meta2 = reschedule(data_store=ds, change_event=change_event, params=params2)
        assert schedule2, "Reschedule after add_candidate should succeed"
        assert "cand_new" in schedule2, "New candidate should be scheduled"

        # The new candidate's assigned slot must have lead1 present
        staff_assignment2 = meta2.get("staff_assignment", {})
        new_slot = schedule2.get("cand_new")
        assert new_slot is not None, "cand_new should be assigned a slot"
        assert "lead1" in staff_assignment2.get(new_slot, []), \
            f"lead1 must be present at slot '{new_slot}' for cand_new (lead requirement should be inherited)"


# ---------------------------------------------------------------------------
# 3. staff/staff_avail out-of-sync — KeyError regression test
# ---------------------------------------------------------------------------

def test_reschedule_does_not_crash_when_staff_missing_from_staff_avail():
    """
    Regression test: if a staff member is in the 'staff' list but absent from
    'staff_avail' (e.g. due to state mutations), the solver should NOT raise
    a KeyError — it should treat the staff member as fully available.
    """
    import tempfile
    from data_models.store import DataStore
    from scheduler.solver import solve_initial_schedule, reschedule

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["cand1"],
            "time_slots": ["2025-04-01 09:00-09:45", "2025-04-01 09:45-10:30"],
            "avail": {
                "cand1": {"2025-04-01 09:00-09:45": 1, "2025-04-01 09:45-10:30": 1},
            },
            # Wanda Pell is in 'staff' but deliberately ABSENT from 'staff_avail'
            "staff": ["lead1", "Wanda Pell"],
            "staff_avail": {
                "lead1": {"2025-04-01 09:00-09:45": 1, "2025-04-01 09:45-10:30": 1},
                # "Wanda Pell" intentionally missing to reproduce the KeyError
            },
            "required_staff": {"cand1": ["lead1"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "staff_change_penalty_weight": 0,
            "time_limit": 10,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,
        }

        # This should NOT raise KeyError: 'Wanda Pell'
        try:
            schedule, meta = solve_initial_schedule(data_store=ds, params=params)
            assert schedule, "Solve should succeed despite staff_avail being incomplete"
        except KeyError as e:
            pytest.fail(f"KeyError raised for missing staff_avail entry: {e}")

        # Same check for reschedule + add_candidate
        data_dict2 = dict(data_dict)
        data_dict2["prev_schedule"] = schedule
        data_dict2["prev_staff_assignment"] = meta.get("staff_assignment", {})
        params2 = dict(params)
        params2["_data_store_dict"] = data_dict2

        try:
            schedule2, _ = reschedule(
                data_store=ds,
                change_event={"add_candidate": ["cand_new"]},
                params=params2,
            )
            assert "cand_new" in schedule2, "New candidate must be scheduled"
        except KeyError as e:
            pytest.fail(f"KeyError raised during reschedule with missing staff_avail entry: {e}")


# ---------------------------------------------------------------------------
# 4. lead_ids persisted in schedule metadata and read back on solve/reschedule
# ---------------------------------------------------------------------------

def test_lead_ids_saved_in_schedule_metadata():
    """When solve_initial_schedule is called with lead_ids in params, the saved
    schedule metadata must include 'lead_ids' so _resume_run can recover it."""
    import tempfile
    from scheduler.solver import solve_initial_schedule
    from data_models.store import DataStore

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["cand1"],
            "time_slots": ["t1", "t2"],
            "avail": {"cand1": {"t1": 1, "t2": 1}},
            "staff": ["alice", "lead_bob"],
            "staff_avail": {
                "alice": {"t1": 1, "t2": 1},
                "lead_bob": {"t1": 1, "t2": 1},
            },
            "required_staff": {"cand1": ["lead_bob"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
            "lead_ids": ["lead_bob"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,
            "lead_ids": ["lead_bob"],  # passed explicitly as in _run_solve
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        assert schedule, "Solve should succeed"

        sid = meta.get("saved_schedule_id")
        assert sid, "schedule_id must be saved in metadata"

        payload = ds.get_schedule_metadata(sid)
        saved_lead_ids = (payload.get("metadata") or {}).get("lead_ids")
        assert saved_lead_ids == ["lead_bob"], (
            f"lead_ids must be persisted in schedule metadata; got {saved_lead_ids}"
        )


def test_reschedule_lead_ids_saved_and_propagated():
    """After a reschedule the lead_ids must still appear in metadata and new
    candidates must inherit the lead requirement."""
    import tempfile
    from scheduler.solver import solve_initial_schedule, reschedule
    from data_models.store import DataStore

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["cand1"],
            "time_slots": ["t1", "t2"],
            "avail": {"cand1": {"t1": 1, "t2": 1}},
            "staff": ["non_lead_alice", "lead_bob"],
            "staff_avail": {
                "non_lead_alice": {"t1": 1, "t2": 1},
                "lead_bob": {"t1": 1, "t2": 1},
            },
            "required_staff": {"cand1": ["lead_bob"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
            "lead_ids": ["lead_bob"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,
            "lead_ids": ["lead_bob"],
        }

        schedule1, meta1 = solve_initial_schedule(data_store=ds, params=params)
        assert schedule1

        data_dict2 = dict(data_dict)
        data_dict2["prev_schedule"] = schedule1
        data_dict2["prev_staff_assignment"] = meta1.get("staff_assignment", {})
        params2 = dict(params)
        params2["_data_store_dict"] = data_dict2

        schedule2, meta2 = reschedule(
            data_store=ds,
            change_event={"add_candidate": ["cand_new"]},
            params=params2,
        )
        assert "cand_new" in schedule2

        sid2 = meta2.get("saved_schedule_id")
        payload2 = ds.get_schedule_metadata(sid2)
        saved_leads2 = (payload2.get("metadata") or {}).get("lead_ids")
        assert saved_leads2 == ["lead_bob"], (
            f"lead_ids must be persisted in reschedule metadata; got {saved_leads2}"
        )

        # The new candidate's slot must contain lead_bob
        staff_asgn = meta2.get("staff_assignment", {})
        slot = schedule2.get("cand_new")
        assert "lead_bob" in staff_asgn.get(slot, []), (
            "lead_bob must attend the new candidate's slot"
        )


# ---------------------------------------------------------------------------
# 5. Lead inheritance works even when UI pre-adds candidate to ds["candidates"]
# ---------------------------------------------------------------------------

def test_add_candidate_inherits_lead_even_when_preinserted_in_ds():
    """When the web-app UI pre-inserts the candidate into ds['candidates']
    before calling reschedule(), the solver must still set required_staff for
    that candidate from ds['lead_ids'].  This was broken because the lead-
    inheritance block was guarded by 'if c not in candidates'.
    """
    import tempfile
    from scheduler.solver import solve_initial_schedule, reschedule
    from data_models.store import DataStore

    lead_name = "non_lead_prefix_alice"  # does NOT start with 'lead', intentionally
    # Using a name that does not start with 'lead' verifies that the solver
    # respects manually-configured lead IDs regardless of name prefix.

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["cand1"],
            "time_slots": ["t1", "t2", "t3"],
            "avail": {"cand1": {"t1": 1, "t2": 1, "t3": 1}},
            "staff": ["bob", lead_name],
            "staff_avail": {
                "bob": {"t1": 1, "t2": 1, "t3": 1},
                lead_name: {"t1": 1, "t2": 1, "t3": 1},
            },
            "required_staff": {"cand1": [lead_name]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
            "lead_ids": [lead_name],
        }

        params_base = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "strategy": "change_penalty",
            "_data_store_dict": data_dict,
            "lead_ids": [lead_name],
        }

        schedule1, meta1 = solve_initial_schedule(data_store=ds, params=params_base)
        assert schedule1

        # Simulate what the web UI does: pre-insert the new candidate into
        # ds["candidates"] and ds["avail"] WITHOUT touching required_staff.
        data_dict2 = dict(data_dict)
        data_dict2["candidates"] = list(data_dict["candidates"]) + ["cand_new"]
        data_dict2["avail"] = dict(data_dict["avail"])
        data_dict2["avail"]["cand_new"] = {t: 1 for t in data_dict["time_slots"]}
        data_dict2["required_staff"] = dict(data_dict["required_staff"])
        # NOTE: required_staff["cand_new"] is deliberately NOT set (UI omission)
        data_dict2["prev_schedule"] = schedule1
        data_dict2["prev_staff_assignment"] = meta1.get("staff_assignment", {})

        params2 = dict(params_base)
        params2["_data_store_dict"] = data_dict2

        schedule2, meta2 = reschedule(
            data_store=ds,
            change_event={"add_candidate": ["cand_new"]},
            params=params2,
        )

        assert "cand_new" in schedule2, "New candidate must be scheduled"
        slot = schedule2["cand_new"]
        staff_at_slot = meta2.get("staff_assignment", {}).get(slot, [])
        assert lead_name in staff_at_slot, (
            f"Lead '{lead_name}' must attend the new candidate's slot; "
            f"got staff: {staff_at_slot}"
        )


def test_time_slots_saved_in_metadata():
    """solve_initial_schedule must persist time_slots in schedule metadata so
    _resume_run can restore the full slot universe (not just occupied slots)."""
    import tempfile
    from scheduler.solver import solve_initial_schedule
    from data_models.store import DataStore

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        data_dict = {
            "candidates": ["c1"],
            "time_slots": ["t1", "t2", "t3", "t4", "t5"],  # 5 slots for 1 candidate
            "avail": {"c1": {t: 1 for t in ["t1", "t2", "t3", "t4", "t5"]}},
            "staff": ["lead_a"],
            "staff_avail": {"lead_a": {t: 1 for t in ["t1", "t2", "t3", "t4", "t5"]}},
            "required_staff": {"c1": ["lead_a"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
            "lead_ids": ["lead_a"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "_data_store_dict": data_dict,
            "lead_ids": ["lead_a"],
        }

        schedule, meta = solve_initial_schedule(data_store=ds, params=params)
        assert schedule

        sid = meta.get("saved_schedule_id")
        payload = ds.get_schedule_metadata(sid)
        saved_slots = (payload.get("metadata") or {}).get("time_slots")
        assert saved_slots is not None, "time_slots must be saved in schedule metadata"
        assert set(saved_slots) == {"t1", "t2", "t3", "t4", "t5"}, (
            f"All 5 time slots must be saved, got: {saved_slots}"
        )


def test_resume_with_full_time_slots_allows_add_candidate():
    """When time_slots is restored from saved metadata, adding a new candidate
    after resume must not produce INFEASIBLE (the model had ≤1 cand/slot and
    only N occupied slots for N candidates before this fix)."""
    import tempfile
    from scheduler.solver import solve_initial_schedule, reschedule
    from data_models.store import DataStore

    with tempfile.TemporaryDirectory() as tmpdir:
        ds = DataStore(config={"base_dir": tmpdir})

        all_slots = ["t1", "t2", "t3"]  # 3 slots for 2 candidates → 1 free
        data_dict = {
            "candidates": ["c1", "c2"],
            "time_slots": all_slots,
            "avail": {"c1": {t: 1 for t in all_slots}, "c2": {t: 1 for t in all_slots}},
            "staff": ["lead_a"],
            "staff_avail": {"lead_a": {t: 1 for t in all_slots}},
            "required_staff": {"c1": ["lead_a"], "c2": ["lead_a"]},
            "forbidden_pairs": [],
            "prev_schedule": {},
            "prev_staff_assignment": {},
            "lead_ids": ["lead_a"],
        }

        params = {
            "persist": True,
            "min_staff_per_slot": 1,
            "fairness": "none",
            "time_limit": 5,
            "_data_store_dict": data_dict,
            "lead_ids": ["lead_a"],
        }

        schedule1, meta1 = solve_initial_schedule(data_store=ds, params=params)
        assert schedule1

        # Simulate what _resume_run() now does: restore time_slots from metadata
        sid = meta1.get("saved_schedule_id")
        payload = ds.get_schedule_metadata(sid)
        restored_slots = (payload.get("metadata") or {}).get("time_slots", [])
        assert set(restored_slots) == set(all_slots), "time_slots must be fully restored"

        # Build a skeleton data_store like _resume_run() would produce
        skeleton = {
            "candidates": list(schedule1.keys()),
            "time_slots": restored_slots,  # full universe, NOT just occupied
            "avail": {c: {t: 1 for t in restored_slots} for c in schedule1},
            "staff": list({s for sl in meta1.get("staff_assignment", {}).values() for s in sl}),
            "staff_avail": {"lead_a": {t: 1 for t in restored_slots}},
            "required_staff": {c: ["lead_a"] for c in schedule1},
            "forbidden_pairs": [],
            "prev_schedule": schedule1,
            "prev_staff_assignment": meta1.get("staff_assignment", {}),
            "lead_ids": ["lead_a"],
        }

        params2 = dict(params)
        params2["_data_store_dict"] = skeleton

        # Pre-add c3 as the UI does (without setting required_staff)
        skeleton["candidates"].append("c3")
        skeleton["avail"]["c3"] = {t: 1 for t in restored_slots}

        schedule2, meta2 = reschedule(
            data_store=ds,
            change_event={"add_candidate": ["c3"]},
            params=params2,
        )

        status = meta2.get("status", "")
        assert status in ("OPTIMAL", "FEASIBLE"), (
            f"Reschedule must be feasible with restored time_slots; got status={status}"
        )
        assert "c3" in schedule2, "New candidate must be scheduled"
