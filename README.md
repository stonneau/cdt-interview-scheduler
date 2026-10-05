# Constraint Solver – Minimally-Disruptive Academic Scheduling

> **Origin of this code.** This repository is based on the 4th-year (UG4) project
> *"Benchmarking Minimally-Disruptive Scheduling Strategies in an Academic Context"*
> carried out at the **School of Informatics, University of Edinburgh** (2025, report dated 2026)
> by **Guillermo Perfect**, supervised by Dr. Steve Tonneau. The first commit of this repository is the
> project as delivered (personal names in tests and examples were replaced by fictional ones); later commits add
> packaging, example data, documentation and a pure-Python MIP backend.
>
> **Looking to schedule CDT admissions interviews?** Go straight to [d2air.md](d2air.md): use case,
> constraints and the recommended configuration.

## Overview

This project researches and implements strategies for **minimally-disruptive** academic scheduling. It targets scenarios—such as PhD viva scheduling at a Centre for Doctoral Training (CDT)—where schedules are volatile: staff and candidates frequently become unavailable, new candidates are added, and each change should disturb as few existing assignments as possible.

The core insight is that while the literature provides many tools for *finding* a good schedule from scratch, comparatively little work addresses *incremental* or *minimally-disruptive* updates to an already-published schedule. This codebase explores that gap.

---

## The Problem

Given:
- A set of **candidates** (e.g. PhD students awaiting a viva)
- A set of **time slots** (fixed 45-minute windows across multiple days)
- A set of **staff** (academics who run the sessions, with designated *leads*)
- **Availability** matrices for both candidates and staff (binary: available / unavailable)
- Optional **required staff** per candidate (e.g., a specific lead must attend)
- Optional **forbidden pairs** (a candidate cannot be scheduled with a particular staff member)
- An optional **previous schedule** to use as a baseline

Produce a schedule that:
1. Assigns each candidate to exactly one time slot
2. Assigns 2 staff members (configurable min/max) to each occupied slot
3. Respects all availability and constraint rules
4. **Minimises disruption** to the previous schedule when one exists

---

## Architecture

```
Constraint_Solver/
├── scheduler/              # Core constraint solver
│   ├── solver.py           # High-level API (solve_initial_schedule, reschedule)
│   ├── model_builder.py    # Google OR-Tools CP-SAT model construction
│   └── strategies/         # Eight rescheduling strategy implementations
│       ├── __init__.py     # Strategy registry & re-exports
│       ├── _core.py        # Shared _solve_model helper
│       ├── _basic.py       # reschedule_from_scratch, change_penalty
│       ├── _advanced.py    # local_repair, slack_based, fairness_weighted, etc.
│       └── _plns.py        # Parallel Large Neighborhood Search
├── data_models/            # Data persistence and loading
│   ├── models.py           # Dataclass definitions (Candidate, Staff, TimeSlot, …)
│   ├── store.py            # JSON-based DataStore for persisting schedules/events
│   ├── loaders.py          # CSV loaders and model-to-solver converters
│   └── utils.py            # Staff availability alignment utilities
├── eval/                   # Evaluation framework
│   ├── experiments/        # Experiment harnesses (subpackage)
│   │   ├── demo_small.py       # Reproducible demo experiments
│   │   ├── demo_actual_data.py # Actual CSV data demo
│   │   └── robustness_experiment.py  # Monte-Carlo robustness testing
│   ├── sweep/              # Sweep framework (subpackage)
│   │   ├── sweep_runner.py     # Parameter sweep executor (parallel)
│   │   └── sweep_scenarios.py  # Preset sweep scenarios and noise configurations
│   ├── sweep_plots/        # Sweep result analysis and plotting (subpackage)
│   ├── produce_plots/      # Matplotlib visualisation (subpackage)
│   ├── metrics.py          # Stability & robustness metrics
│   ├── noise_generators.py # Perturbation generators for robustness testing
│   ├── data_generators.py  # Synthetic dataset generation
│   ├── collect_metrics.py  # Per-run metrics aggregation
│   ├── change_analyzer.py  # Human-readable change event summaries
│   ├── colour_palette.py   # Colorblind-friendly colour definitions
│   └── harness.py          # CLI orchestrator
├── tests/                  # pytest test suite (187 tests)
├── examples/               # CDT example data generator and end-to-end walkthrough
├── events/                 # Event store placeholder
├── integrations/           # Mock graph / ICS adapter stubs
├── ui/                     # User interfaces
│   ├── cli.py              # Interactive command-line interface
│   └── web_app.py          # Streamlit web dashboard
├── docs/                   # Dissertation LaTeX sources
├── Makefile                # install / test / demo / web / cdt targets
├── requirements.txt
├── d2air.md                # CDT interview-scheduling use case and configuration
└── README.md
```

---

## Installation

**Requirements:** Python **3.11 or newer** (developed and tested with 3.13), `pip`, and `make` (optional).
Works on Linux/macOS; on Windows use the manual commands below.

```bash
git clone <this repository>
cd <repository>
make install          # creates .venv and installs requirements.txt
make test             # optional: 186 tests, ~15 s
```

Without `make`:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

All commands in this README are run **from the repository root** (modules are launched with
`python -m ...`). Either activate the virtual environment first (`source .venv/bin/activate`) or
call `.venv/bin/python` explicitly, as the `make` targets do.

**Dependencies:**

| Package | Version | Purpose |
|---------|---------|---------|
| `ortools` | 9.14.6206 | CP-SAT constraint solver (Google OR-Tools) |
| `pandas` | 2.3.3 | Data loading and manipulation |
| `numpy` | 2.3.3 | Numerical operations |
| `matplotlib` | 3.10.8 | Plotting and visualisation |
| `pytest` | 9.0.2 | Test runner |
| `python-dateutil` | 2.9.0.post0 | Date parsing for time slots |
| `streamlit` | ≥1.45.0 | Interactive web UI framework |

---

## Tutorial: run the project in five minutes

```bash
make install          # 1. one-off setup
make demo             # 2. end-to-end demo on the bundled data/demo_small CSVs: initial
                      #    schedule, then 3 change events rescheduled with each strategy
make web              # 3. interactive dashboard on http://localhost:8501
./main.sh             # 4. interactive CLI on the demo data (type `help`, `quit` to leave)
make cdt              # 5. CDT-scale walkthrough: 33 candidates, 16 staff, 160 slots
```

* `make demo` runs `python -m eval.harness` (demo mode) and prints the schedules and metrics.
* `make web` is the tool the coordinator used: upload the two availability CSVs, press
  *Solve Initial Schedule*, stage changes, press *Reschedule*.
* `make cdt` uses the anonymised dataset in `data/cdt_example/` (generated by
  `examples/make_cdt_example_data.py`) and `examples/cdt_walkthrough.py`, which is also the shortest
  example of the Python API.
* For a real problem, with your own CSVs, the minimum command is:

  ```bash
  .venv/bin/python -m ui.cli --applicantscsv my_applicants.csv --staffcsv my_staff.csv \
      --fairness min_dev --interactive
  ```

  See [d2air.md](d2air.md) for the full recommended configuration.

### Constraints used by the solver — summary

Hard constraints (always enforced; otherwise the answer is `INFEASIBLE`) — details in
[The Constraint Model](#the-constraint-model):

| Constraint | Input / parameter |
|---|---|
| Each candidate in exactly one slot, at most one candidate per slot | – |
| Candidate availability | applicants CSV (`Yes` = available, everything else = unavailable) |
| Staff availability | staff CSV |
| Panel size (default exactly 2 staff per occupied slot) | `min_staff_per_slot`, `max_staff_per_slot` |
| At least one *lead* on every panel | staff IDs starting with `lead`, or an explicit list of lead IDs |
| Forbidden candidate–staff pairs | `--forbidden-pairs` / web-app field / CSV |
| Parallel interviews: a staff member is in one parallel room at a time | `--allow-parallel`, `--max-parallel` |
| Frozen slots (past interviews stay as they are) | `frozen_slots` / web-app freeze date |

Soft objectives (optimised): minimal changes to the published schedule (`penalty_scale`,
`candidate_change_penalty_weight`, `staff_change_penalty_weight`), fair staff workload (`fairness`:
`min_dev` / `min_max` / `none`, `fairness_weight`) and a small preference for non-parallel slots.

---

## Quick Start

### Run with a synthetic dataset

```bash
python -m eval.harness --mode synthetic --num-candidates 10 --num-staff 6 --persist
```

### Run a parameter sweep

```bash
python -m eval.harness --mode sweep \
    --sweep-strategies "change_penalty,local_repair,reschedule_from_scratch" \
    --sweep-seeds "1,2,3" \
    --sweep-out results/sweep.csv \
    --persist
```

### Run a penalty-scale sweep with LaTeX export

```bash
python -m eval.harness --mode sweep \
    --sweep-penalty-scales "1,10,100,1000" \
    --sweep-strategies "change_penalty,variance_minimizing" \
    --produce-plots --export-latex
```

### Run with your own CSV files

```bash
python -m eval.harness --mode actual_data \
    --applicantscsv data/my_cohort/applicants_availabilities.csv \
    --staffcsv data/my_cohort/staff_aligned_45min.csv \
    --persist
```

### Enable parallel interview slots

When you have more candidates than time slots, enable parallel interviews so multiple candidates can interview at the same physical time with different staff panels:

```bash
python -m eval.harness --mode synthetic --num-candidates 10 --num-staff 8 \
    --allow-parallel --max-parallel 2 --persist
```

### Use the Python API directly

```python
from scheduler import solver as solver_module
from data_models.store import DataStore

# Build in-memory dataset
data_store = {
    "candidates": ["cand1", "cand2", "cand3"],
    "time_slots": ["2025-04-01 08:00-08:45", "2025-04-01 08:45-09:30",
                   "2025-04-01 09:30-10:15"],
    "avail": {c: {"2025-04-01 08:00-08:45": 1,
                  "2025-04-01 08:45-09:30": 1,
                  "2025-04-01 09:30-10:15": 1} for c in ["cand1", "cand2", "cand3"]},
    "staff": ["lead1", "panel1"],
    "staff_avail": {s: {"2025-04-01 08:00-08:45": 1,
                        "2025-04-01 08:45-09:30": 1,
                        "2025-04-01 09:30-10:15": 1} for s in ["lead1", "panel1"]},
    "required_staff": {},
    "forbidden_pairs": [],
}

# Solve initial schedule
schedule, meta = solver_module.solve_initial_schedule(data_store=data_store, params={})
print(schedule)   # {"cand1": "2025-04-01 08:00-08:45", "cand2": ..., ...}

# Apply a change and reschedule
change_event = {"staff_unavailable": [("lead1", "2025-04-01 08:00-08:45")]}
new_schedule, new_meta = solver_module.reschedule(
    data_store=data_store,
    change_event=change_event,
    params={"strategy": "change_penalty"},
)
print(new_meta["num_changed_assignments"])  # minimal disruption count
```

---

## The Constraint Model

The solver is built on **Google OR-Tools CP-SAT**, a Boolean satisfiability and optimisation engine.

### Decision Variables

| Variable | Type | Meaning |
|----------|------|---------|
| `x[c, t]` | Boolean | Candidate `c` is assigned to slot `t` |
| `y[s, t]` | Boolean | Staff member `s` is assigned to slot `t` |
| `staff_counts[s]` | Integer | Number of slots staff `s` is assigned to |
| `max_load` | Integer | Maximum staff load (for fairness objective) |

### Hard Constraints

1. **Each candidate in exactly one slot:** `∑_t x[c,t] = 1` for all `c`
2. **At most one candidate per slot:** `∑_c x[c,t] ≤ 1` for all `t`
3. **Candidate availability:** `x[c,t] = 0` when `avail[c][t] = 0`
4. **Staff availability:** `y[s,t] = 0` when `staff_avail[s][t] = 0`
5. **Min/max staff per occupied slot:** if any candidate is at slot `t`, then `min_staff ≤ ∑_s y[s,t] ≤ max_staff` (default min=max=2)
6. **Required staff:** if candidate `c` requires staff `s`, then `y[s,t] ≥ x[c,t]` for all `t`
7. **Forbidden pairs:** `y[s,t] ≤ 1 - x[c,t]` for all forbidden `(c,s)` pairs and all `t`
8. **Staff exclusivity across parallel slots:** when parallel interviews are enabled, each staff member can attend at most one parallel instance at the same base time: `∑_{t ∈ group} y[s,t] ≤ 1` for each staff member and each parallel group

### Solver backends: CP-SAT or pure-Python MIP

By default the model is solved with **OR-Tools CP-SAT**. The very same model can also be solved as a
mixed-integer linear program with **HiGHS through `scipy.optimize.milp`**
(`scheduler/backends.py`, `solve_mip`), which needs only numpy/scipy and no native OR-Tools wheel
(a first step towards running the solver in a browser with Pyodide). Select it with the `backend`
parameter:

```python
schedule, meta = solver_module.solve_initial_schedule(data_store=ds, params={"backend": "mip"})
```

All strategies work with both backends. `tests/test_mip_backend.py` solves 60 scenarios (all
strategies × disruption types, fairness modes, parallel rooms, frozen slots, forbidden pairs,
infeasible instances) with both and checks that: statuses match, objective values are equal, and the
allocations are compared; when the MIP allocation differs from CP-SAT's (equal-cost ties), it is fixed
inside the real CP-SAT model, which must accept it with the same objective value.

Speed (CDT-scale example, 33 candidates / 16 staff / 160 slots, `make bench`): reschedules take
0.1–0.5 s with either backend, but the initial solve is roughly 8–12× slower with MIP (≈ 8–12 s vs
≈ 0.4–1 s), and a reschedule that adds candidates with parallel rooms can take tens of seconds.

---

### Parallel Interview Slots

When `allow_parallel=True`, the solver supports multiple candidates interviewing at the same physical time with different staff panels. This is useful when the number of candidates exceeds the number of available time slots.

**How it works:**

1. Each base time slot is expanded into `max_parallel` instances. The first keeps its original name; additional instances are suffixed `.2`, `.3`, … (e.g., `t1` → `t1`, `t1.2`).
2. Candidate and staff availability is replicated from the base slot to every parallel instance.
3. The existing "at most one candidate per slot" constraint is preserved per instance.
4. A **staff exclusivity constraint** prevents any staff member from attending more than one parallel instance at the same base time.
5. A **small objective penalty** discourages the solver from using suffix slots unnecessarily — base slots are always preferred when there is no contention.

```python
# 4 candidates, 3 slots — infeasible without parallel
schedule, meta = solve_initial_schedule(
    data_store=ds,
    params={"allow_parallel": True, "max_parallel": 2, "min_staff_per_slot": 2},
)
# c1 → t1, c2 → t2, c3 → t3, c4 → t1.2 (parallel with c1, different staff)
```

Parallel interviews are disabled by default (`allow_parallel=False`). They can be enabled via:
- **Python API:** `params={"allow_parallel": True, "max_parallel": 2}`
- **CLI:** `--allow-parallel --max-parallel 2`
- **Harness:** `--allow-parallel --max-parallel 2`
- **Web app:** Checkbox and number input in the solver parameters panel

### Objective Functions

**Without a previous schedule (fresh solve):**
- `min_max`: Minimise the maximum staff load → `min max_load`
- `variance` / `min_dev`: Minimise the sum of absolute deviations from the expected average load (linear proxy for variance)
- `none`: Feasibility only (no objective)

**With a previous schedule (rescheduling):**
- Minimise `penalty_scale × (candidate_moves + staff_changes) + fairness_weight × fairness_term`
- `candidate_moves`: penalty for each candidate assigned to a different slot than before
- `staff_changes`: penalty for each `(staff, slot)` assignment that changes from the previous schedule
- `fairness_term`: secondary fairness objective (controlled by the `fairness` parameter — `min_max`, `variance`/`min_dev`, or `none`)
- `penalty_scale` (default varies by strategy: 1000 for change_penalty/local_repair, 100 for slack_based/plns, 50 for fairness_weighted, 10 for variance_minimizing) keeps disruption minimisation dominant; `fairness_weight` (default 1, higher for fairness strategies) scales the fairness term
- The effective trade-off between stability and fairness is controlled by the ratio `penalty_scale / fairness_weight`

**Frozen slots (reschedule-from-date):**
- When `frozen_slots` is provided, candidates previously scheduled in a frozen slot are **hard-fixed** to that slot (`x[c, t] = 1`), and staff previously assigned to a frozen slot are also hard-fixed (`y[s, t] = 1`)
- Frozen candidates and staff are **excluded from change penalties** (no cost for staying)
- Staff loads from frozen slots **still count** in the fairness objective — so the solver produces a fair schedule across all slots, not just the unfrozen ones
- Useful when some interviews have already happened (e.g. past weeks) and only future dates need rescheduling

### Fairness Metrics in Detail: `min_max`, `variance`, and `min_dev`

The `fairness` parameter controls the **secondary objective** (staff workload balance). The three active values measure workload imbalance differently:

| `fairness` | What is minimised | Solver variable(s) | Best for |
|---|---|---|---|
| `"min_max"` | Maximum load across all staff | Single `max_load` integer | Preventing any one person being overwhelmed |
| `"variance"` | Sum of absolute deviations from average | One `dev_s` per staff member | Spreading load evenly across the whole team |
| `"min_dev"` | Identical to `"variance"` (alias) | Same as above | Same as above |
| `"none"` | Nothing (feasibility only) | — | When fairness is irrelevant |

**`"min_max"`** introduces a variable `max_load` bounded by every `staff_count[s] ≤ max_load`. The solver minimises `max_load`. This *caps the busiest person's load* but is indifferent to how work is distributed among everyone else — two distributions with the same peak are treated as identical.

**`"variance"` / `"min_dev"`** introduce one deviation variable `dev_s` per staff member, where `dev_s ≥ |staff_count[s] − avg_int|` (with `avg_int` an integer approximation of the expected average load). The solver minimises `Σ dev_s`. This *spreads load evenly across all staff* and can distinguish between distributions that happen to share the same peak.

> Despite the name `"variance"`, the implementation minimises the **sum of absolute deviations** (a linear proxy) rather than the true quadratic variance. CP-SAT is a linear/integer solver so exact quadratic variance is not directly supported.

**When `min_max` and `variance`/`min_dev` differ — a worked example:**

Consider 3 staff members (`stf1`, `stf2`, `stf3`) after scheduling 5 slots with 2 staff required per slot (10 total assignments across 3 staff, true average = 3.33). The solver uses `avg_int = 3` (integer floor of the true average) as its reference point.

| Distribution | `max_load` | sum-of-abs-dev (avg_int = 3) | `min_max` verdict | `variance` verdict |
|---|---|---|---|---|
| A: stf1=4, stf2=3, stf3=3 | **4** | \|4−3\|+\|3−3\|+\|3−3\| = **1** | Acceptable (tie) | ✓ Preferred |
| B: stf1=4, stf2=4, stf3=2 | **4** | \|4−3\|+\|4−3\|+\|2−3\| = **3** | Acceptable (tie) | ✗ Rejected |

`min_max` treats **A and B identically** (both have `max_load = 4`). `variance`/`min_dev` **prefers distribution A** because the sum of deviations is smaller (1 < 3), meaning the loads are closer to the average.

**What this looks like in an actual run:**

```
# Setup: 5 candidates (cand1–cand5) assigned to 5 time slots,
#        3 staff (stf1, stf2, stf3), 2 staff required per slot

# With fairness="min_max":
# The solver only cares that no single staff member exceeds the minimum possible
# peak load. Both load distributions [4,4,2] and [4,3,3] have max_load=4, so
# either is acceptable — the solver may pick either arbitrarily.
schedule = {"cand1": "t1", "cand2": "t2", "cand3": "t3", "cand4": "t4", "cand5": "t5"}
staff_assignment = {
    "t1": ["stf1", "stf2"],   # running totals: stf1=1, stf2=1, stf3=0
    "t2": ["stf1", "stf2"],   # running totals: stf1=2, stf2=2, stf3=0
    "t3": ["stf1", "stf3"],   # running totals: stf1=3, stf2=2, stf3=1
    "t4": ["stf1", "stf2"],   # running totals: stf1=4, stf2=3, stf3=1
    "t5": ["stf2", "stf3"],   # final:          stf1=4, stf2=4, stf3=2
}
# Loads: stf1=4, stf2=4, stf3=2  →  max_load=4, sum_dev=3
# Solver accepts this: max_load=4 is the best achievable, so objective is met.

# With fairness="variance" (or "min_dev"):
# The solver minimises sum of absolute deviations, so it prefers [4,3,3] over [4,4,2].
staff_assignment = {
    "t1": ["stf1", "stf2"],   # running totals: stf1=1, stf2=1, stf3=0
    "t2": ["stf1", "stf3"],   # running totals: stf1=2, stf2=1, stf3=1
    "t3": ["stf2", "stf3"],   # running totals: stf1=2, stf2=2, stf3=2
    "t4": ["stf1", "stf2"],   # running totals: stf1=3, stf2=3, stf3=2
    "t5": ["stf1", "stf3"],   # final:          stf1=4, stf2=3, stf3=3
}
# Loads: stf1=4, stf2=3, stf3=3  →  max_load=4, sum_dev=1
# Solver prefers this over [4,4,2]: sum_dev=1 < 3, workload more evenly spread.
```

> In practice, on small instances both objectives often agree. The difference becomes visible when multiple feasible staff assignments share the same peak load — `min_max` accepts any of them, while `variance`/`min_dev` steers towards the most evenly spread one.

### Infeasibility Diagnostics

When the solver returns INFEASIBLE, automatic diagnostics run to identify the root cause. The diagnostics check each candidate to determine whether they have at least one *feasible slot* — a slot where the candidate is available AND enough staff members are also available to meet the `min_staff_per_slot` requirement.

Example output:

```
--- Infeasibility diagnostics ---
Candidates with NO feasible slot (guaranteed infeasible):
  Ines Calloway: available at 1 slot(s), but none have >= 2 available staff
Candidates with very few feasible slots (may cause contention):
  Oskar Reeve: 1 feasible slot(s) out of 1 available
---
```

This helps distinguish between data issues (candidates with insufficient availability) and scheduling conflicts (too many candidates competing for the same slots).

---

## Rescheduling Strategies

Eight strategies are implemented, ranging from optimal CP-SAT solutions to a greedy heuristic. The default evaluation suite (`run_generated_demo`) uses six of them:

### 1. `reschedule_from_scratch` (alias: `full`)
Ignores the previous schedule entirely and solves fresh. Provides the globally best new schedule but maximises disruption.

### 2. `change_penalty` (alias: `min_disturbance`) — *default*
Passes the previous schedule to the model builder and uses change penalties as the primary objective. Directly minimises the number of candidate moves and staff reassignments.

### 3. `local_repair`
Restricts the solver to a *local neighbourhood* of affected candidates:
1. Identifies directly affected candidates (from the change event: unavailable candidates/staff, removed candidates, added candidates)
2. Expands one-hop (also includes candidates sharing a slot with an affected candidate in the previous schedule)
3. **Displacement expansion**: when an affected candidate's previous slot is unavailable and their available target slots are all occupied by unaffected (locked) candidates, those blocking candidates are also marked as affected — preventing INFEASIBLE results when all slots are occupied
4. Limits the local window to `max_local_size` (default `max(30, len(candidates) // 2)` — scales with dataset size)
5. **Fixes** unaffected candidates to their previous slot by restricting their availability to only that slot
6. Runs the full CP-SAT model on the constrained problem

Falls back to `change_penalty` if no previous schedule is available.

### 4. `slack_based`
Reserves a deterministic fraction of time slots as *slack* (unavailable to the solver):
- `slack_fraction` (default 0.25): fraction of slots to block
- Only blocks **unoccupied** slots from the previous schedule (existing assignments are never displaced)
- Ensures we never block so many slots that the problem becomes infeasible
- Then runs `change_penalty` on the reduced slot set

Useful for modelling systems that intentionally keep buffer capacity. While `slack_based` does not typically outperform other strategies on stability or fairness metrics, it provides consistent schedule predictability.

### 5. `fairness_weighted`
Explicitly passes `fairness="min_max"` to the model builder with a **lower `penalty_scale`** (default 50) and **higher `fairness_weight`** (default `max(len(candidates), 10)`). This lets the min-max fairness term meaningfully influence the objective — the solver will accept small schedule changes to achieve better staff workload balance. When multiple reschedulings move the same number of candidates, prefers the one where the most-loaded staff member has the lowest load.

### 6. `variance_minimizing`
Uses `fairness="variance"` (sum of absolute deviations from average load) with a **lower `penalty_scale`** (default 10, vs 1000 for `change_penalty`) and a **higher `fairness_weight`** (default `max(len(candidates), 10)`). This makes the fairness term genuinely compete with change penalties in the objective function, so the solver will accept small schedule changes when they yield significantly better staff workload balance. Both `penalty_scale` and `fairness_weight` are set via `setdefault`, so callers can still override them.

- **`change_penalty`** (scale=1000, fairness_weight=1): stability-first, fairness barely matters
- **`fairness_weighted`** (scale=50, fairness_weight=len(candidates)): min-max fairness competes with stability
- **`variance_minimizing`** (scale=10, fairness_weight=len(candidates)): still prefers stability, but accepts small changes for better staff balance

### 7. `greedy_least_loaded` *(heuristic, non-optimal)*
A fast heuristic that does not use the CP-SAT solver:
1. Iterates over candidates in order
2. For each candidate, finds the first free slot where required staff are available
3. Assigns additional staff greedily by picking the least-loaded available staff first
4. Returns the first feasible assignment found

This is useful for large problems where solver time is a concern, but it does not guarantee optimality or minimum disruption.

### 8. `plns` — *Parallel Large Neighborhood Search (Destroy and Repair)*
Based on the Destroy and Repair framework from Attia (2020) ([thesis](https://publications.polymtl.ca/5291/)):
1. **Destroy** – identifies a *sub-scope* (neighbourhood) of the schedule directly or transitively affected by the disruption: disrupted slots, candidates scheduled there, candidates requiring now-unavailable staff, and one-hop neighbours sharing those slots.  The neighbourhood is automatically enlarged when a destroyed candidate has no feasible unoccupied slot.
2. **Repair** – fixes every assignment *outside* the neighbourhood to its previous value, removes change penalties for destroyed candidates, and re-solves only the neighbourhood with CP-SAT.

The key difference from `local_repair` is that PLNS explicitly *removes* the previous assignments from the destroyed region so the repair solver is free to reassign those candidates optimally without incurring change penalties.  Non-destroyed candidates are pinned and incur no solver cost.

Falls back to `change_penalty` if no previous schedule is available.

---

### Strategy Comparison at a Glance

| Strategy | Solver? | Scope | Primary goal | Secondary goal (tiebreaker) | Best when |
|---|---|---|---|---|---|
| `reschedule_from_scratch` | CP-SAT | Global | Fresh optimal schedule | Fairness (`fairness` param) | Starting fresh or no previous schedule |
| `change_penalty` | CP-SAT | Global | Minimum disruption (scale=1000) | Fairness (`fairness` param, default `min_max`) | Default rescheduling |
| `local_repair` | CP-SAT | Local neighbourhood | Minimum disruption (scale=1000) | Fairness (`fairness` param) | Localised changes to a few candidates |
| `fairness_weighted` | CP-SAT | Global | Balanced stability+fairness (scale=50) | `min_max` fairness (cap busiest staff, fairness_weight=N) | When one staff member risks being overwhelmed |
| `variance_minimizing` | CP-SAT | Global | Balanced stability+fairness (scale=10) | `variance` fairness (even load, fairness_weight=N) | When workload equity across the whole team matters |
| `slack_based` | CP-SAT | Global (reduced slots) | Moderate stability (scale=100) | Fairness (`fairness` param) | Modelling buffer capacity, schedule predictability |
| `plns` | CP-SAT | Destroyed neighbourhood | Moderate stability repair (scale=100) | Fairness (`fairness` param) | Focused disruptions where affected region should be re-optimised freely |
| `greedy_least_loaded` | Heuristic | Global | First-fit + least-loaded | None | Large datasets where solver time is prohibitive |

> **`change_penalty` vs `variance_minimizing`**: Both minimise disruption, but with very different stability-fairness trade-offs. `change_penalty` (scale=1000, fairness_weight=1) makes fairness a negligible tiebreaker — the solver almost never accepts extra changes for better fairness. `variance_minimizing` (scale=10, fairness_weight=len(candidates)) amplifies the fairness term so it genuinely competes with change penalties, producing meaningfully different results on the stability-fairness Pareto frontier.

> **`change_penalty` vs `local_repair`**: `local_repair` is faster because it only reschedules a small neighbourhood, but it can miss globally optimal reschedulings that would move a different (non-adjacent) candidate to achieve less disruption overall. Use `local_repair` when you expect changes to be truly localised; use `change_penalty` when you want the globally optimal solution.

> **`plns` vs `local_repair`**: Both restrict the solver to a neighbourhood of affected candidates. The key difference is that `plns` *removes* the previous assignments for destroyed candidates (so the repair solver can optimally reassign them without change penalties), while `local_repair` keeps the previous schedule and relies on change penalties to guide the solver within the local window. Use `plns` when you want the affected region to be re-optimised from scratch; use `local_repair` when you want minimal disruption even within the affected neighbourhood.

---

### Worked Example: Four Strategies on the Same Change Event

**Initial schedule** — 4 candidates, 5 time slots (`t1`-`t5`), 4 staff (`stf1`, `stf2`, `stf3`, `stf4`), 2 staff required per slot:

```
cand_A → t1  [stf1, stf2]
cand_B → t2  [stf1, stf3]
cand_C → t3  [stf2, stf3]
cand_D → t4  [stf1, stf2]
(t5 is empty / spare slot)
```

Staff loads: stf1=3, stf2=3, stf3=2, stf4=0.

**Change event**: `stf1` becomes unavailable at `t1`.

---

**`change_penalty`** (global, minimise moves, `min_max` tiebreaker by default):

The solver re-runs globally. Only `cand_A` is directly disrupted (stf1 was at t1). The solver finds the minimum change: move `cand_A` to `t5` (the spare slot), where stf1 is available. Everyone else stays put.

```
cand_A → t5  [stf1, stf4]   ← moved (stf1 can attend t5)
cand_B → t2  [stf1, stf3]   ← unchanged
cand_C → t3  [stf2, stf3]   ← unchanged
cand_D → t4  [stf1, stf2]   ← unchanged
Changed: 1 candidate
Staff loads: stf1=3, stf2=3, stf3=2, stf4=1  (max_load=3)
```

---

**`local_repair`** (neighbourhood only):

Identifies `cand_A` as affected (at `t1` where stf1 is now unavailable). One-hop expansion: no other candidate is at `t1`, so the local window is just `{cand_A}`. Fixes `cand_B`, `cand_C`, `cand_D` to their previous slots. Solves only for `cand_A`.

```
cand_A → t5  [stf1, stf4]   ← moved (same result as change_penalty here)
cand_B → t2  [stf1, stf3]   ← fixed (not re-solved)
cand_C → t3  [stf2, stf3]   ← fixed (not re-solved)
cand_D → t4  [stf1, stf2]   ← fixed (not re-solved)
Changed: 1 candidate
Solve time: faster (only 1 candidate's variables are active)
```

> In this scenario `local_repair` and `change_penalty` produce the same result, but `local_repair` arrives there faster because it constrained the solver to a single-candidate sub-problem.

---

**`fairness_weighted`** (global, minimise moves, `min_max` tiebreaker):

Same primary result as `change_penalty` (1 move). The `min_max` tiebreaker then guides *which* staff are assigned to each slot. If there were two ways to move `cand_A` that both cost 1 change, the solver picks the one that minimises the busiest staff member's load.

```
cand_A → t5  [stf3, stf4]   ← moved; staff chosen to balance peak load
cand_B → t2  [stf1, stf3]   ← unchanged
cand_C → t3  [stf2, stf3]   ← unchanged
cand_D → t4  [stf1, stf2]   ← unchanged
Changed: 1 candidate
Staff loads: stf1=2, stf2=2, stf3=3, stf4=1  (max_load=3, same as change_penalty)
Note: solver may pick different staff for t5 to keep max_load as low as possible
```

---

**`variance_minimizing`** (global, balanced stability+fairness, `variance`/`min_dev` objective):

With `penalty_scale=10` and `fairness_weight=max(len(candidates), 10)`, the fairness term genuinely competes with change penalties. On this small example (4 candidates), both `penalty_scale` and `fairness_weight` are modest, so the solver still finds the same 1-move solution. On larger datasets, `variance_minimizing` may accept 1–2 additional candidate moves if they yield substantially better staff workload balance.

```
cand_A → t5  [stf3, stf4]   ← moved; staff chosen to minimise sum of deviations
cand_B → t2  [stf1, stf3]   ← unchanged (candidate and staff)
cand_C → t3  [stf2, stf3]   ← unchanged (candidate and staff)
cand_D → t4  [stf1, stf2]   ← unchanged (candidate and staff)
Changed: 1 candidate
Staff loads: stf1=2, stf2=2, stf3=3, stf4=1
sum_dev from avg (avg_int ≈ 2): |2-2|+|2-2|+|3-2|+|1-2| = 2
```

> **Key insight**: On small instances, `change_penalty`, `fairness_weighted`, and `variance_minimizing` often produce the same candidate assignments. The strategies diverge on larger datasets where the fairness term in `variance_minimizing` is amplified enough to justify accepting extra candidate moves for better staff workload balance. The difference between `fairness_weighted` (peak-load capping) and `variance_minimizing` (even-spread) is most pronounced when multiple staff choices produce different load distributions.

---

## Data Formats

### CSV: Applicants Availability

Two-level header CSV. Row 0 = dates, Row 1 = time slots. Cell values: `yes` / `no`. **Only `yes` (case-insensitive) is treated as available**; `no`, `if needed`, empty cells and any other text are treated as unavailable (the loader, `_parse_availability_value`, does not accept `if needed`).

**Candidate names** are read from column 0 by default. When column 0 is empty (e.g. older CSV exports), candidates are auto-named `cand1`, `cand2`, etc.

Two time-slot formats are supported:

**Range format** (older CSVs): Row 0 = `YYYY-MM-DD`, Row 1 = `HH:MM-HH:MM`:

```
,2025-04-01,2025-04-01,...
,09:00-09:45,09:45-10:30,...
CandidateA,yes,no,...
CandidateB,no,yes,...
```

**Start-time format** (newer CSVs, e.g. Doodle polls): Row 0 = date as `YYYY-MM-DD …`, Row 1 = `H.MM` notation (dot-separated hour and minutes, **not** a decimal fraction):

```
,2026-04-01 …,2026-04-01 …,...
,9,9.45,...
Alice,Yes,If needed,...
Bob,,Yes,...
```

In this format, the part after the dot represents actual minutes (not a fraction of an hour), so `9` → `09:00`, `9.45` → `09:45`, `10.3` or `10.30` → `10:30`. Slot labels are normalised to `HH:MM` format to ensure consistent matching between applicant and staff CSVs even when trailing zeros differ.

### CSV: Staff Availability

Same format as applicants with an additional `Name` label in the first column header.

```
Name,2025-04-01,2025-04-01,...
,09:00-09:45,09:45-10:30,...
StaffMember1,yes,yes,...
StaffMember2,yes,no,...
```

Staff members whose ID starts with `lead` are treated as leads.

### CSV: Previous Schedule

```
candidate_id,timeslot_id,staff_ids
CandidateA,2025-04-01 09:00-09:45,StaffMember1;StaffMember2
CandidateB,2025-04-01 09:45-10:30,StaffMember1;StaffMember3
```

### CSV: Forbidden Pairs

Two CSV formats are supported for specifying forbidden candidate–staff pairings:

**Simple format** — two columns `candidate_id` and `staff_id`:

```csv
candidate_id,staff_id
Alice,Prof X
Bob,Prof Y
```

**Real-data format** — columns for `Surname`, `First name(s)`, and `Potential Supervisors` (as used by CDT interview files). An optional header row (`Applicant,,,…`) is auto-detected and skipped. Multiple supervisors are comma-separated:

```csv
Applicant,,,Comments,,Interview,
Surname,First name(s),Potential Supervisors,,,,
Fenwick,Maya,Nora Whitlock,,,,
Marlow,Theo,"Idris Calder, Felix Ashworth",,,,
```

Candidate names are constructed as `"First Surname"` (e.g. `Maya Fenwick`) to match the naming convention used by the availability CSV loader. Comma-separated supervisors are split into individual forbidden pairs.

All forbidden pairs are preserved in the data store, including pairs referencing candidates or staff not yet present. Filtering to active pairs (where both candidate and staff exist) happens only at model-builder time, so when a candidate is added later via staged changes, any matching forbidden pairs automatically apply. Forbidden pairs are also persisted in saved schedule metadata and restored on session resume.

---

## Persistence

The `DataStore` class persists schedules and events as JSON files:

```
data/
└── {run_id}/
    ├── schedules/
    │   └── sch-{uuid}.json      # {id, run_id, seq, created_at, schedule, metadata}
    └── events/
        └── evt-{uuid}.json      # {id, run_id, seq, ts, event}
```

Each saved schedule JSON includes the full `staff_assignment` mapping in its metadata, enabling later export via `DataStore.export_schedule_as_prev_csv()`.

---

## Evaluation Framework

### Synthetic Dataset Generation (`eval/data_generators.py`)

```python
from eval.data_generators import generate_synthetic_dataset

dataset = generate_synthetic_dataset(
    num_candidates=10,
    num_staff=6,
    num_days=3,
    slots_per_day=4,
    complexity="medium",   # "simple" | "medium" | "complex"
    num_leads=2,
    require_leads=True,    # each candidate requires a lead
    seed=42,
)
# Returns: candidates, staff, time_slots, avail, staff_avail, required_staff, forbidden_pairs
```

Complexity levels affect availability density:
- `simple`: ~5% unavailability — problems are almost always feasible
- `medium`: ~15% unavailability
- `complex`: ~30% unavailability with clustered patterns (full-day blocks)

### Noise Generators (`eval/noise_generators.py`)

```python
from eval.noise_generators import apply_noise

noisy_avail, noisy_staff_avail = apply_noise(
    avail=dataset["avail"],
    staff_avail=dataset["staff_avail"],
    noise_type="staff_unavailable",   # See table below
    num_people=2,
    intensity=1,
    seed=42,
    staff_assignment=initial_staff_assignment,  # restrict to active slots
    schedule=initial_schedule,
)
```

| `noise_type` | Effect |
|---|---|
| `staff_unavailable` | Mark `num_people` scheduled staff unavailable at their assigned slot |
| `candidate_unavailable` | Mark `num_people` candidates unavailable at their assigned slot |
| `candidate_removal` | Remove `num_people` candidates entirely |
| `staff_removal` | Remove `num_people` staff entirely |
| `candidate_addition` | Add `num_people` new candidates with full availability |

When `staff_assignment` and `schedule` are provided, noise is narrowed to *active* (occupied) slots only.

### Metrics (`eval/metrics.py`)

```python
from eval.metrics import ScheduleMetrics

m = ScheduleMetrics(
    schedule=new_schedule,
    prev_schedule=initial_schedule,
    staff_assignment=new_staff_assignment,
)

stability = m.stability_metrics()
# {changed_assignments, prop_changed, temporal_deviation_minutes, weighted_change_distance}

robustness = m.robustness_metrics()
# {staff_fairness_variance, staff_fairness_gini, staff_load_max,
#  staff_load_min, staff_load_median, slack_utilisation, feasibility_ratio}
```

### Parameter Sweep (`eval/sweep/sweep_runner.py`)

```python
from eval.sweep.sweep_runner import run_sweep
import itertools

params = itertools.product(
    [{"type": "synthetic", "spec": {"num_candidates": 10, "num_staff": 6}}],
    ["change_penalty", "local_repair", "reschedule_from_scratch"],
    [{"candidate_change_penalty_weight": w} for w in [1, 5, 10]],
    [42, 123],  # seeds
)

results = run_sweep(
    ({
        "dataset": d, "strategy": s, "penalty_weights": pw, "random_seed": seed,
        "noise": {"type": "staff_unavailable", "num_people": 1, "intensity": 1},
    } for d, s, pw, seed in params),
    out_csv="results/my_sweep.csv",
)
```

Results are written incrementally to CSV so partial results are preserved if a run fails mid-sweep.

### Harness CLI (`eval/harness.py`)

```
python -m eval.harness [--mode MODE] [OPTIONS]

Modes:
  demo          Run demo experiment (uses demo_small CSVs or falls back to synthetic)
  synthetic     Run experiment on a synthetically generated dataset
  robustness    Iterative robustness testing on real CSV data
  actual_data   Single run on custom CSV data
  sweep         Full parameter sweep

Common options:
  --base-dir DIR              Output base directory (default: data)
  --persist                   Save schedules and events to disk
  --random-seed N             Fix random seed for reproducibility
  --strategies s1,s2,...      Comma-separated strategy names
  --produce-plots             Generate plots after the run
  --allow-parallel            Enable parallel interview slots
  --max-parallel N            Max parallel interviews per slot (default: 2)

Synthetic/demo options:
  --num-candidates N          (default: 10)
  --num-staff N               (default: 6)
  --num-days N                (default: 3)
  --slots-per-day N           (default: 4)
  --dataset-complexity LEVEL  simple|medium|complex (default: simple)
  --require-leads             Force each candidate to require a lead

Noise options:
  --noise-type TYPE           staff_unavailable|candidate_unavailable|...
  --noise-num-people N        (default: 1)
  --noise-intensity N         (default: 1)

Sweep options:
  --sweep-out FILE            Output CSV (default: data/sweep_results.csv)
  --sweep-strategies s1,s2    Strategies to sweep
  --sweep-sizes s1,s2         Dataset size presets (small, medium, large)
  --sweep-complexities c1,c2  Complexity levels (simple, medium, complex)
  --sweep-candidate-weights w1,w2  Candidate penalty weight values
  --sweep-staff-weights w1,w2      Staff penalty weight values
  --sweep-noise-types t1,t2        Noise types to sweep (empty = all presets)
  --sweep-seeds n1,n2,n3          Seeds to run per combination
  --sweep-penalty-scales p1,p2     Penalty scale values to sweep (e.g. "1,10,100,1000")
  --export-latex              Export summary tables as LaTeX (.tex) files

Actual data / robustness options:
  --applicantscsv FILE        Path to applicants availability CSV
  --staffcsv FILE             Path to staff availability CSV
  --iterations N              Robustness iterations (default: 5)
  --output FILE               Results CSV (default: data/robustness_results.csv)
```

---

### Sweep Framework (`eval/sweep/sweep_scenarios.py`, `eval/sweep_plots/`)

The sweep framework provides a comprehensive benchmarking pipeline for comparing rescheduling strategies across dataset sizes, complexity levels, noise types, and noise severities.

#### Noise Sweep Levels

Noise scenarios are defined at four severity levels, each scaled proportionally to dataset size:

| Level | Unavailability noise | Removal noise | Purpose |
|-------|---------------------|---------------|---------|
| **low** | 10% of staff/candidates | 5% of staff/candidates | Routine minor disruptions |
| **medium** | 35% | 20% | Moderate operational disruptions |
| **high** | 60% | 40% | Severe disruptions, stress-testing strategies |
| **extreme** | 80% | 60% | Near-breaking-point — reveals infeasibility boundaries |

Four noise types are swept at each level: `staff_unavailable`, `candidate_unavailable`, `candidate_removal`, `staff_removal`. Combined with a no-noise baseline, this gives **17 noise scenarios** per sweep. `num_people` is set proportionally (e.g., on a dataset with 20 candidates, "high" candidate_unavailable affects `ceil(20 × 0.60) = 12` candidates).

#### Infeasibility & Timeout Tracking

Both `infeasible` and `timeout` columns (0/1) are included in sweep CSV output:
- `infeasible` = 1 when `reschedule_status` is `INFEASIBLE`, `MODEL_INVALID`, **or** `UNKNOWN` (timeout). This includes timeouts because a timed-out solve also fails to produce a usable schedule.
- `timeout` = 1 when `reschedule_status` is `UNKNOWN` (solver hit the time limit, default 30 s). This is a subset of `infeasible`.

The plotting pipeline generates:
- **`infeasibility_bar.png`** — **stacked** bar chart per strategy: crimson = true infeasible (INFEASIBLE/MODEL_INVALID), orange = timeout (UNKNOWN). Annotations show `infeas=N, timeout=M / total`.
- **`infeasible_by_noise_type.png`**, **`infeasible_by_noise_level.png`**, **`infeasible_by_size_label.png`**, **`infeasible_by_complexity.png`** — dimension breakdowns
- Infeasibility and timeout rates are aggregated using **mean** (not median) to correctly capture low-rate events from binary 0/1 data

**Feasible-only metric aggregation**: All non-rate metrics (stability, fairness, staff load, etc.) in summary tables, recommendation tables, and plots are computed **only** over feasible rows (`infeasible == 0`). This prevents strategies with higher infeasibility rates from being artificially rewarded by the zero-valued metrics that failed/timed-out solves produce. A `feasible_n` column in summary CSVs shows how many rows contributed to those aggregated metrics alongside the total `n`.

Use `--time-limit <seconds>` to increase the solver time budget per experiment for stress testing (default: 30 s). Higher limits separate genuine infeasibility from timeouts.

#### Pareto Plots

Two stability-vs-fairness Pareto plots are generated:

- **`pareto.png`** — scatter plot with each strategy in its own colour and a legend (no numbered point labels)
- **`pareto_regions.png`** — convex hull regions showing where each strategy's experiments generally land, with bold **X** median markers and median coordinates in the legend

#### Penalty Scale Sweeps

For strategies that use penalty-based objectives (`change_penalty`, `min_disturbance`, `variance_minimizing`), `penalty_scale` can be swept across values to find the optimal stability-fairness trade-off:

```python
from eval.sweep.sweep_scenarios import strategy_comparison_iter

scenarios = strategy_comparison_iter(
    strategies=["change_penalty", "variance_minimizing"],
    penalty_scale_values=[1, 10, 100, 1000],
    sizes=["small", "medium"],
    seeds=[0, 1, 2],
)
```

When the CSV data contains multiple `penalty_scale` values, the plotting pipeline automatically generates `summary_by_penalty_scale.csv` and grouped bar charts for each metric broken down by penalty scale.

The `--sweep-penalty-scales` CLI flag provides a shortcut:

```bash
python -m eval.harness --mode sweep \
    --sweep-penalty-scales "1,10,100,1000" \
    --sweep-strategies "change_penalty,variance_minimizing" \
    --produce-plots
```

#### Noise-Level Progression Plots

The plotting pipeline generates line plots showing how each metric changes as noise severity increases from `low → medium → high → extreme`, with one line per strategy. These complement the grouped bar breakdowns by showing trends clearly across noise levels. Output: `metric_vs_noise_level_*.png`.

#### Strategy Recommendation Table

After a sweep, `generate_recommendation_table()` ranks all strategies per metric (stability, fairness, feasibility, speed) and outputs a summary table showing the recommended strategy, runner-up, and which strategy to avoid for each priority:

```
| Priority         | Recommended Strategy | Runner-Up      | Avoid                  |
|------------------|---------------------|----------------|------------------------|
| Stability        | local_repair        | change_penalty | reschedule_from_scratch |
| Fairness         | variance_minimizing | fairness_weighted | change_penalty       |
| Feasibility      | slack_based         | ...            | ...                    |
```

Output: `recommendation_table.md` (and `recommendation_table.tex` when `--export-latex` is used).

#### LaTeX Export

Both `eval/harness.py` and `eval/sweep_plots.py` support `--export-latex`, which converts all summary CSV tables (`summary_*.csv`) to LaTeX (`.tex`) files via `pandas.DataFrame.to_latex()`. The recommendation table is also exported to LaTeX when the flag is set.

```bash
# From harness
python -m eval.harness --mode sweep --export-latex --produce-plots

# Standalone from sweep_plots
python -m eval.sweep_plots results/sweep.csv --out results/plots --export-latex
```

> For a comprehensive research plan using the sweep framework, see [`docs/SWEEP_RESEARCH_GUIDE.md`](docs/SWEEP_RESEARCH_GUIDE.md).

---

## User Interfaces

### CLI (`ui/cli.py`)

An interactive command-line interface for running the solver, browsing schedules, staging changes, and viewing metrics.

```bash
python -m ui.cli \
    --applicantscsv data/applicants.csv \
    --staffcsv data/staff.csv \
    --allow-parallel --max-parallel 2

# With forbidden candidate-staff pairs (CSV file or inline)
python -m ui.cli \
    --applicantscsv data/applicants.csv \
    --staffcsv data/staff.csv \
    --forbidden-pairs forbidden.csv

python -m ui.cli \
    --applicantscsv data/applicants.csv \
    --staffcsv data/staff.csv \
    --forbidden-pairs "Alice:Prof X, Bob:Prof Y"
```

Key features:
- Load candidate/staff availability from CSVs and solve the initial schedule
- Real candidate names from the CSV are used by default; falls back to `cand1`, `cand2`, etc. when names are empty
- Supports both range-format (`09:00-09:45`) and decimal start-time format (`9.45`) slot labels
- `--forbidden-pairs` accepts a CSV file path (simple or real-data format) or inline `candidate:staff` pairs
- Browse the current schedule and staff assignments
- Stage change events interactively (staff/candidate unavailability, additions, removals)
- Reschedule with any strategy and view the resulting stability/robustness metrics
- Generate evaluation plots
- Explore the DataStore history

### Web App (`ui/web_app.py`)

A Streamlit-based web application providing a full interactive dashboard.

```bash
streamlit run ui/web_app.py
```

Key features:
- Upload applicants and staff availability CSVs (supports both range and decimal start-time formats; only `yes` cells count as available)
- Upload an optional previous-schedule CSV as a baseline
- Upload a forbidden pairs CSV or enter inline `candidate:staff` pairs to prevent specific pairings
- Configure solver parameters including parallel interview support, fairness mode, and staff limits
- Solve and view the schedule as a table
- Automatic infeasibility diagnostics when the solver cannot find a solution (identifies candidates with no feasible slot)
- Add new candidates or staff with three availability modes: all available, select unavailable slots, or upload a CSV
- **CSV uploads in Step 2 refresh availability** for existing candidates/staff — re-uploading a CSV restores the correct unavailability data for existing entities
- **Availability persists across resumes** — candidate and staff availability is now saved in schedule metadata, so resuming a run restores the original CSV-based availability instead of defaulting to all-available. Older runs that pre-date this change will still fall back to all-available
- **Bulk unavailability** — a dedicated tab in Step 2 lets you select multiple staff members or candidates *and* multiple dates, then marks all matching slot/entity combinations as unavailable at once. Useful when an entire week of staff becomes unavailable (e.g. due to strikes)
- **Freeze past dates** — an optional date picker before the Reschedule button lets you select a cutoff date. All interview slots on or before that date are frozen: candidates and staff are hard-fixed to their previous positions and excluded from change penalties. Their staff loads still count for the fairness objective, so the solver produces a fair schedule for the remaining (future) slots. Useful when some interviews have already happened and only future dates need rescheduling
- Stage changes interactively and reschedule with a chosen strategy
- Forbidden pairs persist through staged changes and session resumes — pairs referencing not-yet-added candidates apply automatically when those candidates are added later
- View stability and robustness metrics (including staff change counts) after each solve
- Generate and display Gantt, bar, Pareto, and heatmap plots
- Persist every solve to a DataStore; resume a previous session on restart
- **Availability is correctly enforced on resume**: when loading a previous run and uploading new CSVs, candidates/staff are never assumed available at time slots not present in their CSV

---

## Running Tests

```bash
python -m pytest tests/ -v
```

The test suite has 246 tests. All tests should pass.

Key test files:

| File | Purpose |
|------|---------|
| `test_basics.py` | Basic solver end-to-end |
| `test_strategies.py` | All 8 strategy implementations |
| `test_parallel_slots.py` | Parallel interview slot expansion, solver integration, and strategies |
| `test_lead_requirements.py` | Lead/required-staff constraints |
| `test_data_generators.py` | Synthetic data generation |
| `test_noise_generators.py` | Noise generation (including active-slot targeting) |
| `test_loaders.py` | CSV loading, schema validation, slot normalisation, forbidden pairs |
| `test_metrics.py` | Stability and robustness metric calculations |
| `test_change_analyzer.py` | Change event analysis utilities |
| `test_store.py` | DataStore persistence and export |
| `test_solver_determinism.py` | Deterministic solver behaviour under fixed seed |
| `test_collect_metrics.py` | Per-run metrics aggregation |
| `test_sweep_runner.py` | Sweep framework: scenarios, runner, plots, infeasibility, penalty scale |
| `test_mip_backend.py` | MIP backend vs CP-SAT: status, objective, allocations, CP-SAT feasibility of MIP solutions |
| `test_harness_demo.py` | Demo harness integration test |
| `test_produce_plots.py` | Plot generation smoke test |
| `test_staff_assignment_occupied_slots.py` | Staff assignment for occupied slots only |
| `test_add_availability.py` | Add candidate/staff availability modes |
| `test_candidate_change_param.py` | Candidate change penalty parameter |
| `test_cli_new_features.py` | CLI argument parsing and features |
| `test_interactive_datastore.py` | Interactive DataStore operations |

---

## Key Solver Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_staff_per_slot` | 2 | Minimum staff per occupied slot |
| `max_staff_per_slot` | 2 | Maximum staff per occupied slot |
| `fairness` | `"min_max"` | Fairness objective: `"min_max"`, `"variance"`, or `"none"` |
| `candidate_change_penalty_weight` | 5 | Weight for candidate move penalties (5× the default `staff_change_penalty_weight` of 1, preventing unnecessary candidate swaps) |
| `staff_change_penalty_weight` | 1 | Weight for staff reassignment penalties |
| `penalty_scale` | 1000 (strategy-dependent) | Scaling factor for change penalties in the objective. Defaults: 1000 (change_penalty, local_repair), 100 (slack_based, plns), 50 (fairness_weighted), 10 (variance_minimizing) |
| `fairness_weight` | 1 | Scaling factor for the fairness term in the objective |
| `backend` | `"cpsat"` | `"cpsat"` (OR-Tools) or `"mip"` (HiGHS via scipy) |
| `time_limit` | None | Solver time limit (seconds) |
| `num_workers` | None | Number of parallel solver workers |
| `random_seed` | None | Seed for deterministic solving |
| `deterministic` | False | Disable randomised search |
| `strategy` | `"change_penalty"` | Rescheduling strategy name |
| `max_local_size` | `max(30, N//2)` | Max candidates in local repair neighbourhood (scales with dataset size) |
| `slack_fraction` | 0.25 | Fraction of slots reserved as slack (slack_based strategy) |
| `allow_parallel` | False | Enable parallel interview slots |
| `max_parallel` | 2 | Maximum number of parallel interviews per base time slot |
| `frozen_slots` | None | Set of timeslot IDs to freeze (hard-fix candidates and staff to their previous positions). Frozen slots still count for fairness but are excluded from change penalties. Used for "reschedule from date" workflows. |

---

## Known Issues and Future Work

### Bugs

All previously known bugs have been resolved:

1. **Fairness and change penalties are now combined.** *(Fixed)* `scheduler/model_builder.py` now builds a proper weighted-sum objective: `penalty_scale * change_penalties + fairness_term`. The `fairness` parameter (`"min_max"`, `"min_dev"` / `"variance"`, or `"none"`) is respected whether or not a previous schedule exists. Strategies such as `variance_minimizing` and `fairness_weighted` correctly apply their requested fairness mode even on re-schedule runs.

2. **`slack_based` feasibility guard.** *(Fixed)* The strategy already caps the number of blocked slots via `max_blockable = max(0, len(time_slots) - len(candidates))`, ensuring the problem cannot be made infeasible by over-blocking. The stale `# TODO` marker in the test file has been removed.

3. **Required staff logic now uses `Staff.is_lead`.** *(Fixed)* `load_staff_objects_from_csv` populates `Staff.is_lead` during loading (using the `id.startswith("lead")` convention for backward compatibility), and `objects_to_solver_inputs_from_models` now checks `s.is_lead` instead of performing a raw string test. Callers that construct `Staff` objects directly can set `is_lead=True` for any staff member regardless of their ID, enabling arbitrary lead assignments.

### Missing / Incomplete Pieces

4. ~~**No graphical user interface.**~~ *(Resolved)* `ui/cli.py` is a fully functional interactive CLI and `ui/web_app.py` is a complete Streamlit web application. See the [User Interfaces](#user-interfaces) section above.

5. **Event store is in-memory only.** `events/event_store.py` implements an `InMemoryEventStore`. There is no database-backed audit trail for production use.

6. **Robustness test suite is incomplete.** `tests/test_robustness.py` contains `# TODO: implement proper set of changes to stress test the algorithm`. The robustness iteration tests exist but do not cover a full range of change scenarios.

7. **No warm-start from saved schedules in CP-SAT.** Although OR-Tools supports solution hints (warm starts), the solver currently always begins from scratch. Injecting the previous schedule as a hint could significantly reduce solve time on re-runs.

8. **`unify_slots()` does not handle time zones or DST.** `data_models/loaders.py` has a `unify_slots()` function that merges slot lists from two CSVs; it does not account for daylight-saving transitions or timezone-aware datetimes.

9. ~~**Sweep parallelisation is not implemented.**~~ *(Resolved)* `eval/sweep/sweep_runner.py` now uses `ProcessPoolExecutor` with `forkserver` context for parallel sweep execution. Initial solves are cached by `(dataset_spec, seed, time_limit)` to avoid redundant computation.

10. **`integrations/` module is a stub.** Files under `integrations/` (mock graph, ICS adapter) are not implemented and not documented. They likely represent planned calendar/graph integrations.

11. **Complex fairness constraints are not supported.** The availability model is binary (0/1). There is no support for preferences (e.g., prefer morning slots), room requirements, or consecutive-slot constraints.

### Performance Considerations

- **Deep copies on every solve call.** `scheduler/strategies/` and `scheduler/solver.py` use `copy.deepcopy()` extensively. For large datasets (many candidates, many slots) this can be slow.
- **No caching of solver state.** Each call to `solve_initial_schedule` or `reschedule` rebuilds the CP-SAT model from scratch.

---

## Change Event Reference

The `change_event` dict passed to `reschedule()` supports the following keys:

| Key | Type | Effect |
|-----|------|--------|
| `staff_unavailable` | `[(staff_id, slot_id), ...]` | Mark staff unavailable at specific slots |
| `candidate_unavailable` | `[(cand_id, slot_id), ...]` or `[cand_id, ...]` | Mark candidate unavailable (at specific slots or all slots) |
| `remove_candidate` | `[cand_id, ...]` | Remove candidates from the pool entirely |
| `add_candidate` | `[cand_id, ...]` | Add new candidates with full availability |
| `staff_removed` | `[staff_id, ...]` | Remove staff from the pool entirely |
| `staff_added` | `[staff_id, ...]` | Add new staff with full availability |
| `noise_applied` | `{type, num_people, intensity, description}` | Metadata key recorded by the evaluation framework |

---

## Output / Metadata Reference

`solve_initial_schedule` and `reschedule` both return `(schedule, metadata)`:

```python
schedule: Dict[candidate_id, timeslot_id]
# e.g. {"cand1": "2025-04-01 08:00-08:45", "cand2": "2025-04-01 08:45-09:30"}

metadata: {
    "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "MODEL_INVALID" | "UNKNOWN",
    "cp_status": int,               # OR-Tools status code
    "solve_time_seconds": float,
    "num_conflicts": int,
    "num_branches": int,
    "objective_value": float | None,
    "staff_assignment": Dict[timeslot_id, List[staff_id]],
    "num_changed_assignments": int | None,  # None for initial schedules
    "saved_schedule_id": str | None,        # set when persist=True
}
```

---

## Contributing / Extending

### Adding a new strategy

1. Add a function with the signature:
   ```python
   def my_strategy(data_store: Dict, change_event: Dict, params: Dict) -> Tuple[Dict, Dict]:
       ...
   ```
2. Place it in the appropriate module under `scheduler/strategies/` (e.g. `_advanced.py` for CP-SAT strategies, or a new `_my_module.py`).
3. Register it in `_STRATEGIES` in `scheduler/strategies/__init__.py`:
   ```python
   _STRATEGIES["my_strategy"] = my_strategy
   ```
4. Add tests in `tests/test_strategies.py`.

### Adding a new noise type

1. Add a branch in `eval/noise_generators.py`'s `apply_noise()` function.
2. Add tests in `tests/test_noise_generators.py`.
