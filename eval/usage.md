# Harness Usage Examples

## Basic Harness Commands

```bash
# Demo mode (default)
python3 -m eval.harness --persist --produce-plots

# Demo mode with custom params
python3 -m eval.harness --mode demo --base-dir data/my_run --random-seed 42 --strategies reschedule_from_scratch,change_penalty

# Synthetically generated data:
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 --slots-per-day 3 --dataset-complexity simple --persist

# Synthetic with noise (staff becoming unavailable)
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist \
  --noise-type staff_unavailable --noise-num-people 2 --noise-intensity 1

# Synthetic with candidate removal noise
python3 -m eval.harness --mode synthetic --num-candidates 10 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist \
  --noise-type candidate_removal --noise-num-people 2

# Run multiple noise intensities (for robustness testing)
for intensity in 1 2 3 4 5; do
  python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
    --slots-per-day 3 --persist --base-dir data/noise_sweep \
    --noise-type staff_unavailable --noise-num-people 2 --noise-intensity $intensity \
    --random-seed 42
done

# Robustness mode
python3 -m eval.harness --mode robustness --applicantscsv data/applicants_availabilities.csv --staffcsv data/staff_aligned_45min.csv --iterations 10
```

## Noise Types

The harness supports multiple noise types to simulate perturbations:

- `staff_unavailable`: Make staff members unavailable for certain slots
  - `--noise-num-people N`: Number of staff to affect
  - `--noise-intensity N`: Slots per staff to make unavailable
  
- `candidate_unavailable`: Make candidates unavailable for certain slots
  - `--noise-num-people N`: Number of candidates to affect
  - `--noise-intensity N`: Slots per candidate to make unavailable
  
- `candidate_removal`: Remove candidates from the problem
  - `--noise-num-people N`: Number of candidates to remove (or fraction if 0 < N < 1)
  
- `staff_removal`: Remove staff from the problem
  - `--noise-num-people N`: Number of staff to remove (or fraction if 0 < N < 1)

## Robustness Testing Workflow

To find optimal rescheduling strategies under varying degrees of perturbation:

```bash
# 1. Generate baseline (no noise)
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist --base-dir data/robustness_study --random-seed 42

# 2. Generate with low noise
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist --base-dir data/robustness_study \
  --noise-type staff_unavailable --noise-num-people 1 --noise-intensity 1 --random-seed 42

# 3. Generate with medium noise
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist --base-dir data/robustness_study \
  --noise-type staff_unavailable --noise-num-people 2 --noise-intensity 2 --random-seed 42

# 4. Generate with high noise
python3 -m eval.harness --mode synthetic --num-candidates 8 --num-staff 4 --num-days 2 \
  --slots-per-day 3 --persist --base-dir data/robustness_study \
  --noise-type staff_unavailable --noise-num-people 3 --noise-intensity 3 --random-seed 42

# 5. Plot and compare
python3 -m eval.produce_plots --base data/robustness_study --out outputs/all_runs
```

Compare the strategy performance across noise levels to identify which strategies are most robust.

## For Metrics
```bash
python3 -m eval.harness --mode synthetic --noise-type staff_unavailable --persist --base-dir /tmp/results
# Generates: /tmp/results/synthetic-xxxx/metrics.csv
```