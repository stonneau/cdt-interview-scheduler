"""Generate an anonymised, CDT-scale example dataset (``data/cdt_example/``).

The real CDT availability polls contain personal data and are therefore not
distributed.  This script produces files with the *same format and scale*
as the 2026 CDT admissions cycle described in the UG4 report (33 candidates,
16 staff of which 3 leads, 10 slots/day, ~160 slots), so that the full
workflow can be tried end to end.  The generator itself lives in
``webapi/example.py`` (the web app uses it too, in memory).

Usage::

    python examples/make_cdt_example_data.py [--seed 7] [--out data/cdt_example]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webapi.example import make_example  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/cdt_example")
    ap.add_argument("--candidates", type=int, default=33)
    ap.add_argument("--staff", type=int, default=16)
    ap.add_argument("--leads", type=int, default=3)
    ap.add_argument("--days", type=int, default=16)
    args = ap.parse_args()

    texts = make_example(args.seed, args.candidates, args.staff, args.leads, args.days)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "applicants_availabilities.csv").write_text(texts["applicants"], newline="")
    (out / "staff_availabilities.csv").write_text(texts["staff"], newline="")
    (out / "forbidden_pairs.csv").write_text(texts["forbidden"], newline="")
    print(f"Wrote example data to {out}/ ({args.candidates} candidates, {args.staff} staff, "
          f"{args.days * 10} slots)")


if __name__ == "__main__":
    main()
