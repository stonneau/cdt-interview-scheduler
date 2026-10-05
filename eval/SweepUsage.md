Run a sweep with the harness (example):
```bash
python3 -m eval.harness --mode sweep --sweep-candidate-weights 0,1,2 --sweep-staff-weights 0,1 --sweep-noise-types staff_unavailable --sweep-seeds 1,2 --sweep-out data/my_sweep.csv --num-candidates 10 --num-staff 6 --require-leads --persist
```

Compare strategies across scenarios (recommended):
```bash
# Run a structured comparison of strategies across dataset sizes,
# complexity levels, and noise conditions.
python3 -m eval.harness --mode sweep \
  --sweep-strategies change_penalty,local_repair,reschedule_from_scratch \
  --sweep-sizes small,medium \
  --sweep-complexities simple,complex \
  --sweep-seeds 0,1,2 \
  --sweep-out data/strategy_comparison.csv
```

Sweep only one strategy (useful for deep-dive analysis):
```bash
python3 -m eval.harness --mode sweep \
  --sweep-strategies change_penalty \
  --sweep-sizes small,medium,large \
  --sweep-complexities simple,medium,complex \
  --sweep-seeds 0,1,2,3,4 \
  --sweep-out data/change_penalty_sweep.csv
```

Filter noise types:
```bash
# Only staff_unavailable noise + the no-noise baseline
python3 -m eval.harness --mode sweep \
  --sweep-strategies change_penalty,local_repair \
  --sweep-noise-types none,staff_unavailable \
  --sweep-out data/staff_noise_sweep.csv
```

Plot Pareto and breakdown charts from the sweep CSV:
```bash
python3 -m eval.sweep_plots --csv data/strategy_comparison.csv --out outputs/sweep_plots
```

What the plots show:

**Pareto** – X axis: number of changed assignments (stability cost). Y axis: staff fairness variance (workload imbalance). Each point is labelled with strategy, size, complexity, noise, and seed.

**Box plot** – Distribution of changed assignments per strategy.

**Fairness bar** – Median fairness variance per strategy.

**Dimension breakdowns** – Grouped bar charts showing stability and fairness broken down by noise type, dataset size, and availability complexity. These help identify when and why a strategy starts breaking.

CSV output columns:

| Column | Description |
|--------|-------------|
| `strategy` | Rescheduling strategy name |
| `size_label` | Dataset size preset (small/medium/large/custom) |
| `complexity` | Availability complexity (simple/medium/complex) |
| `num_candidates` | Number of candidates in the dataset |
| `num_staff` | Number of staff members |
| `num_slots` | Total number of time slots |
| `noise_type` | Type of noise applied (none/staff_unavailable/candidate_unavailable) |
| `noise_intensity` | Number of slots affected per person |
| `noise_num_people` | Number of people affected by noise |
| `seed` | Random seed for reproducibility |
| `initial_status` | Solver status for initial schedule (OPTIMAL/FEASIBLE) |
| `reschedule_status` | Solver status after rescheduling |
| `changed_assignments` | Number of candidates moved to different slots |
| `prop_changed` | Proportion of candidates that changed |
| `staff_fairness_variance` | Variance of staff workload distribution |
| `staff_fairness_gini` | Gini coefficient of staff workload |
| `solve_time_seconds` | Time taken for the reschedule solve |