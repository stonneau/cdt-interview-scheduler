"""Parse the scheduler's CSV formats from *text*, using only the standard library.

These functions mirror the pandas-based loaders in :mod:`data_models.loaders`
(same results, same error messages) but take the CSV content as a string, so
they work in the browser (Pyodide, where the file is read client-side) and
without pandas.  ``tests/test_csv_text.py`` checks the two implementations
against each other.
"""

import csv
import io
from typing import Dict, List, Set, Tuple

from data_models.loaders import _isna, _normalize_slot_label, _parse_availability_value
from data_models.models import Candidate, Staff

_NAN = float("nan")


def _read_rows(text: str, ragged_pad: bool = True) -> List[list]:
    """CSV text -> list of rows; blank lines skipped, empty cells become NaN.

    Mirrors ``pandas.read_csv`` defaults: rows shorter than the widest row are
    padded with NaN, and a UTF-8 byte-order mark is ignored.
    """
    text = text.lstrip("﻿")
    rows = [r for r in csv.reader(io.StringIO(text)) if r and any(c != "" for c in r)]
    width = max((len(r) for r in rows), default=0)
    out = []
    for r in rows:
        r = [(_NAN if c == "" else c) for c in r]
        if ragged_pad:
            r = r + [_NAN] * (width - len(r))
        out.append(r)
    return out


def parse_availability_text(text: str, use_real_names: bool = True) -> Tuple[List[Candidate], List[str]]:
    """Same as :func:`data_models.loaders.load_availability_objects_from_csv`."""
    rows = _read_rows(text)
    date_row, slot_row = rows[0][1:], rows[1][1:]
    time_slots = [f"{d} {_normalize_slot_label(s)}" for d, s in zip(date_row, slot_row)]
    candidates = []
    for i, row in enumerate(rows[2:]):
        raw_name = row[0]
        if use_real_names and not _isna(raw_name) and str(raw_name).strip():
            cid = str(raw_name).strip()
        else:
            cid = f"cand{i + 1}"
        cand = Candidate(id=cid)
        for j, slot in enumerate(time_slots):
            cand.availability[slot] = _parse_availability_value(row[j + 1])
        candidates.append(cand)
    return candidates, time_slots


def parse_staff_text(text: str) -> Tuple[List[Staff], List[str]]:
    """Same as :func:`data_models.loaders.load_staff_objects_from_csv`."""
    rows = _read_rows(text)
    date_row = [str(d).split()[0] for d in rows[0][1:]]
    slot_row = rows[1][1:]
    time_slots = [f"{d} {_normalize_slot_label(s)}" for d, s in zip(date_row, slot_row)]
    staff_objs = []
    for row in rows[2:]:
        sname = row[0]
        staff = Staff(id=sname)
        staff.is_lead = str(sname).startswith("lead")
        for j, slot in enumerate(time_slots):
            staff.availability[slot] = _parse_availability_value(row[j + 1])
        staff_objs.append(staff)
    return staff_objs, time_slots


def parse_forbidden_pairs_text(text: str) -> Set[Tuple[str, str]]:
    """Same as :func:`data_models.loaders.load_forbidden_pairs_from_csv`."""
    rows = _read_rows(text)
    header, data = rows[0], rows[1:]
    cols = set(header)
    if "candidate_id" in cols and "staff_id" in cols:
        ci, si = header.index("candidate_id"), header.index("staff_id")
        pairs: Set[Tuple[str, str]] = set()
        for row in data:
            cand, staff = row[ci], row[si]
            if _isna(cand) or _isna(staff):
                continue
            c, s = str(cand).strip(), str(staff).strip()
            if c and s:
                pairs.add((c, s))
        return pairs

    if len(header) < 3:
        raise ValueError(
            "forbidden_pairs CSV must have either 'candidate_id,staff_id' columns "
            "or at least 3 columns (Surname, First name(s), Potential Supervisors). "
            f"Found columns: {header}"
        )
    start = 0
    first_val = str(data[0][0]).strip().lower() if data else ""
    if first_val == "surname":
        start = 1
    pairs = set()
    for row in data[start:]:
        surname_raw, first_raw, sup_raw = row[0], row[1], row[2]
        if _isna(surname_raw) or _isna(first_raw):
            continue
        surname, first = str(surname_raw).strip(), str(first_raw).strip()
        if not surname or not first or _isna(sup_raw):
            continue
        sup_str = str(sup_raw).strip()
        for sup in sup_str.split(","):
            s = sup.strip()
            if s:
                pairs.add((f"{first} {surname}", s))
    return pairs


def parse_prev_schedule_text(text: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Same as :func:`data_models.loaders.load_prev_schedule_from_csv`."""
    rows = _read_rows(text)
    header, data = rows[0], rows[1:]
    missing = {"candidate_id", "timeslot_id", "staff_ids"} - set(header)
    if missing:
        raise ValueError(f"prev_schedule CSV missing required columns: {sorted(missing)}")
    ci, ti, si = (header.index(k) for k in ("candidate_id", "timeslot_id", "staff_ids"))

    cand_to_slot: Dict[str, str] = {}
    staff_by_slot: Dict[str, List[str]] = {}
    for i, row in enumerate(data):
        cand = "" if _isna(row[ci]) else str(row[ci]).strip()
        slot = "" if _isna(row[ti]) else str(row[ti]).strip()
        staff_str = "" if _isna(row[si]) else str(row[si]).strip()
        if not cand:
            raise ValueError(f"Empty candidate_id at row {i + 2}")
        if not slot:
            raise ValueError(f"Empty timeslot_id for candidate {cand!r} at row {i + 2}")
        if not staff_str:
            raise ValueError(f"Empty staff_ids for candidate {cand!r} at row {i + 2}")
        staff_ids = [s.strip() for s in staff_str.split(";") if s.strip()]
        if not staff_ids:
            raise ValueError(f"No valid staff_ids parsed for candidate {cand!r} at row {i + 2}")
        if cand in cand_to_slot:
            raise ValueError(f"Duplicate candidate_id {cand!r} in prev_schedule CSV")
        cand_to_slot[cand] = slot
        existing = staff_by_slot.get(slot, [])
        staff_by_slot[slot] = existing + [s for s in staff_ids if s not in existing]
    return cand_to_slot, staff_by_slot
