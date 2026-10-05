"""CSV loading, Pareto-point building, and orchestration for sweep analysis.

Provides :func:`load_sweep_csv` to read sweep results, :func:`build_pareto_points`
to convert rows into Pareto-ready dicts, :func:`plot_pareto_from_csv` to
produce the full suite of plots, and :func:`main` as the CLI entry point.
"""
import csv
from pathlib import Path
from typing import List, Dict, Any

from eval.colour_palette import apply_colorblind_cycle
from eval.produce_plots import plot_pareto, plot_pareto_regions, plot_pareto_regions_zoomed
from eval.sweep_plots._helpers import _safe_float
from eval.sweep_plots._metric_plots import (
    plot_boxplot_changed, plot_fairness_bar, plot_solve_time_bar,
    plot_prop_changed_boxplot, plot_gini_bar, plot_staff_load_range,
    plot_infeasibility_bar, plot_metric_vs_noise_level,
)
from eval.sweep_plots._dimension_plots import (
    plot_by_noise, plot_by_noise_level, plot_by_size,
    plot_by_complexity, plot_by_penalty_scale,
)
from eval.sweep_plots._pareto_plots import (
    plot_pareto_by_penalty_scale, plot_pareto_ps_fw_interaction,
)
from eval.sweep_plots._summary import (
    generate_summary_tables, generate_recommendation_table,
)


def load_sweep_csv(csv_path: str) -> List[Dict[str, Any]]:
    """Read a sweep results CSV and return a list of row dicts.

    When the ``optimal`` column is missing but ``reschedule_status`` is
    present, the ``optimal`` value is derived on-the-fly so that older
    CSVs remain usable without re-running experiments.

    Parameters
    ----------
    csv_path : str
        Path to the CSV file.

    Returns
    -------
    list of dict
        Each dict represents one row from the CSV.
    """
    rows = []
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            if "optimal" not in r and "reschedule_status" in r:
                r["optimal"] = "1" if r["reschedule_status"] == "OPTIMAL" else "0"
            rows.append(r)
    return rows


def build_pareto_points(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert sweep CSV rows into Pareto-plot point dicts.

    Each returned dict contains ``num_changed``, ``prop_changed``,
    ``fairness_var``, ``label``, ``strategy``, ``penalty_scale``, and
    ``fairness_weight`` keys.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.

    Returns
    -------
    list of dict
        Pareto-ready point dicts.
    """
    points = []
    for r in rows:
        num_changed = _safe_float(r.get("changed_assignments") or r.get("num_changed") or 0)
        fairness = _safe_float(r.get("staff_fairness_variance") or r.get("fairness_var") or 0)

        strategy = r.get("strategy") or "unknown"
        size = r.get("size_label", "")
        complexity = r.get("complexity", "")
        noise = r.get("noise_type", "")
        seed = r.get("seed", "")
        penalty_scale = r.get("penalty_scale", "")
        fairness_weight = r.get("fairness_weight", "")

        prop_changed = _safe_float(r.get("prop_changed") or 0)

        label = f"{strategy}|size={size}|cx={complexity}|noise={noise}|seed={seed}"
        points.append({
            "num_changed": num_changed,
            "prop_changed": prop_changed,
            "fairness_var": fairness,
            "label": label,
            "strategy": strategy,
            "penalty_scale": penalty_scale,
            "fairness_weight": fairness_weight,
        })
    return points


def plot_pareto_from_csv(csv_path: str, out_dir: str, *, export_latex: bool = False) -> None:
    """Produce the full suite of sweep plots from a CSV file.

    Reads the sweep CSV, builds Pareto points, and generates all charts,
    dimension breakdowns, summary tables, and recommendation tables.

    Parameters
    ----------
    csv_path : str
        Path to the sweep results CSV file.
    out_dir : str
        Directory to write all output files (PNGs, CSVs, etc.).
    export_latex : bool
        When ``True``, also export LaTeX versions of summary tables.

    Returns
    -------
    None
    """
    apply_colorblind_cycle()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_sweep_csv(csv_path)
    points = build_pareto_points(rows)
    out_path = out / "pareto.png"
    plot_pareto(points, out_path)
    plot_pareto_regions(points, out / "pareto_regions.png")
    plot_pareto_regions(points, out / "pareto_regions_prop.png", x_key="prop_changed")
    plot_pareto_regions_zoomed(points, out / "pareto_regions_zoomed.png")
    # Core summary plots
    plot_boxplot_changed(rows, out_dir)
    plot_fairness_bar(rows, out_dir)
    plot_solve_time_bar(rows, out_dir)
    plot_prop_changed_boxplot(rows, out_dir)
    plot_gini_bar(rows, out_dir)
    plot_staff_load_range(rows, out_dir)
    plot_infeasibility_bar(rows, out_dir)
    # Noise-level progression (line) plots
    plot_metric_vs_noise_level(rows, out_dir)
    # Dimension breakdowns
    plot_by_noise(rows, out_dir)
    plot_by_noise_level(rows, out_dir)
    plot_by_size(rows, out_dir)
    plot_by_complexity(rows, out_dir)
    plot_by_penalty_scale(rows, out_dir)
    # Pareto plot coloured by penalty_scale
    plot_pareto_by_penalty_scale(points, out_dir)
    plot_pareto_by_penalty_scale(points, out_dir, x_key="prop_changed", suffix="_prop")
    # Combined penalty_scale x fairness_weight interaction plot
    plot_pareto_ps_fw_interaction(points, out_dir)
    plot_pareto_ps_fw_interaction(points, out_dir, x_key="prop_changed", suffix="_prop")
    # Summary lookup tables
    generate_summary_tables(rows, out_dir, export_latex=export_latex)
    # Strategy recommendation table
    generate_recommendation_table(csv_path, out_dir, export_latex=export_latex)


def main():
    """CLI entry point for generating sweep plots.

    Parses ``--csv``, ``--out``, and ``--export-latex`` arguments and
    delegates to :func:`plot_pareto_from_csv`.

    Returns
    -------
    None
    """
    import argparse

    parser = argparse.ArgumentParser(description="Plot sweep CSV results (Pareto + breakdowns)")
    parser.add_argument("--csv", required=True, help="Sweep CSV file produced by sweep_runner")
    parser.add_argument("--out", required=True, help="Output directory for plots")
    parser.add_argument("--export-latex", action="store_true",
                        help="Export summary tables as LaTeX .tex files alongside CSVs")
    args = parser.parse_args()

    plot_pareto_from_csv(args.csv, args.out, export_latex=args.export_latex)
