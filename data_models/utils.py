"""Utilities for aligning staff availability CSVs to applicant slot boundaries.

No IO is performed at import time.  All IO is performed by explicit function
calls.  Running this module as a script aligns files under ``data/`` by default.
"""

import pandas as pd
import re
from datetime import datetime
import os


def parse_time_range(time_str):
    """Parse a time-range string into a start/end time pair.

    Accepts formats like ``"9-09:45"`` or ``"09:00-09:45"``.

    :param time_str: Raw time-range string (may be NaN/None).
    :returns: A tuple of ``(start, end)`` as :class:`datetime.time` objects,
        or ``None`` if the input is NaN or cannot be parsed.
    """
    if pd.isna(time_str):
        return None
    m = re.match(r"(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?", str(time_str))
    if not m:
        return None
    h1, m1, h2, m2 = m.groups()
    start = datetime.strptime(f"{int(h1):02d}:{int(m1 or 0):02d}", "%H:%M").time()
    end = datetime.strptime(f"{int(h2):02d}:{int(m2 or 0):02d}", "%H:%M").time()
    return start, end


def time_overlaps(t1_start, t1_end, t2_start, t2_end):
    """Check whether two time intervals overlap.

    :param t1_start: Start of the first interval.
    :param t1_end: End of the first interval.
    :param t2_start: Start of the second interval.
    :param t2_end: End of the second interval.
    :returns: ``True`` if the intervals share any overlap, ``False`` otherwise.
    """
    return max(t1_start, t2_start) < min(t1_end, t2_end)


def align_staff_availabilities(applicants_csv: str, staff_csv: str, out_path: str):
    """Align staff availability columns to applicant slot boundaries.

    Reads the applicant and staff availability CSVs, maps each staff
    member's availability onto the canonical 45-minute applicant slots,
    and writes the result to *out_path*.

    :param applicants_csv: Path to the applicants availability CSV.
    :param staff_csv: Path to the staff availability CSV.
    :param out_path: Path to write the aligned staff CSV.
    :returns: The :class:`pandas.DataFrame` that was written.
    """
    applicants_df = pd.read_csv(applicants_csv)
    staff_df = pd.read_csv(staff_csv)

    applicant_time_map = {}
    for col in applicants_df.columns[1:]:
        slot = applicants_df.loc[0, col]
        if isinstance(slot, str) and "-" in slot:
            base_date = col.split(".")[0]
            parsed = parse_time_range(slot)
            applicant_time_map.setdefault(base_date, []).append(parsed)

    aligned_staff = pd.DataFrame()
    aligned_staff["Unnamed: 0"] = staff_df["Unnamed: 0"]

    for date_base, slots in applicant_time_map.items():
        staff_day_cols = [c for c in staff_df.columns if c.startswith(date_base)]
        if not staff_day_cols:
            continue

        staff_times = [parse_time_range(staff_df.loc[0, c]) for c in staff_day_cols]

        for i, parsed_slot in enumerate(slots):
            if parsed_slot is None:
                continue
            slot_start, slot_end = parsed_slot
            col_name = f"{date_base} {slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}"

            results = []
            for idx in range(1, len(staff_df)):
                available = False
                for (st_range, col) in zip(staff_times, staff_day_cols):
                    if st_range and time_overlaps(slot_start, slot_end, *st_range):
                        if str(staff_df.loc[idx, col]).strip().lower() == "yes":
                            available = True
                            break
                results.append("Yes" if available else "No")

            aligned_staff[col_name] = [""] + results

    time_header = ["NAMES"] + [applicants_df.loc[0, c] for c in applicants_df.columns[1:len(aligned_staff.columns)]]
    if len(time_header) > 0:
        aligned_staff.loc[0] = time_header

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    aligned_staff.to_csv(out_path, index=False)
    return aligned_staff


if __name__ == "__main__":
    default_applicants = os.path.join("data", "applicants_availabilities.csv")
    default_staff = os.path.join("data", "staff_availabilities.csv")
    default_out = os.path.join("data", "staff_aligned_45min.csv")

    try:
        df = align_staff_availabilities(default_applicants, default_staff, default_out)
        print(f"✅ Staff availabilities aligned and saved as '{default_out}'")
    except Exception as e:
        print(f"Failed to align staff availabilities: {e}")
