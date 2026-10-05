# This is meant to be a file to test our algorithm against randomly generated noise
# This script allows you to load the real CSV data, run Monte Carlo simulations of disruptions, and export the metrics to a CSV file.

import argparse
import pandas as pd
import random
import copy
import sys
import os

from scheduler.solver import solve_initial_schedule
from scheduler import strategies
from eval.metrics import ScheduleMetrics
from data_models.loaders import (
    load_availability_objects_from_csv,
    load_staff_objects_from_csv,
    objects_to_solver_inputs_from_models,
    unify_slots,
    load_prev_schedule_from_csv,
)

def solve_model(
    candidates,
    time_slots,
    avail,
    staff,
    staff_avail,
    required_staff,
    forbidden_pairs,
    prev_schedule=None,
    prev_staff_assignment=None,
    fairness="min_max",
    staff_change_penalty_weight: int = 1,
):
    """
    Helper to run solver and return friendly dictionary formats.
    """
    data_store = {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
        "prev_schedule": prev_schedule,
        "prev_staff_assignment": prev_staff_assignment,
    }

    params = {
        "min_staff_per_slot": 2,
        "fairness": fairness,
        "staff_change_penalty_weight": staff_change_penalty_weight,
        "time_limit": 10,
    }

    schedule, metadata = solve_initial_schedule(data_store=data_store, params=params)
    if not schedule:
        return None, None
    staff_assignment = metadata.get("staff_assignment", {})
    return schedule, staff_assignment

def perturb_instance(avail, staff_avail, perturbation_type="random_staff_unavailable", intensity=1, num_staff=1):
    """
    Returns deep copies of availability dicts with random faults injected.

    - intensity: number of slots to remove per affected staff/candidate
    - num_staff: how many distinct staff to affect (only for staff perturbations)
    """
    new_avail = copy.deepcopy(avail)
    new_staff_avail = copy.deepcopy(staff_avail)

    if perturbation_type == "random_staff_unavailable":
        staff_ids = list(new_staff_avail.keys())
        if not staff_ids:
            return new_avail, new_staff_avail

        # choose up to `num_staff` distinct staff to affect
        chosen = random.sample(staff_ids, min(num_staff, len(staff_ids)))
        for target_staff in chosen:
            slots = list(new_staff_avail[target_staff].keys())
            available_slots = [t for t in slots if new_staff_avail[target_staff][t] == 1]
            if not available_slots:
                continue
            targets = random.sample(available_slots, min(intensity, len(available_slots)))
            for t in targets:
                new_staff_avail[target_staff][t] = 0
            
    elif perturbation_type == "candidate_reschedule":
        # Pick a candidate and block their preferred slots? 
        # Or just block random slots for them.
        cand_ids = list(new_avail.keys())
        if not cand_ids: return new_avail, new_staff_avail
        
        target_c = random.choice(cand_ids)
        slots = list(new_avail[target_c].keys())
        available_slots = [t for t in slots if new_avail[target_c][t] == 1]
        
        if available_slots:
            targets = random.sample(available_slots, min(intensity, len(available_slots)))
            for t in targets:
                new_avail[target_c][t] = 0

    return new_avail, new_staff_avail

def run_experiment(
    applicantscsv: str,
    staffcsv: str,
    iterations: int = 5,
    output: str = "data/robustness_results.csv",
    prev_schedule_csv: str | None = None,
    staff_change_penalty_weight: int = 1,
) -> pd.DataFrame:
    """
    Run robustness experiments programmatically.

    Parameters
    ----------
    applicantscsv : str
        Path to applicants availability CSV.
    staffcsv : str
        Path to staff availability CSV.
    iterations : int
        Number of random runs per technique.
    output : str
        Path to output CSV file.

    Returns
    -------
    pandas.DataFrame
        Results table (may be empty if no results collected).
    """
    print(f"Loading data from {applicantscsv} and {staffcsv}...")
    candidates_objs, time_slots1 = load_availability_objects_from_csv(applicantscsv)
    staff_objs, time_slots2 = load_staff_objects_from_csv(staffcsv)
    (
        candidates,
        staff,
        base_avail,
        base_staff_avail,
        required_staff,
        forbidden_pairs,
    ) = objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
    time_slots = unify_slots(time_slots1, time_slots2)

    # Optional external previous schedule (overrides baseline for Min_Disturbance)
    if prev_schedule_csv is not None:
        external_prev_schedule, external_prev_staff_assignment = load_prev_schedule_from_csv(
            prev_schedule_csv
        )
    else:
        external_prev_schedule = None
        external_prev_staff_assignment = None

    results = []
    print(f"Starting experiment with {iterations} iterations...")

    desired = ["reschedule_from_scratch", "change_penalty", "local_repair"]
    techniques = []
    for name in desired:
        try:
            strategies.get_strategy(name)
        except KeyError:
            # not implemented
            continue
        use_prev = False if name in ("reschedule_from_scratch", "full") else True
        techniques.append((name, use_prev, "min_max"))

    for i in range(iterations):
        print(f"--- Iteration {i + 1}/{iterations} ---")

        # 1. Solve baseline (no previous info here)
        base_schedule, base_staff_assign = solve_model(
            candidates,
            time_slots,
            base_avail,
            staff,
            base_staff_avail,
            required_staff,
            forbidden_pairs,
            prev_schedule=None,
            prev_staff_assignment=None,
            fairness="min_max",
            staff_change_penalty_weight=staff_change_penalty_weight,
        )

        if not base_schedule:
            print("WARNING: Could not solve baseline schedule. Skipping iteration.")
            continue

        # 2. Create Perturbation
        p_avail, p_staff_avail = perturb_instance(
            base_avail,
            base_staff_avail,
            "random_staff_unavailable",
            intensity=10,
            num_staff=25,
        )

        # 3. Run each technique
        for tech_name, use_prev, fairness_mode in techniques:
            if use_prev:
                prev_sched = external_prev_schedule or base_schedule
                prev_staff = external_prev_staff_assignment or base_staff_assign
            else:
                prev_sched = None
                prev_staff = None

            new_schedule, new_staff_assign = solve_model(
                candidates,
                time_slots,
                p_avail,
                staff,
                p_staff_avail,
                required_staff,
                forbidden_pairs,
                prev_schedule=prev_sched,
                prev_staff_assignment=prev_staff,
                fairness=fairness_mode,
                staff_change_penalty_weight=staff_change_penalty_weight,
            )

            if not new_schedule:
                print(f"Technique {tech_name}: No solution found.")
                continue

            # 4. Collect Metrics
            metrics = ScheduleMetrics(
                new_schedule,
                base_schedule,
                new_staff_assign,
                time_slots,
            )
            stab = metrics.stability_metrics()
            rob = metrics.robustness_metrics()

            row = {
                "iteration": i + 1,
                "technique": tech_name,
                "perturbation": "random_staff_unavailable",
                "changed_assignments": stab["changed_assignments"],
                "temporal_deviation": stab["temporal_deviation_minutes"],
                "feasibility_ratio": rob["feasibility_ratio"],
                "fairness_variance": rob["staff_fairness_variance"],
                "slack_utilisation": rob["slack_utilisation"],
            }

            results.append(row)
            print(
                f"{tech_name}: {int(stab['changed_assignments'])} changes, "
                f"{int(stab['temporal_deviation_minutes'])}min deviation"
            )

    # Save to CSV
    if results:
        df = pd.DataFrame(results)
        df.to_csv(output, index=False)
        print(f"\nExperiment complete. Results saved on {output}")
        print(
            df.groupby("technique")[
                ["changed_assignments", "temporal_deviation", "fairness_variance"]
            ].mean()
        )
        return df

    print("\nNo results collected.")
    return pd.DataFrame(columns=[
        "iteration",
        "technique",
        "perturbation",
        "changed_assignments",
        "temporal_deviation",
        "feasibility_ratio",
        "fairness_variance",
        "slack_utilisation",
    ])


def main() -> None:
    """
    CLI entrypoint for robustness experiments.

    This wraps `run_experiment` with argparse parsing so it can be run as a script.
    """
    parser = argparse.ArgumentParser(description="Run robustness experiments")
    parser.add_argument("--applicantscsv", type=str, required=True)
    parser.add_argument("--staffcsv", type=str, required=True)
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of random runs per technique",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/robustness_results.csv",
    )
    parser.add_argument(
        "--prev_schedule",
        type=str,
        default=None,
        help=(
            "Optional path to prev_schedule.csv (candidate_id,timeslot_id, panel_id). "
            "If provided, used as the previous schedule for Min_Disturbance."
        ),
    )
    parser.add_argument(
        "--staff-change-penalty-weight",
        type=int,
        default=1,
        help="Weight for penalising staff changes in robustness experiments.",
    )
    args = parser.parse_args()

    run_experiment(
        applicantscsv=args.applicantscsv,
        staffcsv=args.staffcsv,
        iterations=args.iterations,
        output=args.output,
        prev_schedule_csv=args.prev_schedule,
        staff_change_penalty_weight=args.staff_change_penalty_weight,
    )


if __name__ == "__main__":
    main()