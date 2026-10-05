"""
Lightweight sweep runner for experimenting with strategies, datasets and noise.

Provides:
- run_single_experiment(params) -> dict of metrics + metadata
- run_sweep(iterable_of_param_dicts, out_csv, max_workers=1)

All CSV output uses flat, scalar columns so that results can be directly loaded
into pandas or any spreadsheet tool for analysis and charting.

Parallelism is available via the *max_workers* argument of ``run_sweep``.
When ``max_workers > 1`` experiments are executed in a
``concurrent.futures.ProcessPoolExecutor`` while result order is preserved
so that strategy ordering in downstream plots stays deterministic.

Initial-schedule solves are **cached** by ``(dataset_spec, seed)`` so that
experiments sharing the same baseline (differing only in strategy or noise)
avoid redundant work.
"""

from typing import Dict, Any, Optional, Iterable, List
import concurrent.futures
import csv
import json
import multiprocessing
import os
import time
import uuid

from data_models.store import DataStore
from data_models.loaders import (
    load_availability_objects_from_csv,
    load_staff_objects_from_csv,
    objects_to_solver_inputs_from_models,
)
from eval.data_generators import generate_synthetic_dataset
from eval.noise_generators import apply_noise
from eval.metrics import ScheduleMetrics
from scheduler import solver as solver_module


# Canonical column order – new metric columns are appended automatically.
_SCENARIO_COLS = [
    "run_id",
    "strategy",
    "size_label",
    "complexity",
    "num_candidates",
    "num_staff",
    "num_slots",
    "noise_type",
    "noise_level",
    "noise_intensity",
    "noise_num_people",
    "candidate_change_penalty_weight",
    "staff_change_penalty_weight",
    "penalty_scale",
    "fairness_weight",
    "seed",
    "initial_status",
    "reschedule_status",
    "infeasible",
    "timeout",
    "optimal",
    "solve_time_seconds",
    "initial_solve_wall_seconds",
]


def _build_data_store_dict_from_synthetic(spec: Dict[str, Any]) -> Dict[str, Any]:
    ds = generate_synthetic_dataset(
        num_candidates=spec.get("num_candidates", 10),
        num_staff=spec.get("num_staff", 6),
        num_days=spec.get("num_days", 3),
        slots_per_day=spec.get("slots_per_day", 4),
        complexity=spec.get("complexity", "simple"),
        num_leads=spec.get("num_leads", 2),
        require_leads=spec.get("require_leads", False),
        seed=spec.get("seed", None),
    )
    return {
        "candidates": ds["candidates"],
        "time_slots": ds["time_slots"],
        "avail": ds["avail"],
        "staff": ds["staff"],
        "staff_avail": ds["staff_avail"],
        "required_staff": ds["required_staff"],
        "forbidden_pairs": ds["forbidden_pairs"],
    }


def _build_data_store_dict_from_csv(applicants_csv: str, staff_csv: str) -> Dict[str, Any]:
    candidates_objs, time_slots1 = load_availability_objects_from_csv(applicants_csv)
    staff_objs, time_slots2 = load_staff_objects_from_csv(staff_csv)
    candidate_ids, staff_ids, avail, staff_avail, required_staff, forbidden_pairs = (
        objects_to_solver_inputs_from_models(candidates_objs, staff_objs)
    )
    # unify timeslots is handled elsewhere; we pass time_slots from loaders for now
    time_slots = time_slots1 if time_slots1 else time_slots2
    return {
        "candidates": candidate_ids,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff_ids,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
    }


# ---------------------------------------------------------------------------
# Initial-solve caching helpers
# ---------------------------------------------------------------------------


def _cache_key(params: Dict[str, Any]):
    """Return a hashable key that uniquely identifies the initial solve inputs.

    The initial schedule depends only on the dataset specification, the random
    seed, and the solver time-limit — **not** on the strategy, noise, or
    penalty weights.  So experiments that share these three values can reuse
    the same initial solve.
    """
    ds = params.get("dataset", {})
    seed = params.get("random_seed")
    tl = params.get("time_limit", 30)
    if ds.get("type") == "synthetic":
        spec = ds.get("spec", {})
        return ("synthetic", json.dumps(spec, sort_keys=True), seed, tl)
    elif ds.get("type") == "csv":
        return ("csv", ds.get("applicants_csv"), ds.get("staff_csv"), seed, tl)
    return None


def _compute_initial(params: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the initial schedule for *params* and return reusable state.

    The returned dict is safe to share across experiments (each consumer
    should shallow-copy ``ds_dict`` before mutating it).
    """
    ds = DataStore(config={
        "base_dir": params.get("base_dir", "data/sweeps"),
        "run_id": f"sweep-init-{uuid.uuid4().hex[:8]}",
    })

    dataset = params.get("dataset", {})
    if dataset.get("type") == "synthetic":
        ds_dict = _build_data_store_dict_from_synthetic(dataset.get("spec", {}))
    elif dataset.get("type") == "csv":
        ds_dict = _build_data_store_dict_from_csv(
            dataset.get("applicants_csv"), dataset.get("staff_csv"),
        )
    else:
        raise ValueError("Unknown dataset type for sweep")

    solver_params: Dict[str, Any] = {
        "_data_store_dict": dict(ds_dict),
        "persist": False,
    }
    solver_params["time_limit"] = params.get("time_limit", 30)
    if params.get("num_workers") is not None:
        solver_params["num_workers"] = int(params["num_workers"])
    if params.get("random_seed") is not None:
        solver_params["random_seed"] = int(params.get("random_seed"))
        solver_params["deterministic"] = True

    t0 = time.monotonic()
    schedule_init, meta_init = solver_module.solve_initial_schedule(
        data_store=ds, params=solver_params,
    )
    initial_wall = time.monotonic() - t0

    return {
        "ds_dict": ds_dict,
        "schedule_init": schedule_init,
        "meta_init": meta_init,
        "staff_assign_init": meta_init.get("staff_assignment", {}),
        "initial_solve_wall_seconds": initial_wall,
    }


def run_single_experiment(params: Dict[str, Any]) -> Dict[str, Any]:
    """Run one experiment and return metrics + metadata.

    Expected params keys (examples):
      - dataset: {type: 'synthetic', spec: {...}} or {type: 'csv', applicants_csv, staff_csv}
      - strategy: str (solver strategy for reschedule)
      - noise: {type, num_people, intensity} or None
      - penalty_weights: {candidate_change_penalty_weight: ..., staff_change_penalty_weight: ...}
      - size_label: optional human label for the dataset size (e.g. "small")
      - random_seed, persist (bool), base_dir
      - _precomputed_initial: (optional) dict from ``_compute_initial`` to skip
        the initial-solve step.

    Returns a dict with flat, scalar values suitable for CSV output.
    """
    run_id = params.get("run_id") or f"sweep-{uuid.uuid4().hex[:8]}"
    ds = DataStore(config={"base_dir": params.get("base_dir", "data/sweeps"), "run_id": run_id})

    precomputed = params.get("_precomputed_initial")
    dataset = params.get("dataset", {})

    if precomputed is not None:
        # Re-use a previously computed initial solve (shallow-copy ds_dict so
        # that mutations like injecting prev_schedule don't leak).
        ds_dict = dict(precomputed["ds_dict"])
        schedule_init = precomputed["schedule_init"]
        meta_init = precomputed["meta_init"]
        staff_assign_init = precomputed["staff_assign_init"]
        initial_solve_wall = precomputed["initial_solve_wall_seconds"]
    else:
        # Build data store dict
        ds_dict = None
        if dataset.get("type") == "synthetic":
            ds_dict = _build_data_store_dict_from_synthetic(dataset.get("spec", {}))
        elif dataset.get("type") == "csv":
            ds_dict = _build_data_store_dict_from_csv(dataset.get("applicants_csv"), dataset.get("staff_csv"))
        else:
            raise ValueError("Unknown dataset type for sweep")

        # Solve initial schedule
        solver_params = {"_data_store_dict": dict(ds_dict), "persist": bool(params.get("persist", False))}
        # Apply a default solver time limit so sweeps don't hang on hard instances.
        solver_params["time_limit"] = params.get("time_limit", 30)
        if params.get("num_workers") is not None:
            solver_params["num_workers"] = int(params["num_workers"])
        if params.get("random_seed") is not None:
            solver_params["random_seed"] = int(params.get("random_seed"))
            solver_params["deterministic"] = True

        t0 = time.monotonic()
        schedule_init, meta_init = solver_module.solve_initial_schedule(data_store=ds, params=solver_params)
        initial_solve_wall = time.monotonic() - t0
        staff_assign_init = meta_init.get("staff_assignment", {})

    # Optionally apply noise to create a change_event
    noise = params.get("noise")
    change_event = {}
    if noise:
        noisy_avail, noisy_staff_avail = apply_noise(
            avail=ds_dict["avail"],
            staff_avail=ds_dict["staff_avail"],
            noise_type=noise.get("type"),
            num_people=noise.get("num_people", 1),
            intensity=noise.get("intensity", 1),
            seed=params.get("random_seed"),
            staff_assignment=staff_assign_init,
            schedule=schedule_init,
        )

        # derive staff_unavailable tuples
        staff_unavailable = []
        for s, slots in noisy_staff_avail.items():
            before = ds_dict["staff_avail"].get(s, {})
            for slot, after_v in slots.items():
                before_v = before.get(slot, 1)
                if before_v == 1 and after_v == 0:
                    staff_unavailable.append((s, slot))

        if staff_unavailable:
            change_event["staff_unavailable"] = staff_unavailable

        # candidate_unavailable
        cand_unavailable = []
        for c, slots in noisy_avail.items():
            before = ds_dict["avail"].get(c, {})
            for slot, after_v in slots.items():
                before_v = before.get(slot, 1)
                if before_v == 1 and after_v == 0:
                    cand_unavailable.append((c, slot))
        if cand_unavailable:
            change_event["candidate_unavailable"] = cand_unavailable

        # detect removed candidates (candidate_removal noise)
        removed_candidates = [c for c in ds_dict["avail"] if c not in noisy_avail]
        if removed_candidates:
            change_event["remove_candidate"] = removed_candidates

        # detect removed staff (staff_removal noise)
        removed_staff = [s for s in ds_dict["staff_avail"] if s not in noisy_staff_avail]
        if removed_staff:
            change_event["staff_removed"] = removed_staff

    # Inject the initial schedule as the baseline so that strategies like
    # change_penalty can penalise deviations from it.  Without this the
    # reschedule call has no prev_schedule and every strategy degrades to
    # a from-scratch solve.
    ds_dict["prev_schedule"] = schedule_init
    ds_dict["prev_staff_assignment"] = staff_assign_init

    # Reschedule with strategy and penalty weights
    res_params = {"_data_store_dict": dict(ds_dict), "strategy": params.get("strategy"), "persist": bool(params.get("persist", False))}
    res_params["time_limit"] = params.get("time_limit", 30)
    if params.get("num_workers") is not None:
        res_params["num_workers"] = int(params["num_workers"])
    # include penalty weights if provided
    pw = params.get("penalty_weights") or {}
    if "candidate_change_penalty_weight" in pw:
        res_params["candidate_change_penalty_weight"] = pw["candidate_change_penalty_weight"]
    if "staff_change_penalty_weight" in pw:
        res_params["staff_change_penalty_weight"] = pw["staff_change_penalty_weight"]
    # Forward strategy-specific knobs so sweeps can tune them
    for _key in ("penalty_scale", "fairness_weight", "max_local_size", "slack_fraction"):
        if _key in params:
            res_params[_key] = params[_key]
    if params.get("random_seed") is not None:
        res_params["random_seed"] = int(params.get("random_seed"))
        res_params["deterministic"] = True

    # Start reschedule from the initial saved schedule id if available
    saved_id = meta_init.get("saved_schedule_id")
    if saved_id:
        res_params["use_saved_schedule_id"] = saved_id

    sched_new, meta_new = solver_module.reschedule(data_store=ds, change_event=change_event, params=res_params)

    # Compute metrics comparing new schedule to initial schedule
    metrics_obj = ScheduleMetrics(schedule=sched_new, prev_schedule=schedule_init, staff_assignment=meta_new.get("staff_assignment", {}), time_slots=ds_dict.get("time_slots"), prev_staff_assignment=staff_assign_init)
    stability = metrics_obj.stability_metrics()
    robustness = metrics_obj.robustness_metrics()

    # ---- Build flat output row ----
    spec = dataset.get("spec", {})
    out: Dict[str, Any] = {
        "run_id": run_id,
        "strategy": params.get("strategy"),
        # Dataset descriptors (flat)
        "size_label": params.get("size_label", "custom"),
        "complexity": spec.get("complexity", "unknown") if dataset.get("type") == "synthetic" else "csv",
        "num_candidates": len(ds_dict.get("candidates", [])),
        "num_staff": len(ds_dict.get("staff", [])),
        "num_slots": len(ds_dict.get("time_slots", [])),
        # Noise descriptors (flat)
        "noise_type": noise.get("type") if noise else "none",
        "noise_level": noise.get("noise_level", "none") if noise else "none",
        "noise_intensity": noise.get("intensity", 0) if noise else 0,
        "noise_num_people": noise.get("num_people", 0) if noise else 0,
        # Penalty weights (flat)
        "candidate_change_penalty_weight": pw.get("candidate_change_penalty_weight", 1),
        "staff_change_penalty_weight": pw.get("staff_change_penalty_weight", 1),
        "penalty_scale": params.get("penalty_scale", ""),
        "fairness_weight": params.get("fairness_weight", ""),
        # Seed
        "seed": params.get("random_seed"),
        # Solver status
        "initial_status": meta_init.get("status"),
        "reschedule_status": meta_new.get("status"),
        # Non-feasible includes both true infeasibility and timeouts (UNKNOWN),
        # because a timed-out solve also fails to produce a usable schedule.
        # The separate ``timeout`` column lets downstream plots/tables
        # distinguish the two causes.
        "infeasible": 1 if meta_new.get("status") in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN") else 0,
        "timeout": 1 if meta_new.get("status") == "UNKNOWN" else 0,
        "optimal": 1 if meta_new.get("status") == "OPTIMAL" else 0,
        "solve_time_seconds": meta_new.get("solve_time_seconds"),
        "initial_solve_wall_seconds": round(initial_solve_wall, 6),
    }
    # Stability metrics
    out.update(stability)
    # Robustness metrics
    out.update(robustness)

    return out


def _ordered_fieldnames(result: Dict[str, Any]) -> List[str]:
    """Return fieldnames with scenario columns first, then metrics in sorted order."""
    ordered = [c for c in _SCENARIO_COLS if c in result]
    remaining = sorted(k for k in result if k not in ordered)
    return ordered + remaining


def run_sweep(
    param_iter: Iterable[Dict[str, Any]],
    out_csv: str,
    max_workers: int = 2,
) -> List[Dict[str, Any]]:
    """Run a sequence of parameter dicts and write results to CSV.

    Each item yielded by param_iter is passed to `run_single_experiment`.
    Returns the list of result dicts.

    Parameters
    ----------
    param_iter : iterable of dict
        Parameter dicts for each experiment.
    out_csv : str
        Path to the output CSV file (created / appended).
    max_workers : int, optional
        Number of parallel workers.  ``2`` (default) runs experiments
        in parallel using a ``concurrent.futures.ProcessPoolExecutor``.
        Set to ``1`` for sequential execution.  Result **order** is
        always preserved so that downstream plots keep the strategy
        ordering specified by the caller.
    """
    params_list = list(param_iter)
    if not params_list:
        return []

    # ------------------------------------------------------------------
    # Phase 1 – cache initial solves (one per unique dataset + seed).
    # This avoids redundant work when the same baseline is shared by
    # multiple strategies or noise scenarios.
    # ------------------------------------------------------------------
    initial_cache: Dict[Any, Dict[str, Any]] = {}
    for p in params_list:
        key = _cache_key(p)
        if key is not None and key not in initial_cache:
            try:
                initial_cache[key] = _compute_initial(p)
            except Exception as exc:
                # Skip – will be retried per-experiment where a proper
                # error row is built.  Print so failures are not silent.
                print(f"[sweep] initial-solve cache miss ({type(exc).__name__}: {exc})")

    # Inject precomputed data.  Each experiment gets its own shallow copy
    # of the cache entry; ``ds_dict`` is shallow-copied inside
    # ``run_single_experiment`` before mutation (line ~200).
    for p in params_list:
        key = _cache_key(p)
        if key in initial_cache:
            p["_precomputed_initial"] = initial_cache[key]

    # ------------------------------------------------------------------
    # Phase 2 – run experiments (sequential or parallel).
    # ------------------------------------------------------------------
    results: List[Dict[str, Any]] = []
    if max_workers <= 1:
        for p in params_list:
            try:
                r = run_single_experiment(p)
            except Exception as e:
                r = _error_row(p, e)
            results.append(r)
    else:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=multiprocessing.get_context("forkserver"),
        ) as executor:
            futures = [
                executor.submit(run_single_experiment, p) for p in params_list
            ]
            # Iterate in submission order → result order is preserved.
            for idx, fut in enumerate(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    r = _error_row(params_list[idx], e)
                results.append(r)

    # ------------------------------------------------------------------
    # Phase 3 – write CSV (single open, one pass).
    # ------------------------------------------------------------------
    fieldnames: Optional[List[str]] = None
    for r in results:
        if "error" not in r:
            fieldnames = _ordered_fieldnames(r)
            break

    if fieldnames is not None:
        needs_header = not (os.path.exists(out_csv) and os.path.getsize(out_csv) > 0)
        with open(out_csv, "a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            if needs_header:
                writer.writeheader()
            for r in results:
                writer.writerow({k: r.get(k) for k in fieldnames})

    return results


def _error_row(params: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    """Build a partial result dict for a failed experiment."""
    return {
        "error": str(exc),
        "strategy": params.get("strategy"),
        "run_id": params.get("run_id", ""),
        "size_label": params.get("size_label", ""),
        "seed": params.get("random_seed"),
        "noise_type": (params.get("noise") or {}).get("type", "none"),
        "reschedule_status": "ERROR",
        "infeasible": 1,
        "timeout": 0,
    }
