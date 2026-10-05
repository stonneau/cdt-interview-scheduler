"""The browser API (JSON in / JSON out) end to end, under CPython."""

import json

import pytest

pytest.importorskip("scipy")

from webapi import api  # noqa: E402
from webapi.example import make_example  # noqa: E402


def call(method, **payload):
    out = json.loads(api.dispatch(method, json.dumps(payload)))
    return out


@pytest.fixture(autouse=True)
def fresh_session():
    api.STATE.ds, api.STATE.last = None, None


def test_requires_data_first():
    out = call("solve", params={})
    assert out["ok"] is False and "No data loaded" in out["error"]


def test_example_end_to_end():
    out = call("load_example")
    assert out["ok"] and out["data"]["info"]["leads"] == ["lead1", "lead2", "lead3"]
    assert len(out["data"]["info"]["candidates"]) == 33

    params = {"min_staff": 2, "max_staff": 2, "fairness": "min_dev", "time_limit": 60,
              "allow_parallel": False}
    solved = call("solve", params=params)["data"]["result"]
    assert solved["status"] == "OPTIMAL" and len(solved["rows"]) == 33
    leads = {"lead1", "lead2", "lead3"}
    for r in solved["rows"]:
        assert len(r["panel"]) == 2 and set(r["panel"]) & leads
    assert len({(r["slot"]) for r in solved["rows"]}) == 33

    # a panel member cancels the day of the first interview -> only a few people move
    first = solved["rows"][0]
    victim = first["panel"][-1]
    out = call("reschedule", params=params, strategy="local_repair",
               changes={"staff_unavailable_dates": [[victim, first["date"]]]})
    res = out["data"]["result"]
    assert res["ok"] and res["changes"]["moved"] <= 3
    assert all(victim not in r["panel"] for r in res["rows"] if r["date"] == first["date"])
    # the staged cancellation is now part of the session: rescheduling again keeps it
    again = call("reschedule", params=params, strategy="change_penalty",
                 changes={"add_candidate": [{"id": "Late Applicant"}]})["data"]["result"]
    assert again["ok"] and again["changes"]["new"] == 1
    assert all(victim not in r["panel"] for r in again["rows"] if r["date"] == first["date"])

    csv_text = call("export", kind="prev")["data"]["csv"]
    assert csv_text.startswith("candidate_id,timeslot_id,staff_ids\n")
    assert len(csv_text.strip().splitlines()) == 1 + 34


def test_freeze_date_keeps_earlier_interviews():
    call("load_example")
    params = {"time_limit": 60}
    solved = call("solve", params=params)["data"]["result"]
    dates = sorted({r["date"] for r in solved["rows"]})
    cutoff = dates[len(dates) // 2]
    before = {r["candidate"]: (r["slot"], tuple(r["panel"])) for r in solved["rows"] if r["date"] <= cutoff}
    # remove somebody scheduled after the cutoff and cancel a late staff member
    late = next(r for r in solved["rows"] if r["date"] > cutoff)
    out = call("reschedule", params=params, strategy="change_penalty", freeze_date=cutoff,
               changes={"staff_unavailable": [[late["panel"][-1], late["slot"]]]})["data"]["result"]
    assert out["ok"]
    after = {r["candidate"]: (r["slot"], tuple(r["panel"])) for r in out["rows"] if r["date"] <= cutoff}
    assert after == before


def test_infeasible_returns_diagnostics():
    texts = make_example()
    # one applicant is never available
    lines = texts["applicants"].splitlines()
    cells = lines[2].split(",")
    lines[2] = ",".join([cells[0]] + ["No"] * (len(cells) - 1))
    call("load", applicants="\n".join(lines) + "\n", staff=texts["staff"], lead_ids="")
    out = call("solve", params={"time_limit": 30})["data"]["result"]
    assert out["ok"] is False and out["status"] == "INFEASIBLE"
    assert out["diagnostics"]["no_slot"][0]["candidate"] == cells[0]


def test_panel_of_three_is_kept_when_rescheduling():
    call("load_example")
    params = {"min_staff": 3, "max_staff": 3, "time_limit": 30}
    res = call("solve", params=params)["data"]["result"]
    assert res["ok"] and all(len(r["panel"]) == 3 for r in res["rows"])
    # rescheduling must keep the same panel size bounds (regression: max was reset to 2)
    victim = res["rows"][0]
    out = call("reschedule", params=params, strategy="local_repair",
               changes={"staff_unavailable": [[victim["panel"][-1], victim["slot"].split(".")[0]]]})
    assert out["data"]["result"]["ok"]
    assert all(len(r["panel"]) == 3 for r in out["data"]["result"]["rows"])


def test_bad_input_is_reported_not_raised():
    out = call("load", applicants="", staff="x")
    assert out["ok"] is False and out["error"]


def test_afternoon_hours_are_displayed_and_sorted_chronologically():
    """Doodle writes 1pm as '1': rows must show 13:00 and sort after 09:00 of the same day."""
    call("load_example")
    res = call("solve", params={"time_limit": 60})["data"]["result"]
    assert all("08:00" <= r["time"] <= "19:00" for r in res["rows"]), {r["time"] for r in res["rows"]}
    keys = [(r["date"], r["time"], r["room"]) for r in res["rows"]]
    assert keys == sorted(keys)
    assert any(r["time"] >= "13:00" for r in res["rows"])


def test_wrong_file_is_rejected_with_a_clear_message():
    texts = make_example()
    out = call("load", applicants=texts["forbidden"], staff=texts["staff"])   # wrong file as applicants
    assert out["ok"] is False and "does not look like an availability export" in out["error"]
    out = call("load", applicants=texts["applicants"], staff=texts["applicants"].replace("2026", "x"))
    assert out["ok"] is False


def test_applicant_without_availability_is_flagged():
    texts = make_example()
    lines = texts["applicants"].splitlines()
    cells = lines[2].split(",")
    lines[2] = ",".join([cells[0]] + ["No"] * (len(cells) - 1))
    out = call("load", applicants="\n".join(lines) + "\n", staff=texts["staff"])
    assert out["ok"] and any(cells[0] in w for w in out["data"]["warnings"])


REAL_STYLE_APPLICANTS = (
    ",2026-03-11,2026-03-11,2026-03-11\n,9,9.45,10.30\n"
    "Ann Lee,Yes,If needed,\nBo Chan,No,Yes,Yes\nCy Dunn,Yes,Yes,No\nBo Chan,Yes,Yes,Yes\n")
REAL_STYLE_STAFF = (
    ",2026-03-11,2026-03-11,2026-03-11\n,9,9.45,10.3\n"
    "Prof A,Yes,Yes,Yes\nProf B,Yes,If needed,Yes\nProf C,No,Yes,Yes\nProf B,Yes,Yes,Yes\n")


def test_duplicate_names_are_resolved_not_rejected():
    for policy, expect_bo in (("last", [1, 1, 1]), ("first", [0, 1, 1]), ("both", [0, 1, 1])):
        out = call("load", applicants=REAL_STYLE_APPLICANTS, staff=REAL_STYLE_STAFF, duplicates=policy,
                   lead_ids="Prof A")
        assert out["ok"], out
        d = out["data"]
        assert len(d["info"]["candidates"]) == 3 and len(d["info"]["staff"]) == 3
        assert any("more than once" in w and "Bo Chan" in w for w in d["warnings"])
        slots = d["info"]["slots"]
        bo = [api.STATE.ds["avail"]["Bo Chan"][t] for t in slots]
        assert bo == expect_bo, (policy, bo)


def test_if_needed_option():
    off = call("load", applicants=REAL_STYLE_APPLICANTS, staff=REAL_STYLE_STAFF, lead_ids="Prof A")["data"]
    ann_off = [api.STATE.ds["avail"]["Ann Lee"][t] for t in off["info"]["slots"]]
    on = call("load", applicants=REAL_STYLE_APPLICANTS, staff=REAL_STYLE_STAFF, lead_ids="Prof A",
              if_needed="available")["data"]
    ann_on = [api.STATE.ds["avail"]["Ann Lee"][t] for t in on["info"]["slots"]]
    assert ann_off == [1, 0, 0] and ann_on == [1, 1, 0]
    assert any("If needed" in w for w in off["warnings"])


def test_lead_picker_changes_required_staff():
    call("load", applicants=REAL_STYLE_APPLICANTS, staff=REAL_STYLE_STAFF, if_needed="available")
    assert api.STATE.ds["lead_ids"] == []                      # real names: nothing auto-detected
    out = call("set_leads", lead_ids=["Prof A", "Prof C", "nobody"])["data"]["info"]
    assert out["leads"] == ["Prof A", "Prof C"]
    assert all(v == ["Prof A", "Prof C"] for v in api.STATE.ds["required_staff"].values())


def test_infeasible_hint_mentions_if_needed():
    texts = ",2026-03-11\n,9\nAnn,If needed\n", ",2026-03-11\n,9\nlead1,Yes\nstaff,Yes\n"
    call("load", applicants=texts[0], staff=texts[1])
    res = call("solve", params={"time_limit": 10})["data"]["result"]
    assert res["status"] == "INFEASIBLE" and res["diagnostics"]["hint_if_needed"] == 1
    call("load", applicants=texts[0], staff=texts[1], if_needed="available")
    assert call("solve", params={"time_limit": 10})["data"]["result"]["ok"]


def test_example_files_download_matches_the_example_and_can_be_loaded():
    import base64, io, zipfile
    out = call("example_files")
    assert out["ok"]
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(out["data"]["zip_base64"])))
    assert sorted(z.namelist()) == ["applicants_availabilities.csv", "forbidden_pairs.csv", "staff_availabilities.csv"]
    loaded = call("load", applicants=z.read("applicants_availabilities.csv").decode(),
                  staff=z.read("staff_availabilities.csv").decode(), forbidden=z.read("forbidden_pairs.csv").decode())
    assert loaded["ok"] and len(loaded["data"]["info"]["candidates"]) == 33
    assert loaded["data"]["info"]["n_forbidden"] == 8


def test_parallel_rooms_are_added_only_when_needed():
    call("load_example")
    r = call("solve", params={"allow_parallel": True, "max_parallel": 3, "time_limit": 60})["data"]["result"]
    assert r["ok"] and r["rooms_used"] == 1            # 33 applicants fit in the base rooms
    assert all(row["room"] == 1 for row in r["rows"])


def test_rooms_escalate_one_at_a_time_and_are_kept_when_rescheduling():
    texts = make_example(8, 24, 12, 3, 2)               # 24 applicants, only 20 base slots
    call("load", applicants=texts["applicants"], staff=texts["staff"], forbidden=texts["forbidden"],
         if_needed="available")
    params = {"allow_parallel": True, "max_parallel": 3, "time_limit": 20}
    r = call("solve", params=params)["data"]["result"]
    assert r["ok"] and r["rooms_used"] == 2 and max(row["room"] for row in r["rows"]) == 2
    # rescheduling without the rooms option must still keep the rooms the schedule already uses
    victim = r["rows"][0]
    out = call("reschedule", params={**params, "allow_parallel": False}, strategy="local_repair",
               changes={"staff_unavailable": [[victim["panel"][-1], victim["slot"].split(".")[0]]]})
    assert out["data"]["result"]["ok"] and out["data"]["result"]["rooms_used"] == 2


def test_timeout_without_a_schedule_is_not_reported_as_infeasible():
    call("load_example")
    params = api._params({"allow_parallel": True, "max_parallel": 3, "time_limit": 30})
    res = api._result(api.STATE.ds, {}, {"status": "UNKNOWN", "solve_time_seconds": 30.0}, params)
    assert res["ok"] is False and res["diagnostics"]["timeout"] is True
    assert "no_slot" not in res["diagnostics"]          # no misleading "several rules combining" text
