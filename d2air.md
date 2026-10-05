# Scheduling the CDT (D2AIR) admissions interviews

A practical, to-the-point guide: how to configure this tool to schedule — and
re-schedule — CDT admissions interviews. Everything here is taken from the UG4
report (*Benchmarking Minimally-Disruptive Scheduling Strategies in an Academic
Context*, Guillermo Perfect) and checked against the code. Section references
(§) point to that report. For the full documentation of the solver see
[README.md](README.md).

---

## 1. The use case

Each admissions round, the CDT interviews its applicants online. The
coordinator must give every applicant one interview slot and a two-person
panel, then keep that timetable stable while the real world interferes
(academics cancel, applicants withdraw or arrive late, a strike removes a
week).

Scale of the 2026 cycle (§3.1, §4.6, Appendix E):

| Item | Value |
|---|---|
| Applicants | ~33 (+ a few late additions) |
| Staff | ~16 (3 *leads*, the others are assessors) |
| Slots | ~160, 45 minutes each, 10 per day, over ~4 weeks |
| Panel | exactly 2 staff per interview, at least one of them a lead |
| Interviews | online, so several panels can run at the same time |

Manual rescheduling took "at least an hour" per change the previous year; with
the tool it was "a matter of minutes", and the proposed changes were accepted
without manual overrides (§4.6.4).

The tool does two jobs:

1. **Initial schedule** – satisfy every hard constraint and spread the work
   fairly across staff.
2. **Rescheduling** – after a disruption, produce a new valid schedule that
   *moves as few people as possible* from the one already published.

---

## 2. The constraints

### Hard constraints (never violated)

If the solver cannot satisfy all of them it answers `INFEASIBLE` instead of
bending a rule. Each one is fed by a specific input:

| # | Rule in the CDT | Where it comes from | Model (§3.3.2) |
|---|---|---|---|
| 1 | Every applicant gets exactly one interview | the applicant list | `Σₜ x[c,t] = 1` |
| 2 | One applicant per slot (per parallel room, see 8) | – | `Σ_c x[c,t] ≤ 1` |
| 3 | Applicant only in slots where they said **Yes** | applicants CSV | `x[c,t] = 0` if unavailable |
| 4 | Staff only in slots where they said **Yes** | staff CSV | `y[s,t] = 0` if unavailable |
| 5 | Panel of exactly 2 staff for each occupied slot | `min_staff_per_slot = max_staff_per_slot = 2` | `2 ≤ Σ_s y[s,t] ≤ 2` |
| 6 | At least one **lead** on every panel | leads = staff IDs starting with `lead` (or listed explicitly in the web app) | `Σ_{s∈leads} y[s,t] ≥ x[c,t]` |
| 7 | A supervisor never sits on their own applicant's panel | forbidden-pairs CSV / inline pairs | `y[s,t] + x[c,t] ≤ 1` |
| 8 | Online interviews: several panels in parallel, but nobody is in two at once | `allow_parallel`, `max_parallel` | `Σ_{t∈group} y[s,t] ≤ 1` |

Notes:

* **Rule 6 means "at least one" lead**, not "all leads": the loader gives every
  applicant the *list* of leads, and the model requires that the panel contains
  at least one of them.
* **Availability is binary** (§3.1, §5.3). There are no preferences such as
  "morning preferred". Only the cell value `Yes` (any capitalisation) counts as
  available; `No`, `If needed`, empty cells and anything else count as
  unavailable (see the gotchas in §7).
* Rule 8 only needs enabling when there are fewer slots than applicants *or*
  when you want parallel rooms. A small penalty makes the solver prefer the
  base slot (`t`) over the extra rooms (`t.2`, …), so parallel rooms are used
  only when needed.

### Soft objectives (optimised, in this order of priority)

The objective is `λp · (change penalties) + λf · (fairness) + (parallel-suffix penalty)` (§3.3.3):

1. **Stability** – each applicant moved to a new slot costs `ωc` (default 5),
   each staff member added/removed on a slot costs `ωs` (default 1), all
   multiplied by the penalty scale `λp`. Only present when a previous schedule
   exists.
2. **Fairness of staff workload** – with `fairness = min_dev` the solver
   minimises the sum of absolute deviations of each staff member's number of
   interviews from the average. The report prefers this over `min_max` because
   the leads are forced onto many panels: capping the *maximum* load does not
   rebalance everyone else (§3.3.3). **All the report's results use `min_dev`.**
3. **Parallel rooms** – a unit penalty on every use of an extra room.

The ratio `λp / λf` is a *regime selector*, not a fine-tuning knob (§4.3.1,
§5.1): above ≈ 1 stability wins and fairness barely matters; well below 0.1
fairness dominates. Pick a regime through the strategy (section 4), not by
nudging numbers.

---

## 3. Preparing the input files

Two availability CSVs exported from the Doodle polls, one for applicants and one
for staff. Place them anywhere, e.g. `data/cdt_2027/`.

```
,2026-03-11,2026-03-11,…,2026-03-12,…        <- row 1: dates (one per slot column)
,9,9.45,10.3,11.15,1,1.45,2.3,3.15,4,4.45,…  <- row 2: slot start times
Alice Example,Yes,No,Yes,…                    <- one row per person
```

* **Slot labels** are `H` or `H.MM`, where the part after the dot is *minutes*
  (`9.45` → 09:45, `10.3` → 10:30). Both CSVs must use the **same labels**;
  afternoon hours may be written `1`, `2`, `3`, `4` as long as both files do the
  same. The `HH:MM-HH:MM` range format is also accepted.
* **Leads**: the staff CSV must name them `lead…` (e.g. `lead1`, or rename the
  three leads in the CSV before loading). In the web app you can instead type
  the lead IDs in the *Lead staff IDs* box (`none` disables the lead rule).
* **Applicant names**: first column. Names are used as IDs, so keep them unique.
* **Forbidden pairs**: either a CSV with columns `candidate_id,staff_id`, or the
  "real-data" format used by the CDT interview sheet (`Surname`, `First name(s)`,
  `Potential Supervisors`, supervisors comma-separated; applicant IDs become
  `"First Surname"`), or inline `"Alice Example:Prof X, Bob Example:Prof Y"`.
* **Previous schedule** (optional, to continue a round in a new session): CSV
  with columns `candidate_id,timeslot_id,staff_ids` (staff separated by `;`).
  Any schedule saved by the app can be exported in that format.

Do **not** commit real applicant data. `data/cdt_example/` contains an
anonymised dataset with the same shape and scale (33 applicants, 16 staff
including 3 leads, 160 slots, 8 forbidden pairs) generated by
`examples/make_cdt_example_data.py`.

---

## 4. The configuration to use

### Solver parameters

| Parameter | CDT value | Why |
|---|---|---|
| `min_staff_per_slot` | `2` | two-person panels |
| `max_staff_per_slot` | `2` | the web app does not expose it and leaves it at its default of 2 — do **not** raise `min` above 2 there, it would become infeasible |
| `fairness` | **`min_dev`** | even workload; the report's choice. *The CLI and web-app dropdowns default to `min_max` — change it.* |
| `allow_parallel` / `max_parallel` | `True` / `2` | interviews are online, parallel panels allowed (§3.3.3) |
| `time_limit` | `30` (s) | the report's limit; the web app defaults to 10 s, the CLI is fixed to 5 s. At CDT scale solves finish in about a second anyway |
| `strategy` (initial) | `change_penalty` (any; there is no previous schedule yet) | the objective reduces to the fairness term |
| `candidate_change_penalty_weight` | `5` (default) | moving an applicant is 5× worse than changing one panellist — applicants have been told their slot |
| `staff_change_penalty_weight` | `1` (default) | |
| `random_seed` | any fixed int | reproducible schedules (Python API) |

### Which strategy for which situation (§4.7.2)

At CDT scale all strategies are fast and almost always feasible; they differ in
what they optimise:

| Situation | Strategy | Notes |
|---|---|---|
| **Default for routine changes** (an academic cancels, applicants added/withdraw) | **`local_repair`** | fewest changes (median 28), fastest (~1 s). Used for events 2 and 4 of the deployment |
| Disruption touches many applicants / local repair says infeasible | `change_penalty` | same objective on the whole problem — it can move anyone, so it can find solutions `local_repair` cannot |
| Workload equity matters more than stability | `variance_minimizing` | best fairness (variance 1.27, Gini 0.09) but ~2× the changes |
| Plan for resilience *before* publishing | `slack_based` | keeps spare slots free, lowest infeasibility rate. Python API only: set `slack_fraction` (code default 0.25, the report used 0.1) |
| Re-plan everything, ignore the published timetable | `full` (= `reschedule_from_scratch`) | maximal disruption — a last resort |

`plns` and `greedy_least_loaded` are not recommended for the CDT (§4.7).

> **When the answer is `INFEASIBLE`**: it is a proof that no schedule satisfies
> the constraints, not a failure of the tool. In the 2026 cycle a strike removed
> a whole week and the solver proved infeasibility within seconds; the
> coordinator immediately asked the affected applicants for new availability,
> uploaded it, and the problem became feasible (event 4). Typical remedies: ask
> for more availability, add staff, allow more parallel rooms, or relax the
> forbidden pairs.

---

## 5. Step-by-step: the web app (what the coordinator used)

```bash
make install     # once
make web         # opens http://localhost:8501
```

**Step 1 – initial schedule**

1. Upload the applicants CSV and the staff CSV.
2. *Lead staff IDs*: leave blank to auto-detect `lead…` IDs, or type the lead IDs.
3. Add forbidden pairs (inline or CSV).
4. Solver parameters: *Min staff per slot* `2`, *Fairness objective* `min_dev`,
   *Time limit* `30`, tick *Allow parallel interviews* (max `2`).
5. Click **Solve Initial Schedule**. If it is infeasible, the app lists the
   applicants who have no slot with two available staff — fix those inputs first.
6. Check the metrics and the Gantt/heat-map plots, then publish the timetable.

**Step 2 – a disruption arrives.** Stage the changes (you can stack several into
one batch — they are solved together, §3.1):

| Real event | Change to stage |
|---|---|
| A panellist cancels some slots | *Staff unavailable* (or *Bulk unavailability* for a whole week or several people) |
| An applicant cannot attend | *Candidate unavailable* |
| An applicant withdraws | *Remove candidate* |
| A late applicant | *Add candidate* (all slots / selected slots / upload CSV) |
| A panellist leaves the pool / joins | *Remove staff* / *Add staff* |

**Step 3 – reschedule.** Choose the strategy (`local_repair` by default, see
section 4), optionally set a **freeze date** (interviews on or before it have
already happened or are confirmed and are hard-fixed; they still count in the
fairness totals), and press **Reschedule**. The app reports how many applicants
and staff changed. Only the people listed there need to be notified.

**Step 4 – keep going.** Every solve is saved; use the export button to produce
a `prev_schedule` CSV, and *resume* a previous run after restarting the app.

---

## 6. Try it now

```bash
make install            # venv + dependencies
make cdt-data           # anonymised CDT-scale data -> data/cdt_example/ (already included)
make cdt                # initial schedule + 3 disruptions
```

`examples/cdt_walkthrough.py` loads `data/cdt_example/`, applies exactly the
configuration of section 4 and replays four events (it is also the shortest
example of the Python API):

```
33 candidates, 16 staff (leads: lead1, lead2, lead3), 160 slots, 8 forbidden pairs
=== Event 1: initial schedule ===                       status=OPTIMAL  scheduled=33
=== Event 2: 4 candidates added [local_repair] ===      status=OPTIMAL  scheduled=37  changed=4
=== Event 3: Staff-04 unavailable for 1 slot(s) [local_repair] ===   changed=0
=== Event 4: strike on 4 day(s) [change_penalty] ===    status=OPTIMAL  changed=13
```

Solve times are around a second each. (Exact numbers depend on the solver
version and machine; the point is that only the 4 added applicants move in
event 2.)

The same data through the interactive CLI:

```bash
.venv/bin/python -m ui.cli \
    --applicantscsv data/cdt_example/applicants_availabilities.csv \
    --staffcsv data/cdt_example/staff_availabilities.csv \
    --forbidden-pairs data/cdt_example/forbidden_pairs.csv \
    --fairness min_dev --allow-parallel --max-parallel 2 --interactive
```

then, at the `scheduler>` prompt: `strategy local_repair`, `add staff_unavailable lead1 <slot>`
(or `add add_candidate Newcomer`), `reschedule`, `metrics`. Type `help` for all commands.

To reproduce the report's benchmark (4,590+ runs, hours of CPU), see
[eval/SweepUsage.md](eval/SweepUsage.md); a short version:

```bash
.venv/bin/python -m eval.harness --mode sweep --sweep-sizes small \
    --sweep-strategies change_penalty,local_repair,variance_minimizing,slack_based \
    --sweep-seeds 0,1,2 --sweep-out results/sweep.csv --produce-plots
```

---

## 7. Gotchas

* **Only `Yes` is "available".** `README.md` says `if needed` also counts; the
  code (`_parse_availability_value` in `data_models/loaders.py`) does not. If the
  Doodle export contains `If needed` and you want it treated as available,
  replace it with `Yes` in the CSV first.
* **Defaults differ between entry points.** The Python solver defaults to
  `min_dev` for fairness, but the CLI and the web-app dropdown default to
  `min_max`; CLI time limit is fixed at 5 s and the initial strategy at
  `change_penalty`.
* **Lead detection is by name prefix** (`lead…`, lower case). A lead named
  `Lead1` or `Prof Smith` is not detected unless listed in the web-app box.
* **Staff are matched by name** between the two CSVs and the forbidden-pairs
  file: spelling and spacing must match exactly.
* **Rescheduling needs a baseline.** Without a previous schedule the stability
  term is absent and every strategy behaves like a fresh solve.
* **`slack_based` must be planned in advance**: it keeps slots free, so it only
  helps if used from the first schedule.
* **Limits (§5.3):** availability is binary (no preferences), panels are fixed at
  two, and the model was validated on one CDT cycle.
