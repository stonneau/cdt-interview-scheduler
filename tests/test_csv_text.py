"""The stdlib-only text parsers must agree with the pandas file loaders."""

import os
import tempfile

import pytest

pytest.importorskip("pandas")

from data_models import csv_text, loaders  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

AVAIL_TEXTS = {
    "range format": ",2025-04-01,2025-04-01\n,09:00-09:45,09:45-10:30\nAlice,Yes,No\nBob,yes,YES\n",
    "doodle H.MM labels": ",2026-04-01 x,2026-04-01 x,2026-04-02 x\n,9,9.45,10.3\nAlice,Yes,If needed,\nBob,,Yes,no\n",
    "blank names fall back": ",2026-03-11,2026-03-11\n,9,9.45\n,Yes,Yes\n  ,No,Yes\n",
    "short rows + blank lines + BOM": "﻿,2026-03-11,2026-03-11,2026-03-12\n,9,9.45,10\n\nAlice,Yes\nBob,Yes,Yes,Yes\n",
    "quoted names": ',2026-03-11\n,9\n"Smith, Jo",Yes\n',
    "blank-with-space cells are NOT available": ",2026-03-11,2026-03-11\n,9,9.45\nAlice, ,Yes\n",
}
STAFF_TEXTS = {
    "leads": "Name,2025-04-01,2025-04-01\n,09:00-09:45,09:45-10:30\nlead1,Yes,Yes\npanel1,No,Yes\n",
    "doodle": " ,2026-04-01 x,2026-04-01 x\n,9,9.45\nlead2,Yes,\nStaff-01,yes,Yes\n",
}
FORBIDDEN_TEXTS = {
    "simple": "candidate_id,staff_id\nAlice,Prof X\n Bob , Prof Y \n,Z\nCarl,\n",
    "real format": ('Applicant,,,Comments,,Interview,\nSurname,First name(s),Potential Supervisors,,,,\n'
                    'Fenwick,Maya,Nora Whitlock,,,,\nMarlow,Theo,"Idris Calder, Felix Ashworth",,,,\n'
                    'Harlow,Jonas Peter Wren,,,,,\n'),
    "real format, no Surname row": "Applicant,,,x,\nFenwick,Maya,Nora Whitlock,,\n",
}
PREV_TEXT = ("candidate_id,timeslot_id,staff_ids\nA,2025-04-01 09:00,s1;s2\n"
             "B,2025-04-01 09:00,s2;s3\nC,2025-04-01 09:45,\"s1; s3\"\n")


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    f.write(text)
    f.close()
    return f.name


def with_file(text, loader):
    path = write(text)
    try:
        return loader(path)
    finally:
        os.remove(path)


def cand_view(result):
    objs, slots = result
    return [(c.id, dict(c.availability)) for c in objs], list(slots)


def staff_view(result):
    objs, slots = result
    return [(s.id, s.is_lead, dict(s.availability)) for s in objs], list(slots)


@pytest.mark.parametrize("name", AVAIL_TEXTS)
def test_availability_matches_pandas(name):
    text = AVAIL_TEXTS[name]
    assert cand_view(csv_text.parse_availability_text(text)) == \
        cand_view(with_file(text, loaders.load_availability_objects_from_csv))


@pytest.mark.parametrize("name", STAFF_TEXTS)
def test_staff_matches_pandas(name):
    text = STAFF_TEXTS[name]
    assert staff_view(csv_text.parse_staff_text(text)) == \
        staff_view(with_file(text, loaders.load_staff_objects_from_csv))


@pytest.mark.parametrize("name", FORBIDDEN_TEXTS)
def test_forbidden_pairs_match_pandas(name):
    text = FORBIDDEN_TEXTS[name]
    assert csv_text.parse_forbidden_pairs_text(text) == \
        with_file(text, loaders.load_forbidden_pairs_from_csv)


def test_prev_schedule_matches_pandas():
    assert csv_text.parse_prev_schedule_text(PREV_TEXT) == \
        with_file(PREV_TEXT, loaders.load_prev_schedule_from_csv)


@pytest.mark.parametrize("text,fn_text,fn_file", [
    ("a,b\n1,2\n", csv_text.parse_forbidden_pairs_text, loaders.load_forbidden_pairs_from_csv),
    ("candidate_id,timeslot_id\nA,t\n", csv_text.parse_prev_schedule_text, loaders.load_prev_schedule_from_csv),
    ("candidate_id,timeslot_id,staff_ids\nA,t,\n", csv_text.parse_prev_schedule_text, loaders.load_prev_schedule_from_csv),
    ("candidate_id,timeslot_id,staff_ids\nA,t,s\nA,u,s\n", csv_text.parse_prev_schedule_text, loaders.load_prev_schedule_from_csv),
])
def test_same_errors_as_pandas(text, fn_text, fn_file):
    with pytest.raises(ValueError):
        fn_text(text)
    with pytest.raises(ValueError):
        with_file(text, fn_file)


@pytest.mark.skipif(not os.path.isdir(os.path.join(DATA, "cdt_example")), reason="example data not present")
def test_bundled_example_files_match_pandas():
    d = os.path.join(DATA, "cdt_example")
    read = lambda n: open(os.path.join(d, n), encoding="utf-8").read()
    assert cand_view(csv_text.parse_availability_text(read("applicants_availabilities.csv"))) == \
        cand_view(loaders.load_availability_objects_from_csv(os.path.join(d, "applicants_availabilities.csv")))
    assert staff_view(csv_text.parse_staff_text(read("staff_availabilities.csv"))) == \
        staff_view(loaders.load_staff_objects_from_csv(os.path.join(d, "staff_availabilities.csv")))
    assert csv_text.parse_forbidden_pairs_text(read("forbidden_pairs.csv")) == \
        loaders.load_forbidden_pairs_from_csv(os.path.join(d, "forbidden_pairs.csv"))


def test_loaders_import_without_pandas():
    """The solver path must not import pandas (needed for the browser build)."""
    import subprocess, sys
    code = ("import sys; sys.modules['pandas'] = None; "
            "import data_models, data_models.csv_text, scheduler.solver; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.stdout.strip() == "ok", r.stderr
