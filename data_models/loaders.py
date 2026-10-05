"""Data loading and conversion functions for the constraint-solver system.

Provides CSV loaders for candidate availability, staff availability,
forbidden candidate–staff pairings, and previous schedules.  Also exposes
converters that transform model objects into the flat dictionary structures
expected by the solver engine.
"""

from typing import List, Tuple, Dict, Set

from data_models.models import Candidate, Staff, ScheduleAssignment
import pandas as pd
from datetime import datetime


def _normalize_slot_label(raw) -> str:
    """Normalise a single slot label to ``HH:MM`` format.

    Handles decimal notation (``9.45`` → ``09:45``), bare integers
    (``9`` → ``09:00``), and passes non-numeric labels through unchanged.

    :param raw: Raw slot label value (may be numeric, string, or NaN).
    :returns: Normalised slot string, or empty string for NaN/blank input.
    """
    if pd.isna(raw):
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if "." in s:
        parts = s.split(".", 1)
        try:
            hour = int(parts[0])
            minutes = int(parts[1].ljust(2, "0")[:2])
            if 0 <= minutes <= 59:
                return f"{hour:02d}:{minutes:02d}"
            return s
        except ValueError:
            return s
    else:
        try:
            hour = int(s)
            return f"{hour:02d}:00"
        except ValueError:
            return s


def _parse_availability_value(val) -> int:
    """Parse a single availability cell into ``0`` or ``1``.

    Only the string ``"yes"`` (case-insensitive) is treated as available.
    Everything else — including ``"no"``, empty/NaN cells, and any other
    text — returns ``0``.

    :param val: Raw cell value from the availability CSV.
    :returns: ``1`` if available, ``0`` otherwise.
    """
    if pd.isna(val):
        return 0
    text = str(val).strip().lower()
    if text in ("yes"):
        return 1
    return 0


def load_availability_objects_from_csv(
    csv_path: str,
    use_real_names: bool = True,
) -> Tuple[List[Candidate], List[str]]:
    """Load candidate availability data from a CSV file.

    The CSV is expected to have two header rows (dates and slot labels)
    followed by one row per candidate with ``"yes"``/``"no"`` availability
    values.

    :param csv_path: Path to the applicants availability CSV.
    :param use_real_names: When ``True`` (default), use column 0 as the
        candidate name.  Falls back to ``cand{i+1}`` if the cell is blank.
        Set to ``False`` to always use anonymous identifiers.
    :returns: A tuple of ``(candidates, time_slots)`` where *candidates* is
        a list of :class:`~data_models.models.Candidate` objects and
        *time_slots* is the ordered list of timeslot labels.
    """
    df = pd.read_csv(csv_path, header=None)
    date_row = df.iloc[0, 1:].tolist()
    slot_row = df.iloc[1, 1:].tolist()

    time_slots = [
        f"{date} {_normalize_slot_label(slot)}"
        for date, slot in zip(date_row, slot_row)
    ]

    candidates = []
    for i in range(len(df) - 2):
        raw_name = df.iloc[i + 2, 0]
        if use_real_names and not pd.isna(raw_name) and str(raw_name).strip():
            cid = str(raw_name).strip()
        else:
            cid = f"cand{i+1}"
        cand = Candidate(id=cid)
        for j, slot in enumerate(time_slots):
            val = df.iloc[i+2, j+1]
            cand.availability[slot] = _parse_availability_value(val)
        candidates.append(cand)
    return candidates, time_slots


def load_staff_objects_from_csv(csv_path: str) -> Tuple[List[Staff], List[str]]:
    """Load staff availability data from a CSV and build Staff objects.

    The CSV layout mirrors the candidate availability CSV: two header rows
    (dates and slot labels) followed by one row per staff member.  Staff
    whose name starts with ``"lead"`` have their ``is_lead`` flag set.

    :param csv_path: Path to the staff availability CSV.
    :returns: A tuple of ``(staff_objs, time_slots)`` where *staff_objs* is
        a list of :class:`~data_models.models.Staff` objects and
        *time_slots* is the ordered list of timeslot labels.
    """
    df = pd.read_csv(csv_path, header=None)
    raw_date_row = df.iloc[0, 1:].tolist()
    date_row = [str(d).split()[0] for d in raw_date_row]
    slot_row = df.iloc[1, 1:].tolist()

    time_slots = [
        f"{date} {_normalize_slot_label(slot)}"
        for date, slot in zip(date_row, slot_row)
    ]

    staff_objs = []
    for i in range(2, len(df)):
        sname = df.iloc[i, 0]
        staff = Staff(id=sname)
        staff.is_lead = str(sname).startswith("lead")
        for j, slot in enumerate(time_slots):
            val = df.iloc[i][j + 1]
            staff.availability[slot] = _parse_availability_value(val)
        staff_objs.append(staff)
    return staff_objs, time_slots


def load_forbidden_pairs_from_csv(csv_path: str) -> Set[Tuple[str, str]]:
    """Load forbidden candidate–staff pairings from a CSV file.

    Supports two CSV formats:

    **Simple format** (``candidate_id,staff_id`` columns)::

        candidate_id,staff_id
        Alice,Prof X
        Bob,Prof Y

    **Real-data format** (``Surname``, ``First name(s)``,
    ``Potential Supervisors`` columns — the supervisors column may list
    multiple names separated by commas)::

        Applicant,,,Comments,,Interview,
        Surname,First name(s),Potential Supervisors,,,,
        Fenwick,Maya,Nora Whitlock,,,,

    The candidate ID is constructed as ``"First name(s) Surname"`` to match
    the naming convention used by :func:`load_availability_objects_from_csv`.

    :param csv_path: Path to the forbidden-pairs CSV file.
    :returns: A set of ``(candidate_id, staff_id)`` tuples.
    :raises ValueError: If the CSV has fewer than 3 columns and lacks the
        simple-format headers.
    """
    df = pd.read_csv(csv_path)
    cols = set(df.columns)

    if "candidate_id" in cols and "staff_id" in cols:
        pairs: Set[Tuple[str, str]] = set()
        for _, row in df.iterrows():
            cand = row["candidate_id"]
            staff = row["staff_id"]
            if pd.isna(cand) or pd.isna(staff):
                continue
            c = str(cand).strip()
            s = str(staff).strip()
            if c and s:
                pairs.add((c, s))
        return pairs

    if len(df.columns) < 3:
        raise ValueError(
            "forbidden_pairs CSV must have either 'candidate_id,staff_id' columns "
            "or at least 3 columns (Surname, First name(s), Potential Supervisors). "
            f"Found columns: {list(df.columns)}"
        )
    start_row = 0
    first_val = str(df.iloc[0, 0]).strip().lower() if len(df) > 0 else ""
    if first_val in ("surname",):
        start_row = 1

    pairs = set()
    for i in range(start_row, len(df)):
        surname_raw = df.iloc[i, 0]
        first_raw = df.iloc[i, 1]
        supervisors_raw = df.iloc[i, 2]

        if pd.isna(surname_raw) or pd.isna(first_raw):
            continue
        surname = str(surname_raw).strip()
        first = str(first_raw).strip()
        if not surname or not first:
            continue

        cid = f"{first} {surname}"

        if pd.isna(supervisors_raw):
            continue
        supervisors_str = str(supervisors_raw).strip()
        if not supervisors_str:
            continue

        for sup in supervisors_str.split(","):
            s = sup.strip()
            if s:
                pairs.add((cid, s))

    return pairs


def parse_forbidden_pairs_inline(text: str) -> Set[Tuple[str, str]]:
    """Parse forbidden pairs from an inline colon-separated string.

    Accepted format: ``"candidate1:staff1, candidate2:staff2, ..."``.
    Whitespace around names and separators is stripped.

    :param text: The inline forbidden-pairs string.
    :returns: A set of ``(candidate_id, staff_id)`` tuples.
    """
    pairs: Set[Tuple[str, str]] = set()
    if not text or not text.strip():
        return pairs
    for token in text.split(","):
        token = token.strip()
        if ":" not in token:
            continue
        parts = token.split(":", 1)
        c = parts[0].strip()
        s = parts[1].strip()
        if c and s:
            pairs.add((c, s))
    return pairs


def objects_to_solver_inputs_from_models(
    candidates: List[Candidate],
    staff: List[Staff],
    lead_ids: List[str] = None,
    forbidden_pairs: Set[Tuple[str, str]] = None,
) -> Tuple[List[str], List[str], Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, List[str]], Set]:
    """Convert model objects to the flat dictionaries expected by the solver.

    :param candidates: List of :class:`~data_models.models.Candidate` objects.
    :param staff: List of :class:`~data_models.models.Staff` objects.
    :param lead_ids: Optional explicit list of staff IDs to treat as leads.
        When provided, overrides the ``is_lead`` flag on Staff objects.
        Pass ``[]`` to disable lead requirements.  When ``None``, falls back
        to ``Staff.is_lead``.
    :param forbidden_pairs: Optional set of ``(candidate_id, staff_id)``
        tuples the solver must not co-assign.
    :returns: A 6-tuple of ``(candidate_ids, staff_ids,
        candidate_availability, staff_availability, required_staff,
        forbidden_pairs_set)``.
    """
    candidate_ids = [c.id for c in candidates]
    staff_ids = [s.id for s in staff]

    avail = {c.id: c.availability for c in candidates}
    staff_avail = {s.id: s.availability for s in staff}

    if lead_ids is None:
        leads = [s.id for s in staff if s.is_lead]
    else:
        staff_id_set = {s.id for s in staff}
        leads = [lid for lid in lead_ids if lid in staff_id_set]

    required_staff = {c.id: list(leads) for c in candidates}

    fp = set(forbidden_pairs) if forbidden_pairs else set()
    return candidate_ids, staff_ids, avail, staff_avail, required_staff, fp


def load_prev_schedule_from_csv(csv_path: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Load a previous schedule from a CSV file.

    Expected CSV schema::

        candidate_id,timeslot_id,staff_ids
        cand1,2025-04-01 09:00-09:45,"s1;s2"
        cand2,2025-04-01 09:45-10:30,"s2;s3"

    :param csv_path: Path to the prev_schedule CSV file.
    :returns: A tuple of ``(candidate_to_slot, prev_staff_assignment)`` where
        *candidate_to_slot* maps ``candidate_id`` → ``timeslot_id`` and
        *prev_staff_assignment* maps ``timeslot_id`` → list of staff IDs.
    :raises ValueError: If required columns are missing, values are empty,
        or duplicate candidate IDs are found.
    """
    df = pd.read_csv(csv_path)

    required_cols = {"candidate_id", "timeslot_id", "staff_ids"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"prev_schedule CSV missing required columns: {sorted(missing)}"
        )

    candidate_to_slot: Dict[str, str] = {}
    prev_staff_assignment: Dict[str, List[str]] = {}

    for i, row in df.iterrows():
        cand_raw = row["candidate_id"]
        slot_raw = row["timeslot_id"]
        staff_raw = row["staff_ids"]

        cand = str(cand_raw).strip() if not pd.isna(cand_raw) else ""
        slot = str(slot_raw).strip() if not pd.isna(slot_raw) else ""
        staff_str = str(staff_raw).strip() if not pd.isna(staff_raw) else ""

        if not cand:
            raise ValueError(
                f"Empty candidate_id at row {i + 2} in {csv_path!r}"
            )
        if not slot:
            raise ValueError(
                f"Empty timeslot_id for candidate {cand!r} at row {i + 2} in {csv_path!r}"
            )
        if not staff_str:
            raise ValueError(
                f"Empty staff_ids for candidate {cand!r} at row {i + 2} in {csv_path!r}"
            )

        staff_ids = [s.strip() for s in staff_str.split(";") if s.strip()]
        if not staff_ids:
            raise ValueError(
                f"No valid staff_ids parsed for candidate {cand!r} at row {i + 2} in {csv_path!r}"
            )

        if cand in candidate_to_slot:
            raise ValueError(
                f"Duplicate candidate_id {cand!r} in prev_schedule CSV {csv_path!r}"
            )

        candidate_to_slot[cand] = slot

        existing = prev_staff_assignment.get(slot, [])
        combined = existing + [s for s in staff_ids if s not in existing]
        prev_staff_assignment[slot] = combined

    return candidate_to_slot, prev_staff_assignment


def normalize_slot(date, slot):
    """Normalise a ``"date slot"`` pair into a canonical ``"YYYY-MM-DD HH:MM"`` string.

    :param date: Date portion of the slot label.
    :param slot: Time portion of the slot label.
    :returns: Normalised slot string.
    """
    try:
        dt = datetime.strptime(f"{date} {slot}", "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return f"{date.strip()} {_normalize_slot_label(slot)}"


def unify_slots(slots_A, slots_B):
    """Compute the union of two timeslot lists after normalisation.

    Ensures timeslots from different sources (e.g. staff vs. candidate CSVs)
    are reconciled into a single canonical set.

    :param slots_A: First list of timeslot label strings.
    :param slots_B: Second list of timeslot label strings.
    :returns: A list of unique normalised timeslot strings.
    """
    norm_A = {normalize_slot(*s.split(' ', 1)): s for s in slots_A}
    norm_B = {normalize_slot(*s.split(' ', 1)): s for s in slots_B}
    unified = list(set(norm_A.keys()) | set(norm_B.keys()))
    return unified
