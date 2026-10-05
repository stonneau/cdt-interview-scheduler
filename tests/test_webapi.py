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
