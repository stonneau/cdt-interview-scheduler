"""Summary tables and strategy recommendation table for sweep analysis.

Generates CSV lookup tables with aggregated metric values per strategy
(and optionally by dimension), plus a strategy recommendation table
that identifies the best, runner-up, and worst strategy for each metric.
"""
import csv
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

from eval.sweep_plots._helpers import (
    _safe_float, _feasible_only, _METRIC_DEFS, _MEAN_AGG_METRICS,
)

# Mapping from metric column to a human-readable priority label used in the
# recommendation table.
_METRIC_PRIORITY = {
    "changed_assignments": "Stability",
    "prop_changed": "Normalised Stability",
    "staff_fairness_variance": "Fairness",
    "staff_fairness_gini": "Fairness (Gini)",
    "infeasible": "Feasibility",
    "timeout": "Timeout Resilience",
    "solve_time_seconds": "Speed",
    "staff_load_max": "Staff Load Balance",
}


def generate_summary_tables(rows: List[Dict[str, Any]], out_dir: str, *, export_latex: bool = False):
    """Write CSV lookup tables with median metric values per strategy.

    Produces:
      - ``summary_overall.csv``   -- one row per strategy (global medians)
      - ``summary_by_size.csv``   -- one row per strategy x size
      - ``summary_by_complexity.csv`` -- one row per strategy x complexity
      - ``summary_by_noise.csv``  -- one row per strategy x noise_type
      - ``summary_by_noise_level.csv`` -- one row per strategy x noise_level
      - ``summary_by_penalty_scale.csv`` -- one row per strategy x penalty_scale
        *(only when the data contains multiple distinct penalty_scale values)*

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    out_dir : str
        Directory to write the output CSV (and optionally LaTeX) files.
    export_latex : bool
        When ``True``, also export ``.tex`` versions of each summary table.

    Returns
    -------
    None
    """
    import numpy as np

    metric_cols = [col for col, _label, _hib in _METRIC_DEFS]
    metric_labels = [label for _col, label, _hib in _METRIC_DEFS]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def _build_table(rows_subset, extra_keys=None):
        """Return list-of-dicts table with aggregated values grouped by strategy
        (and optional extra grouping keys).

        Most metrics use the *median*; binary rate metrics (like ``infeasible``)
        use the *mean* so that low-rate events are not hidden.

        Non-rate metrics (stability, fairness, etc.) are computed **only** over
        feasible rows (``infeasible == 0``) so that strategies with higher
        infeasibility rates are not artificially rewarded by the zero-valued
        metrics that infeasible/timed-out solves produce.  A ``feasible_n``
        column shows how many rows contributed to those aggregated metrics.
        """
        if extra_keys is None:
            extra_keys = []
        grouped: Dict[tuple, list] = defaultdict(list)
        for r in rows_subset:
            key = tuple([r.get("strategy", "unknown")] + [r.get(k, "") for k in extra_keys])
            grouped[key].append(r)

        table = []
        for key, grp in sorted(grouped.items()):
            row_out: Dict[str, Any] = {"strategy": key[0]}
            for i, ek in enumerate(extra_keys):
                row_out[ek] = key[i + 1]
            row_out["n"] = len(grp)
            feasible_grp = _feasible_only(grp)
            row_out["feasible_n"] = len(feasible_grp)
            for mc in metric_cols:
                if mc in _MEAN_AGG_METRICS:
                    vals = [_safe_float(r.get(mc, 0)) for r in grp]
                    row_out[mc] = round(float(np.mean(vals)), 4) if vals else ""
                else:
                    vals = [_safe_float(r.get(mc, 0)) for r in feasible_grp]
                    if not vals:
                        row_out[mc] = ""
                    else:
                        row_out[mc] = round(float(np.median(vals)), 4)
            table.append(row_out)
        return table

    def _write_csv(table, filename, extra_keys=None):
        if extra_keys is None:
            extra_keys = []
        fieldnames = ["strategy"] + extra_keys + ["n", "feasible_n"] + metric_cols
        path = out / filename
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(table)

    def _print_table(table, title, extra_keys=None):
        if extra_keys is None:
            extra_keys = []
        print(f"\n{'=' * 80}")
        print(f"  {title}")
        print(f"{'=' * 80}")
        headers = ["strategy"] + extra_keys + ["n", "feasible_n"] + metric_labels
        col_keys = ["strategy"] + extra_keys + ["n", "feasible_n"] + metric_cols
        widths = [max(len(str(h)), max((len(str(r.get(ck, ""))) for r in table), default=4)) for h, ck in zip(headers, col_keys)]
        widths = [max(w, 6) for w in widths]
        fmt = " | ".join(f"{{:<{w}}}" for w in widths)
        sep = "-+-".join("-" * w for w in widths)
        print(fmt.format(*headers))
        print(sep)
        for r in table:
            vals = [str(r.get(ck, "")) for ck in col_keys]
            print(fmt.format(*vals))

    # Overall
    t = _build_table(rows)
    _write_csv(t, "summary_overall.csv")
    _print_table(t, "Overall summary (median per strategy)")

    # By size
    t = _build_table(rows, extra_keys=["size_label"])
    _write_csv(t, "summary_by_size.csv", extra_keys=["size_label"])
    _print_table(t, "Summary by dataset size", extra_keys=["size_label"])

    # By complexity
    t = _build_table(rows, extra_keys=["complexity"])
    _write_csv(t, "summary_by_complexity.csv", extra_keys=["complexity"])
    _print_table(t, "Summary by complexity", extra_keys=["complexity"])

    # By noise
    t = _build_table(rows, extra_keys=["noise_type"])
    _write_csv(t, "summary_by_noise.csv", extra_keys=["noise_type"])
    _print_table(t, "Summary by noise type", extra_keys=["noise_type"])

    # By noise level
    t = _build_table(rows, extra_keys=["noise_level"])
    _write_csv(t, "summary_by_noise_level.csv", extra_keys=["noise_level"])
    _print_table(t, "Summary by noise level", extra_keys=["noise_level"])

    # By penalty_scale (only when a sweep was performed)
    distinct_ps = {r.get("penalty_scale", "") for r in rows}
    distinct_ps.discard("")
    if len(distinct_ps) >= 2:
        t = _build_table(rows, extra_keys=["penalty_scale"])
        _write_csv(t, "summary_by_penalty_scale.csv", extra_keys=["penalty_scale"])
        _print_table(t, "Summary by penalty scale", extra_keys=["penalty_scale"])

    # By fairness_weight (only when a sweep was performed)
    distinct_fw = {r.get("fairness_weight", "") for r in rows}
    distinct_fw.discard("")
    if len(distinct_fw) >= 2:
        t = _build_table(rows, extra_keys=["fairness_weight"])
        _write_csv(t, "summary_by_fairness_weight.csv", extra_keys=["fairness_weight"])
        _print_table(t, "Summary by fairness weight", extra_keys=["fairness_weight"])

    # Joint penalty_scale x fairness_weight (when both are swept)
    if len(distinct_ps) >= 2 and len(distinct_fw) >= 2:
        t = _build_table(rows, extra_keys=["penalty_scale", "fairness_weight"])
        _write_csv(t, "summary_by_ps_fw.csv", extra_keys=["penalty_scale", "fairness_weight"])
        _print_table(t, "Summary by penalty_scale × fairness_weight",
                     extra_keys=["penalty_scale", "fairness_weight"])

    if export_latex:
        _export_summary_latex(out)


def _export_summary_latex(out_dir):
    """Convert all ``summary_*.csv`` files in *out_dir* to LaTeX tables.

    Uses :func:`pandas.DataFrame.to_latex` when pandas is available.

    Parameters
    ----------
    out_dir : str or Path
        Directory containing the summary CSV files.

    Returns
    -------
    None
    """
    try:
        import pandas as pd
    except Exception:
        print("pandas not available; skipping LaTeX export")
        return
    out = Path(out_dir)
    for csv_path in sorted(out.glob("summary_*.csv")):
        df = pd.read_csv(csv_path)
        tex_path = csv_path.with_suffix(".tex")
        df.to_latex(tex_path, index=False, float_format="%.4f")


def generate_recommendation_table(
    csv_path: str,
    out_dir: str,
    *,
    export_latex: bool = False,
) -> str:
    """Produce a strategy recommendation table from a sweep CSV.

    For each metric the table identifies:
      - **Recommended** -- the strategy with the best aggregated score
      - **Runner-Up** -- the second-best strategy
      - **Avoid** -- the strategy with the worst aggregated score

    Parameters
    ----------
    csv_path : str
        Path to the sweep results CSV file.
    out_dir : str
        Directory to write ``recommendation_table.md`` (and optionally
        ``recommendation_table.tex``).
    export_latex : bool
        When ``True``, also export a LaTeX version.

    Returns
    -------
    str
        The recommendation table as a Markdown string.
    """
    import numpy as np
    from eval.sweep_plots._io import load_sweep_csv

    rows = load_sweep_csv(csv_path)
    if not rows:
        return ""

    strategies = sorted({r.get("strategy", "unknown") for r in rows})
    if len(strategies) < 2:
        return ""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "| Priority | Recommended Strategy | Runner-Up | Avoid |",
        "|----------|---------------------|-----------|-------|",
    ]
    table_rows: list = []

    hib_lookup = {m[0]: m[2] for m in _METRIC_DEFS}

    for metric_key, priority_label in _METRIC_PRIORITY.items():
        use_mean = metric_key in _MEAN_AGG_METRICS
        agg_fn = np.mean if use_mean else np.median

        higher_is_better = hib_lookup.get(metric_key)
        ascending = not higher_is_better

        use_feasible_only = metric_key not in _MEAN_AGG_METRICS

        scores = {}
        for strat in strategies:
            strat_rows = [r for r in rows if r.get("strategy") == strat]
            if use_feasible_only:
                strat_rows = _feasible_only(strat_rows)
            vals = [_safe_float(r.get(metric_key, 0)) for r in strat_rows]
            scores[strat] = float(agg_fn(vals)) if vals else float("inf")

        ranked = sorted(scores, key=scores.get, reverse=not ascending)
        best = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else ""
        worst = ranked[-1]

        lines.append(f"| {priority_label} | {best} | {runner_up} | {worst} |")
        table_rows.append({
            "Priority": priority_label,
            "Recommended Strategy": best,
            "Runner-Up": runner_up,
            "Avoid": worst,
        })

    md_text = "\n".join(lines) + "\n"
    (out / "recommendation_table.md").write_text(md_text)

    if export_latex:
        try:
            import pandas as pd
            df = pd.DataFrame(table_rows)
            df.to_latex(out / "recommendation_table.tex", index=False)
        except Exception:
            pass

    return md_text
