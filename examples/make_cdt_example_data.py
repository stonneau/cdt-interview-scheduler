"""Generate an anonymised, CDT-scale example dataset (``data/cdt_example/``).

The real CDT availability polls contain personal data and are therefore not
distributed.  This script produces files with the *same format and scale*
as the 2026 CDT admissions cycle described in the UG4 report (33 candidates,
16 staff of which 3 leads, 10 slots/day, ~160 slots), so that the full
workflow can be tried end to end.

Usage::

    python examples/make_cdt_example_data.py [--seed 7] [--out data/cdt_example]
"""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

# Slot labels as exported by the Doodle poll: "H" or "H.MM" (hour, then minutes).
# Afternoon hours are written 1, 2, 3, 4 (not 13, 14, ...).  Both CSVs must use
# the same convention, which is all the loader needs.
SLOT_LABELS = ["9", "9.45", "10.3", "11.15", "1", "1.45", "2.3", "3.15", "4", "4.45"]


def interview_days(start: date, n_days: int):
    """Return the next ``n_days`` weekdays starting from ``start``."""
    days, d = [], start
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def write_availability(path, names, days, p_yes, rng, bad_day_prob=0.0):
    """Write a two-header-row availability CSV (dates row, slot-label row)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([""] + [d.isoformat() for d in days for _ in SLOT_LABELS])
        w.writerow([""] + SLOT_LABELS * len(days))
        for name in names:
            row = [name]
            for _ in days:
                # Correlated "bad day": most slots of that day become unavailable.
                bad = rng.random() < bad_day_prob
                for _ in SLOT_LABELS:
                    p = 0.1 if bad else p_yes
                    row.append("Yes" if rng.random() < p else "No")
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/cdt_example")
    ap.add_argument("--candidates", type=int, default=33)
    ap.add_argument("--staff", type=int, default=16)
    ap.add_argument("--leads", type=int, default=3)
    ap.add_argument("--days", type=int, default=16)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    days = interview_days(date(2026, 3, 11), args.days)

    candidates = [f"Candidate-{i:02d}" for i in range(1, args.candidates + 1)]
    # Leads MUST be named "lead..." -- that prefix is how the loader detects them.
    leads = [f"lead{i}" for i in range(1, args.leads + 1)]
    others = [f"Staff-{i:02d}" for i in range(1, args.staff - args.leads + 1)]

    write_availability(out / "applicants_availabilities.csv", candidates, days, 0.45, rng)
    write_availability(out / "staff_availabilities.csv", leads + others, days, 0.55, rng,
                       bad_day_prob=0.2)

    # Supervisor / candidate conflicts: that supervisor must not sit on the panel.
    with open(out / "forbidden_pairs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "staff_id"])
        for c in rng.sample(candidates, 8):
            w.writerow([c, rng.choice(others)])
    print(f"Wrote example data to {out}/ "
          f"({len(candidates)} candidates, {len(leads) + len(others)} staff, "
          f"{len(days) * len(SLOT_LABELS)} slots)")


if __name__ == "__main__":
    main()
