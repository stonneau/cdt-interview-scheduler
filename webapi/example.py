"""In-memory generator of an anonymised CDT-scale example (no files needed).

Same shape and scale as the 2026 CDT cycle in the UG4 report: 33 applicants,
16 staff of which 3 leads, 10 slots/day, 16 weekdays = 160 slots.
``examples/make_cdt_example_data.py`` writes these texts to disk.
"""

import csv
import io
import random
from datetime import date, timedelta

# Slot labels as exported by the Doodle poll: "H" or "H.MM" (hour, then minutes).
SLOT_LABELS = ["9", "9.45", "10.3", "11.15", "1", "1.45", "2.3", "3.15", "4", "4.45"]


def interview_days(start, n_days):
    """Return the next ``n_days`` weekdays starting from ``start``."""
    days, d = [], start
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def availability_csv(names, days, p_yes, rng, bad_day_prob=0.0):
    """Two-header-row availability CSV text (dates row, slot-label row)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([""] + [d.isoformat() for d in days for _ in SLOT_LABELS])
    w.writerow([""] + SLOT_LABELS * len(days))
    for name in names:
        row = [name]
        for _ in days:
            bad = rng.random() < bad_day_prob   # correlated "bad day"
            for _ in SLOT_LABELS:
                p = 0.1 if bad else p_yes
                row.append("Yes" if rng.random() < p else "No")
        w.writerow(row)
    return buf.getvalue()


def make_example(seed=7, n_candidates=33, n_staff=16, n_leads=3, n_days=16):
    """Return ``{"applicants": csv, "staff": csv, "forbidden": csv}`` texts."""
    rng = random.Random(seed)
    days = interview_days(date(2026, 3, 11), n_days)
    candidates = [f"Candidate-{i:02d}" for i in range(1, n_candidates + 1)]
    # Leads MUST be named "lead..." -- that prefix is how the loader detects them.
    leads = [f"lead{i}" for i in range(1, n_leads + 1)]
    others = [f"Staff-{i:02d}" for i in range(1, n_staff - n_leads + 1)]

    applicants = availability_csv(candidates, days, 0.45, rng)
    staff = availability_csv(leads + others, days, 0.55, rng, bad_day_prob=0.2)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["candidate_id", "staff_id"])
    for c in rng.sample(candidates, 8):    # supervisor / candidate conflicts
        w.writerow([c, rng.choice(others)])
    return {"applicants": applicants, "staff": staff, "forbidden": buf.getvalue()}
