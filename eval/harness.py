"""
Harness: CLI orchestrator for running experiments.
Dispatches to demo_small, robustness_experiment, and plotting utilities.
"""

from typing import Any, Dict
import argparse
import subprocess
from pathlib import Path

from eval.experiments.demo_small import run_demo_small, run_generated_demo
from eval.experiments.demo_actual_data import run_actual_data_demo
from eval.experiments.robustness_experiment import run_experiment
from eval.collect_metrics import collect_and_save_metrics
from eval.sweep.sweep_runner import run_sweep
from eval.sweep.sweep_scenarios import strategy_comparison_iter
import itertools


def main() -> None:
    """
    CLI entrypoint: orchestrate demo_small, robustness experiments, and plotting.
    """
    parser = argparse.ArgumentParser(
        description="Harness: run experiments (demo_small or robustness) with optional plotting"
    )
    
    # Global options
    parser.add_argument("--mode", type=str, choices=["demo", "robustness", "synthetic", "actual_data", "sweep"], default="demo",
                        help="Experiment mode: demo (demo_small), synthetic (generated), robustness, or sweep")
    parser.add_argument("--produce-plots", action="store_true", help="Generate plots after experiment")
    
    # Demo mode options
    parser.add_argument("--base-dir", type=str, default="data", help="Output base directory (each run gets nested run_id subdir)")
    parser.add_argument("--persist", action="store_true", help="Persist schedules/events")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run id (auto-generated if not provided)")
    parser.add_argument("--random-seed", type=int, default=None, help="Random seed for determinism")
    parser.add_argument("--strategies", type=str, default=None, help="Comma-separated strategy list")
    
    # Synthetic mode options
    parser.add_argument("--num-candidates", type=int, default=10, help="Number of candidates for synthetic data")
    parser.add_argument("--num-staff", type=int, default=6, help="Number of staff for synthetic data")
    parser.add_argument("--num-days", type=int, default=3, help="Number of days for synthetic data")
    parser.add_argument("--slots-per-day", type=int, default=4, help="Time slots per day for synthetic data")
    parser.add_argument("--dataset-complexity", type=str, choices=["simple", "medium", "complex"], 
                        default="simple", help="Availability complexity level for synthetic data")

    # Synthetic dataset options: require a lead per candidate
    parser.add_argument("--require-leads", action="store_true", help="Force synthetic dataset to require one lead per candidate")
    
    # Noise options (for synthetic and robustness modes)
    parser.add_argument("--noise-type", type=str, default=None,
                        help="Type of noise: staff_unavailable, candidate_unavailable, candidate_removal, staff_removal")
    parser.add_argument("--noise-num-people", type=int, default=1,
                        help="Number of people (staff/candidates) affected by noise")
    parser.add_argument("--noise-intensity", type=int, default=1,
                        help="Intensity of noise perturbation")

    # Sweep mode options
    parser.add_argument("--sweep-out", type=str, default="data/sweep_results.csv", help="CSV output for sweep results")
    parser.add_argument("--sweep-strategies", type=str, default=None, help="Comma-separated strategies to sweep (overrides --strategies)")
    parser.add_argument("--sweep-sizes", type=str, default="small,medium",
                        help="Comma-separated dataset size presets to sweep (small, medium, large)")
    parser.add_argument("--sweep-complexities", type=str, default="simple,complex",
                        help="Comma-separated availability complexity levels to sweep (simple, medium, complex)")
    parser.add_argument("--sweep-candidate-weights", type=str, default="1", help="Comma-separated candidate_change_penalty_weight values to sweep")
    parser.add_argument("--sweep-staff-weights", type=str, default="1", help="Comma-separated staff_change_penalty_weight values to sweep")
    parser.add_argument("--sweep-noise-types", type=str, default="", help="Comma-separated noise types to sweep (empty = all presets incl. baseline)")
    parser.add_argument("--sweep-penalty-scales", type=str, default=None,
                        help="Comma-separated penalty_scale values to sweep for penalty-aware strategies (e.g. '1,10,100,1000')")
    parser.add_argument("--sweep-fairness-weights", type=str, default=None,
                        help="Comma-separated fairness_weight values to sweep for penalty-aware strategies (e.g. '1,10,50,100'). "
                             "Combined with --sweep-penalty-scales to explore the penalty_scale/fairness_weight ratio surface.")
    parser.add_argument("--sweep-seeds", type=str, default="0,1,2", help="Comma-separated random seeds to run for each combination")
    parser.add_argument("--sweep-workers", type=int, default=4,
                        help="Number of parallel processes for sweep (default: 4). "
                             "Rule of thumb: sweep-workers * sweep-num-search-workers <= physical cores.")
    parser.add_argument("--sweep-num-search-workers", type=int, default=None,
                        help="Number of CP-SAT search threads per solve (default: all cores). "
                             "Set this when using --sweep-workers > 1 to avoid CPU over-subscription. "
                             "E.g. --sweep-workers 4 --sweep-num-search-workers 2 for an 8-core machine.")
    parser.add_argument("--time-limit", type=int, default=30,
                        help="Solver time limit in seconds per experiment (default: 30). "
                             "Increase for stress testing to separate timeouts from true infeasibility.")
    parser.add_argument("--sweep-dataset-type", type=str, choices=["synthetic", "csv"], default="synthetic", help="Dataset type for sweep")
    parser.add_argument("--sweep-applicantscsv", type=str, default=None, help="Applicants CSV for sweep (if dataset-type=csv)")
    parser.add_argument("--sweep-staffcsv", type=str, default=None, help="Staff CSV for sweep (if dataset-type=csv)")
    parser.add_argument("--export-latex", action="store_true",
                        help="Export sweep summary tables as LaTeX .tex files alongside CSVs")

    # Robustness mode options
    parser.add_argument("--applicantscsv", type=str, help="Path to applicants CSV")
    parser.add_argument("--staffcsv", type=str, help="Path to staff CSV")
    parser.add_argument("--iterations", type=int, default=5, help="Number of iterations for robustness")
    parser.add_argument("--output", type=str, default="data/robustness_results.csv", help="Output CSV file")
    parser.add_argument("--prev-schedule", type=str, default=None, help="Optional previous schedule CSV")
    parser.add_argument("--staff-change-penalty-weight", type=int, default=1)

    # Parallel interview options
    parser.add_argument("--allow-parallel", action="store_true",
                        help="Allow parallel interview slots (multiple candidates at the same time with different staff)")
    parser.add_argument("--max-parallel", type=int, default=2,
                        help="Maximum number of parallel interviews per time slot (default: 2, requires --allow-parallel)")
    
    args = parser.parse_args()

    if args.mode == "demo":
        _run_demo_mode(args)
    elif args.mode == "synthetic":
        _run_synthetic_mode(args)
    elif args.mode == "robustness":
        _run_robustness_mode(args)
    elif args.mode == "actual_data":
        _run_actual_data_demo(args)
    elif args.mode == "sweep":
        _run_sweep_mode(args)


def _run_demo_mode(args) -> None:
    """Run demo_small experiment."""
    strat_list = args.strategies.split(",") if args.strategies else None
    ds = run_demo_small(
        random_seed=args.random_seed,
        base_dir=args.base_dir,
        persist=args.persist,
        strategies=strat_list,
        run_id=args.run_id,
        noise_type=args.noise_type,
        noise_intensity=args.noise_intensity,
        allow_parallel=args.allow_parallel,
        max_parallel=args.max_parallel,
    )
    
    if args.persist:
        collect_and_save_metrics(base_dir=args.base_dir, run_id=ds.run_id)
    
    if args.produce_plots:
        out_dir = f"outputs/small_demos/{ds.run_id}"
        subprocess.run(
            ["python3", "-m", "eval.produce_plots", "--base", str(ds.base_dir), "--out", out_dir],
            check=False
        )
        print(f"Plots written to {out_dir}")


def _run_synthetic_mode(args) -> None:
    """Run synthetic dataset experiment."""
    strat_list = args.strategies.split(",") if args.strategies else None
    ds = run_generated_demo(
        random_seed=args.random_seed,
        base_dir=args.base_dir,
        persist=args.persist,
        strategies=strat_list,
        run_id=args.run_id,
        num_candidates=args.num_candidates,
        num_staff=args.num_staff,
        num_days=args.num_days,
        slots_per_day=args.slots_per_day,
        complexity=args.dataset_complexity,
        require_leads=args.require_leads,
        noise_type=args.noise_type,
        noise_num_people=args.noise_num_people,
        noise_intensity=args.noise_intensity,
        allow_parallel=args.allow_parallel,
        max_parallel=args.max_parallel,
    )
    
    if args.persist:
        collect_and_save_metrics(base_dir=args.base_dir, run_id=ds.run_id)
    
    base = f"data/synthetic_runs"
    if args.produce_plots:
        out_dir = f"outputs/synthetic_runs/{ds.run_id}"
        subprocess.run(
            ["python3", "-m", "eval.produce_plots", "--base", base, "--out", out_dir],
            check=False
        )
        print("Base dir is", ds.base_dir)
        print(f"Plots written to {out_dir}")


def _run_robustness_mode(args) -> None:
    """Run robustness experiment."""
    if not args.applicantscsv or not args.staffcsv:
        print("ERROR: --applicantscsv and --staffcsv are required for robustness mode")
        return
    
    run_experiment(
        applicantscsv=args.applicantscsv,
        staffcsv=args.staffcsv,
        iterations=args.iterations,
        output=args.output,
        prev_schedule_csv=args.prev_schedule,
        staff_change_penalty_weight=args.staff_change_penalty_weight,
    )
    
    if args.produce_plots:
        # Optional: plot robustness results if needed
        print("(Plot generation for robustness results not yet implemented)")

def _run_actual_data_demo(args) -> None:
    if not args.applicantscsv or not args.staffcsv:
        print("ERROR: --applicantscsv and --staffcsv are required for actual data demo")
        return
    strat_list = args.strategies.split(",") if args.strategies else None
    ds = run_actual_data_demo(
        applicants_csv=args.applicantscsv,
        staff_csv=args.staffcsv,
        base_dir=args.base_dir,
        random_seed=args.random_seed,
        persist=args.persist,
        strategies=strat_list,
        run_id=args.run_id,
        noise_type=args.noise_type,
        noise_num_people=args.noise_num_people,
        noise_intensity=args.noise_intensity,
        allow_parallel=args.allow_parallel,
        max_parallel=args.max_parallel,
    )

    if args.persist:
        collect_and_save_metrics(base_dir=args.base_dir, run_id=ds.run_id)

    base = f"data/real_runs"
    if args.produce_plots:
        out_dir = f"outputs/actual_data_runs/{ds.run_id}"
        subprocess.run(
            ["python3", "-m", "eval.produce_plots", "--base", base, "--out", out_dir],
            check=False
        )
        print("Base dir is", ds.base_dir)
        print(f"Plots written to {out_dir}")


def _run_sweep_mode(args) -> None:
    """Run a parameter sweep using `eval.sweep_runner.run_sweep`.

    When ``--sweep-dataset-type=synthetic`` (default), the sweep uses
    ``strategy_comparison_iter`` to walk through size × complexity × noise ×
    seed combinations for each strategy.  Penalty weights and custom CSV
    datasets are supported as overrides.
    """
    def _parse_list(s):
        return [x for x in (s.split(",") if s else []) if x != ""]

    # Resolve strategies
    strategies = []
    if args.sweep_strategies:
        strategies = _parse_list(args.sweep_strategies)
    elif args.strategies:
        strategies = _parse_list(args.strategies)
    # None → strategy_comparison_iter will use all distinct strategies

    seeds = [int(x) for x in _parse_list(args.sweep_seeds)]
    sizes = _parse_list(args.sweep_sizes) or None
    complexities = _parse_list(args.sweep_complexities) or None
    noise_types = _parse_list(args.sweep_noise_types) or None

    cand_weights = [float(x) for x in _parse_list(args.sweep_candidate_weights)]
    staff_weights = [float(x) for x in _parse_list(args.sweep_staff_weights)]
    penalty_scales = [int(x) for x in _parse_list(args.sweep_penalty_scales)] or None
    fairness_weights = [int(x) for x in _parse_list(args.sweep_fairness_weights)] or None

    base = "data/sweep_runs"

    if args.sweep_dataset_type == "csv":
        # CSV dataset mode – cartesian product over CLI axes
        dataset_spec = {
            "type": "csv",
            "applicants_csv": args.sweep_applicantscsv or args.applicantscsv,
            "staff_csv": args.sweep_staffcsv or args.staffcsv,
        }
        if not strategies:
            strategies = ["reschedule_from_scratch", "change_penalty", "local_repair"]

        def param_generator():
            for strat, cw, sw, seed in itertools.product(
                strategies, cand_weights or [1], staff_weights or [1], seeds or [0, 1, 2]
            ):
                noise_iter = noise_types if noise_types else [None]
                for nt in noise_iter:
                    params = {
                        "dataset": dataset_spec,
                        "strategy": strat,
                        "size_label": "csv",
                        "penalty_weights": {
                            "candidate_change_penalty_weight": cw,
                            "staff_change_penalty_weight": sw,
                        },
                        "random_seed": seed,
                        "persist": bool(args.persist),
                        "base_dir": base,
                    }
                    if args.sweep_num_search_workers is not None:
                        params["num_workers"] = args.sweep_num_search_workers
                    if nt:
                        params["noise"] = {
                            "type": nt,
                            "num_people": args.noise_num_people,
                            "intensity": args.noise_intensity,
                        }
                    yield params

        out_csv = args.sweep_out
        print(f"Running CSV sweep: strategies={strategies}, seeds={seeds}, workers={args.sweep_workers}")
        run_sweep(param_generator(), out_csv, max_workers=args.sweep_workers)
    else:
        # Synthetic dataset mode – use strategy_comparison_iter for a
        # structured grid across size, complexity, noise and seeds.
        pw = {}
        if cand_weights:
            pw["candidate_change_penalty_weight"] = cand_weights[0]
        if staff_weights:
            pw["staff_change_penalty_weight"] = staff_weights[0]

        out_csv = args.sweep_out
        print(
            f"Running sweep: strategies={strategies or 'all'}, "
            f"sizes={sizes or 'default'}, complexities={complexities or 'default'}, "
            f"noise_types={noise_types or 'all presets'}, seeds={seeds or 'default'}, "
            f"workers={args.sweep_workers}"
        )
        run_sweep(
            strategy_comparison_iter(
                strategies=strategies or None,
                sizes=sizes,
                complexities=complexities,
                noise_levels=noise_types,
                seeds=seeds or None,
                penalty_weights=pw or None,
                penalty_scale_values=penalty_scales,
                fairness_weight_values=fairness_weights,
                persist=bool(args.persist),
                base_dir=base,
                time_limit=args.time_limit,
                num_workers=args.sweep_num_search_workers,
            ),
            out_csv,
            max_workers=args.sweep_workers,
        )

    print(f"Sweep results written to {out_csv}")

    if args.produce_plots:
        from eval.sweep_plots import plot_pareto_from_csv
        plot_dir = str(Path(out_csv).parent / "plots")
        print(f"Generating plots and summary tables in {plot_dir} ...")
        plot_pareto_from_csv(out_csv, plot_dir, export_latex=args.export_latex)
        print(f"Plots written to {plot_dir}")

if __name__ == "__main__":
    main()