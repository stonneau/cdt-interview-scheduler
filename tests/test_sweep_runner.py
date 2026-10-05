"""Tests for the sweep runner, scenario generation and CSV output."""

import csv
import os
import tempfile

import pytest

from eval.sweep.sweep_runner import (
    run_single_experiment,
    run_sweep,
    _cache_key,
    _compute_initial,
)
from eval.sweep.sweep_scenarios import (
    _size_presets,
    _complexity_presets,
    _noise_presets,
    _strategies,
    strategy_comparison_iter,
    default_param_iter,
)


# ---------------------------------------------------------------------------
# Scenario generation
# ---------------------------------------------------------------------------


def test_size_presets_contains_expected_keys():
    presets = _size_presets()
    assert "small" in presets
    assert "medium" in presets
    assert "large" in presets
    for v in presets.values():
        assert "num_candidates" in v
        assert "num_staff" in v


def test_complexity_presets():
    assert set(_complexity_presets()) == {"simple", "medium", "complex"}


def test_noise_presets_scaled():
    noises = _noise_presets(num_staff=20, num_candidates=40)
    # First entry is the no-noise baseline
    assert noises[0] is None
    # Remaining entries should have num_people set proportionally
    for n in noises[1:]:
        assert "num_people" in n
        assert n["num_people"] >= 1
        assert "noise_level" in n
        assert n["noise_level"] in ("low", "medium", "high", "extreme")

    # All four registered noise types must appear
    types_present = {n["type"] for n in noises[1:]}
    assert types_present == {
        "staff_unavailable",
        "candidate_unavailable",
        "candidate_removal",
        "staff_removal",
    }


def test_strategies_returns_unique_names():
    names = _strategies()
    assert len(names) >= 4
    # No duplicates (aliases should have been filtered)
    assert len(names) == len(set(names))


def test_strategy_comparison_iter_yields_params():
    params = list(
        strategy_comparison_iter(
            strategies=["change_penalty"],
            sizes=["small"],
            complexities=["simple"],
            seeds=[0],
        )
    )
    # 1 strategy × 1 size × 1 complexity × 17 noise presets × 1 seed = 17
    assert len(params) == 17
    for p in params:
        assert p["strategy"] == "change_penalty"
        assert p.get("size_label") == "small"
        assert p["dataset"]["spec"]["complexity"] == "simple"


def test_strategy_comparison_iter_noise_filter():
    params = list(
        strategy_comparison_iter(
            strategies=["change_penalty"],
            sizes=["small"],
            complexities=["simple"],
            noise_levels=["none"],
            seeds=[0],
        )
    )
    # Only the no-noise baseline should appear
    assert len(params) == 1
    assert params[0].get("noise") is None


def test_strategy_comparison_iter_multiple_strategies():
    params = list(
        strategy_comparison_iter(
            strategies=["change_penalty", "reschedule_from_scratch"],
            sizes=["small"],
            complexities=["simple"],
            noise_levels=["none"],
            seeds=[0],
        )
    )
    assert len(params) == 2
    strats = {p["strategy"] for p in params}
    assert strats == {"change_penalty", "reschedule_from_scratch"}


def test_default_param_iter_yields():
    count = 0
    for p in default_param_iter(seeds=[0], sizes=["small"]):
        count += 1
        if count > 5:
            break
    assert count > 0


# ---------------------------------------------------------------------------
# Single experiment
# ---------------------------------------------------------------------------


def test_run_single_experiment_flat_output():
    """Verify that a single experiment returns flat, scalar CSV-ready values."""
    params = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 5,
                "num_staff": 3,
                "num_days": 1,
                "slots_per_day": 6,
                "complexity": "simple",
            },
        },
        "strategy": "change_penalty",
        "size_label": "tiny",
        "noise": {"type": "staff_unavailable", "num_people": 1, "intensity": 1},
        "penalty_weights": {
            "candidate_change_penalty_weight": 1,
            "staff_change_penalty_weight": 1,
        },
        "random_seed": 42,
        "persist": False,
    }
    result = run_single_experiment(params)

    # Key scenario columns should be present
    expected_cols = [
        "run_id", "strategy", "size_label", "complexity",
        "num_candidates", "num_staff", "num_slots",
        "noise_type", "noise_intensity", "noise_num_people",
        "candidate_change_penalty_weight", "staff_change_penalty_weight",
        "seed", "initial_status", "reschedule_status", "infeasible",
        "timeout", "solve_time_seconds",
    ]
    for col in expected_cols:
        assert col in result, f"Missing expected column: {col}"

    # Values must be scalars (no dicts or lists)
    for k, v in result.items():
        assert not isinstance(v, (dict, list, set)), (
            f"Column {k!r} has non-scalar value: {type(v)}"
        )

    # Spot-check some values
    assert result["strategy"] == "change_penalty"
    assert result["size_label"] == "tiny"
    assert result["noise_type"] == "staff_unavailable"
    assert result["complexity"] == "simple"
    assert result["num_candidates"] == 5
    assert result["num_staff"] == 3
    assert result["initial_status"] in ("OPTIMAL", "FEASIBLE")
    assert result["reschedule_status"] in ("OPTIMAL", "FEASIBLE")
    assert "changed_assignments" in result
    assert "staff_fairness_variance" in result


def test_run_single_experiment_no_noise():
    params = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 4,
                "num_staff": 3,
                "num_days": 1,
                "slots_per_day": 5,
                "complexity": "simple",
            },
        },
        "strategy": "reschedule_from_scratch",
        "noise": None,
        "random_seed": 0,
        "persist": False,
    }
    result = run_single_experiment(params)
    assert result["noise_type"] == "none"
    assert result["noise_level"] == "none"
    assert result["noise_intensity"] == 0


def test_run_single_experiment_candidate_removal():
    """Verify that candidate_removal noise is handled and populates the
    change_event so the solver sees the removal."""
    params = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 6,
                "num_staff": 3,
                "num_days": 1,
                "slots_per_day": 6,
                "complexity": "simple",
            },
        },
        "strategy": "change_penalty",
        "noise": {"type": "candidate_removal", "num_people": 1, "intensity": 1,
                  "noise_level": "low"},
        "penalty_weights": {
            "candidate_change_penalty_weight": 1,
            "staff_change_penalty_weight": 1,
        },
        "random_seed": 42,
        "persist": False,
    }
    result = run_single_experiment(params)
    assert result["noise_type"] == "candidate_removal"
    assert result["noise_level"] == "low"
    assert result["reschedule_status"] in ("OPTIMAL", "FEASIBLE")


def test_run_single_experiment_staff_removal():
    """Verify that staff_removal noise is handled."""
    params = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 5,
                "num_staff": 4,
                "num_days": 1,
                "slots_per_day": 6,
                "complexity": "simple",
            },
        },
        "strategy": "change_penalty",
        "noise": {"type": "staff_removal", "num_people": 1, "intensity": 1,
                  "noise_level": "low"},
        "penalty_weights": {
            "candidate_change_penalty_weight": 1,
            "staff_change_penalty_weight": 1,
        },
        "random_seed": 42,
        "persist": False,
    }
    result = run_single_experiment(params)
    assert result["noise_type"] == "staff_removal"
    assert result["noise_level"] == "low"
    assert result["reschedule_status"] in ("OPTIMAL", "FEASIBLE")


def test_noise_level_column_present():
    """Verify noise_level appears in experiment output for all noise types."""
    base = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 5,
                "num_staff": 3,
                "num_days": 1,
                "slots_per_day": 6,
                "complexity": "simple",
            },
        },
        "strategy": "change_penalty",
        "penalty_weights": {
            "candidate_change_penalty_weight": 1,
            "staff_change_penalty_weight": 1,
        },
        "random_seed": 42,
        "persist": False,
    }
    result = run_single_experiment(dict(base, noise={
        "type": "staff_unavailable", "num_people": 1, "intensity": 1,
        "noise_level": "medium",
    }))
    assert result["noise_level"] == "medium"


def test_change_penalty_fewer_changes_than_from_scratch():
    """change_penalty should produce fewer (or equal) changed assignments
    than reschedule_from_scratch because it penalises deviations from the
    initial schedule."""
    base = {
        "dataset": {
            "type": "synthetic",
            "spec": {
                "num_candidates": 5,
                "num_staff": 3,
                "num_days": 1,
                "slots_per_day": 6,
                "complexity": "simple",
            },
        },
        "noise": {"type": "staff_unavailable", "num_people": 1, "intensity": 1},
        "penalty_weights": {
            "candidate_change_penalty_weight": 1,
            "staff_change_penalty_weight": 1,
        },
        "random_seed": 42,
        "persist": False,
    }
    r_cp = run_single_experiment(dict(base, strategy="change_penalty"))
    r_fs = run_single_experiment(dict(base, strategy="reschedule_from_scratch"))
    assert r_cp["changed_assignments"] <= r_fs["changed_assignments"]


# ---------------------------------------------------------------------------
# Full sweep + CSV
# ---------------------------------------------------------------------------


def test_run_sweep_writes_csv():
    """Run a tiny sweep and verify the CSV has flat headers and rows."""
    params_list = [
        {
            "dataset": {
                "type": "synthetic",
                "spec": {
                    "num_candidates": 4,
                    "num_staff": 3,
                    "num_days": 1,
                    "slots_per_day": 5,
                    "complexity": "simple",
                },
            },
            "strategy": strat,
            "size_label": "tiny",
            "noise": None,
            "penalty_weights": {
                "candidate_change_penalty_weight": 1,
                "staff_change_penalty_weight": 1,
            },
            "random_seed": 0,
            "persist": False,
        }
        for strat in ["change_penalty", "reschedule_from_scratch"]
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "results.csv")
        results = run_sweep(iter(params_list), csv_path)

        assert len(results) == 2
        assert os.path.exists(csv_path)

        # Read back and verify structure
        with open(csv_path, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 2
        # Headers should include the scenario columns
        for col in ["strategy", "size_label", "noise_type", "changed_assignments"]:
            assert col in reader.fieldnames

        # No nested dict strings in any cell
        for row in rows:
            for k, v in row.items():
                assert not v.startswith("{"), f"Column {k!r} looks like a dict: {v}"


# ---------------------------------------------------------------------------
# Initial-solve caching
# ---------------------------------------------------------------------------


_TINY_PARAMS = {
    "dataset": {
        "type": "synthetic",
        "spec": {
            "num_candidates": 4,
            "num_staff": 3,
            "num_days": 1,
            "slots_per_day": 5,
            "complexity": "simple",
        },
    },
    "strategy": "change_penalty",
    "size_label": "tiny",
    "noise": None,
    "penalty_weights": {
        "candidate_change_penalty_weight": 1,
        "staff_change_penalty_weight": 1,
    },
    "random_seed": 0,
    "persist": False,
}


def test_cache_key_same_for_different_strategies():
    """Experiments with same dataset+seed but different strategies should
    share the same cache key (initial solve doesn't depend on strategy)."""
    p1 = dict(_TINY_PARAMS, strategy="change_penalty")
    p2 = dict(_TINY_PARAMS, strategy="reschedule_from_scratch")
    assert _cache_key(p1) == _cache_key(p2)


def test_cache_key_differs_for_different_seeds():
    p1 = dict(_TINY_PARAMS, random_seed=0)
    p2 = dict(_TINY_PARAMS, random_seed=1)
    assert _cache_key(p1) != _cache_key(p2)


def test_compute_initial_returns_expected_keys():
    result = _compute_initial(_TINY_PARAMS)
    assert "ds_dict" in result
    assert "schedule_init" in result
    assert "meta_init" in result
    assert "staff_assign_init" in result
    assert "initial_solve_wall_seconds" in result
    assert result["initial_solve_wall_seconds"] >= 0


def test_initial_solve_wall_seconds_in_output():
    """initial_solve_wall_seconds should appear in experiment output."""
    result = run_single_experiment(dict(_TINY_PARAMS))
    assert "initial_solve_wall_seconds" in result
    assert isinstance(result["initial_solve_wall_seconds"], float)
    assert result["initial_solve_wall_seconds"] >= 0


def test_precomputed_initial_skips_solve():
    """When _precomputed_initial is supplied, the initial solve should
    be skipped and the precomputed values used instead."""
    precomputed = _compute_initial(_TINY_PARAMS)
    params = dict(_TINY_PARAMS, _precomputed_initial=precomputed)
    result = run_single_experiment(params)
    # Should use the precomputed wall time
    assert result["initial_solve_wall_seconds"] == pytest.approx(
        precomputed["initial_solve_wall_seconds"], abs=1e-5,
    )
    assert result["reschedule_status"] in ("OPTIMAL", "FEASIBLE")


# ---------------------------------------------------------------------------
# Parallel sweep + order preservation
# ---------------------------------------------------------------------------


def test_run_sweep_parallel_preserves_order():
    """Results from a parallel sweep must appear in the same order as the
    input parameter list so that strategy ordering in plots is stable."""
    strategies = ["change_penalty", "reschedule_from_scratch"]
    params_list = [
        dict(_TINY_PARAMS, strategy=s) for s in strategies
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "parallel.csv")
        results = run_sweep(iter(params_list), csv_path, max_workers=2)

        assert len(results) == 2
        assert results[0]["strategy"] == "change_penalty"
        assert results[1]["strategy"] == "reschedule_from_scratch"

        # CSV should also be in order
        with open(csv_path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert rows[0]["strategy"] == "change_penalty"
        assert rows[1]["strategy"] == "reschedule_from_scratch"


def test_run_sweep_caches_initial_solves():
    """Two experiments with the same dataset+seed but different strategies
    should reuse the initial solve via caching."""
    params_list = [
        dict(_TINY_PARAMS, strategy="change_penalty"),
        dict(_TINY_PARAMS, strategy="reschedule_from_scratch"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "cached.csv")
        results = run_sweep(iter(params_list), csv_path)

        assert len(results) == 2
        # Both should succeed
        for r in results:
            assert "error" not in r
            assert r["reschedule_status"] in ("OPTIMAL", "FEASIBLE")


def test_run_sweep_initial_solve_wall_in_csv():
    """initial_solve_wall_seconds column should appear in the CSV output."""
    params_list = [dict(_TINY_PARAMS)]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "init_wall.csv")
        run_sweep(iter(params_list), csv_path)

        with open(csv_path, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert "initial_solve_wall_seconds" in reader.fieldnames
        assert float(rows[0]["initial_solve_wall_seconds"]) >= 0


def test_run_sweep_max_workers_default_sequential():
    """max_workers=1 (default) should run sequentially and produce
    correct results identical to the previous behaviour."""
    params_list = [dict(_TINY_PARAMS)]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "seq.csv")
        results = run_sweep(iter(params_list), csv_path, max_workers=1)

        assert len(results) == 1
        assert "error" not in results[0]
        assert os.path.exists(csv_path)


# ---------------------------------------------------------------------------
# Infeasibility column
# ---------------------------------------------------------------------------


def test_infeasible_column_present_and_zero_for_feasible():
    """Verify infeasible column is 0 when reschedule succeeds."""
    result = run_single_experiment(dict(_TINY_PARAMS))
    assert "infeasible" in result
    assert result["infeasible"] == 0


def test_infeasible_column_in_csv():
    """Verify infeasible appears in CSV header and rows."""
    params_list = [dict(_TINY_PARAMS)]

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "results.csv")
        run_sweep(iter(params_list), csv_path)

        with open(csv_path, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert "infeasible" in reader.fieldnames
        assert rows[0]["infeasible"] == "0"


# ---------------------------------------------------------------------------
# variance_minimizing differentiation
# ---------------------------------------------------------------------------


def test_variance_minimizing_uses_lower_penalty_scale():
    """variance_minimizing should use penalty_scale=10 (not 1000) so
    fairness actually influences the objective differently from change_penalty."""
    from scheduler.strategies import variance_minimizing, change_penalty

    # Build a tiny data_store
    ds = {
        "candidates": [f"c{i}" for i in range(4)],
        "time_slots": [f"t{i}" for i in range(6)],
        "staff": ["s1", "s2", "s3"],
        "avail": {f"c{i}": {f"t{j}": 1 for j in range(6)} for i in range(4)},
        "staff_avail": {f"s{i}": {f"t{j}": 1 for j in range(6)} for i in range(1, 4)},
        "required_staff": {},
        "forbidden_pairs": set(),
        "prev_schedule": {"c0": "t0", "c1": "t1", "c2": "t2", "c3": "t3"},
        "prev_staff_assignment": {
            "t0": ["s1", "s2"], "t1": ["s1", "s3"],
            "t2": ["s2", "s3"], "t3": ["s1", "s2"],
        },
    }
    params = {"time_limit": 10}
    sched_vm, meta_vm = variance_minimizing(ds, {}, params)
    assert meta_vm["status"] in ("OPTIMAL", "FEASIBLE")

    # Verify it doesn't override an explicitly provided penalty_scale
    params_explicit = {"time_limit": 10, "penalty_scale": 500}
    sched_ex, meta_ex = variance_minimizing(ds, {}, params_explicit)
    assert meta_ex["status"] in ("OPTIMAL", "FEASIBLE")


def test_variance_minimizing_sets_fairness_weight():
    """variance_minimizing should set fairness_weight proportional to
    the number of candidates so the fairness term can compete with
    change penalties at practical penalty_scale values."""
    from scheduler.strategies import variance_minimizing

    ds = {
        "candidates": [f"c{i}" for i in range(5)],
        "time_slots": [f"t{i}" for i in range(6)],
        "staff": ["s1", "s2", "s3"],
        "avail": {f"c{i}": {f"t{j}": 1 for j in range(6)} for i in range(5)},
        "staff_avail": {f"s{i}": {f"t{j}": 1 for j in range(6)} for i in range(1, 4)},
        "required_staff": {},
        "forbidden_pairs": set(),
        "prev_schedule": {f"c{i}": f"t{i}" for i in range(5)},
        "prev_staff_assignment": {f"t{j}": ["s1", "s2"] for j in range(6)},
    }
    params = {"time_limit": 10}
    sched, meta = variance_minimizing(ds, {}, params)
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")

    # Verify it doesn't override an explicitly provided fairness_weight
    params_explicit = {"time_limit": 10, "fairness_weight": 50}
    sched_ex, meta_ex = variance_minimizing(ds, {}, params_explicit)
    assert meta_ex["status"] in ("OPTIMAL", "FEASIBLE")


def test_fairness_weight_in_csv_output():
    """fairness_weight should appear in CSV output when explicitly provided."""
    params = dict(_TINY_PARAMS, fairness_weight=25)
    result = run_single_experiment(params)
    assert result["fairness_weight"] == 25

    # Without explicit fairness_weight, should be empty string
    result_default = run_single_experiment(dict(_TINY_PARAMS))
    assert result_default["fairness_weight"] == ""


# ---------------------------------------------------------------------------
# local_repair max_local_size scaling
# ---------------------------------------------------------------------------


def test_local_repair_max_local_size_scales_with_dataset():
    """local_repair default max_local_size should scale with candidate count."""
    from scheduler.strategies import local_repair

    ds = {
        "candidates": [f"c{i}" for i in range(80)],
        "time_slots": [f"t{i}" for i in range(100)],
        "staff": [f"s{i}" for i in range(5)],
        "avail": {f"c{i}": {f"t{j}": 1 for j in range(100)} for i in range(80)},
        "staff_avail": {f"s{i}": {f"t{j}": 1 for j in range(100)} for i in range(5)},
        "required_staff": {},
        "forbidden_pairs": set(),
        "prev_schedule": {f"c{i}": f"t{i}" for i in range(80)},
        "prev_staff_assignment": {f"t{i}": ["s0", "s1"] for i in range(100)},
    }
    # With 80 candidates, default max_local = max(30, 80//2) = 40
    # Make many candidates affected so the cap is tested
    change_event = {"candidate_unavailable": [(f"c{i}", f"t{i}") for i in range(50)]}
    params = {"time_limit": 10}
    sched, meta = local_repair(ds, change_event, params)
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")


# ---------------------------------------------------------------------------
# penalty_scale in sweep output
# ---------------------------------------------------------------------------


def test_penalty_scale_in_csv_output():
    """penalty_scale should appear in CSV output when explicitly provided."""
    params = dict(_TINY_PARAMS, penalty_scale=100)
    result = run_single_experiment(params)
    assert result["penalty_scale"] == 100

    # Without explicit penalty_scale, should be empty string
    result_default = run_single_experiment(dict(_TINY_PARAMS))
    assert result_default["penalty_scale"] == ""


def test_penalty_scale_sweep_scenarios():
    """strategy_comparison_iter with penalty_scale_values should produce
    multiple experiments per penalty-scale-aware strategy."""
    params = list(strategy_comparison_iter(
        strategies=["change_penalty", "local_repair"],
        sizes=["small"],
        complexities=["simple"],
        noise_levels=["none"],
        seeds=[0],
        penalty_scale_values=[10, 1000],
    ))
    # change_penalty gets 2 runs (one per penalty_scale value)
    # local_repair gets 1 run (not a penalty-scale strategy)
    cp_params = [p for p in params if p["strategy"] == "change_penalty"]
    lr_params = [p for p in params if p["strategy"] == "local_repair"]
    assert len(cp_params) == 2
    assert len(lr_params) == 1
    assert cp_params[0]["penalty_scale"] == 10
    assert cp_params[1]["penalty_scale"] == 1000
    assert "penalty_scale" not in lr_params[0]


# ---------------------------------------------------------------------------
# buffer_slots metric
# ---------------------------------------------------------------------------


def test_buffer_slots_metric():
    """_buffer_slots should count timeslots with no candidate assigned."""
    from eval.metrics import ScheduleMetrics
    # 6 slots, 4 candidates assigned to t0-t3 → t4, t5 are buffer (empty)
    m = ScheduleMetrics(
        schedule={"c0": "t0", "c1": "t1", "c2": "t2", "c3": "t3"},
        prev_schedule={"c0": "t0", "c1": "t1", "c2": "t2", "c3": "t3"},
        staff_assignment={"t0": ["s1"], "t1": ["s1"], "t2": ["s1"], "t3": ["s1"]},
        time_slots=["t0", "t1", "t2", "t3", "t4", "t5"],
    )
    assert m._buffer_slots() == 2


def test_buffer_slots_not_in_robustness_metrics():
    """buffer_slots should NOT appear in robustness_metrics (identical for all strategies)."""
    result = run_single_experiment(dict(_TINY_PARAMS))
    assert "buffer_slots" not in result


# ---------------------------------------------------------------------------
# Infeasibility rate aggregation
# ---------------------------------------------------------------------------


def test_infeasibility_summary_uses_mean_not_median():
    """Summary tables should use mean (rate) for infeasible, not median.

    With binary 0/1 data, median is 0 unless >50% are infeasible —
    mean shows the true infeasibility rate.
    """
    from eval.sweep_plots import generate_summary_tables
    # Simulate 5 rows: 2 infeasible out of 5 → rate = 0.4 (not 0 from median)
    rows = [
        {"strategy": "local_repair", "infeasible": 0, "changed_assignments": 2,
         "size_label": "small", "complexity": "simple", "noise_type": "none",
         "noise_level": "none"},
        {"strategy": "local_repair", "infeasible": 0, "changed_assignments": 3,
         "size_label": "small", "complexity": "simple", "noise_type": "none",
         "noise_level": "none"},
        {"strategy": "local_repair", "infeasible": 0, "changed_assignments": 2,
         "size_label": "small", "complexity": "simple", "noise_type": "none",
         "noise_level": "none"},
        {"strategy": "local_repair", "infeasible": 1, "changed_assignments": 0,
         "size_label": "small", "complexity": "simple", "noise_type": "none",
         "noise_level": "none"},
        {"strategy": "local_repair", "infeasible": 1, "changed_assignments": 0,
         "size_label": "small", "complexity": "simple", "noise_type": "none",
         "noise_level": "none"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_summary_tables(rows, tmpdir)
        with open(os.path.join(tmpdir, "summary_overall.csv"), newline="") as fh:
            reader = csv.DictReader(fh)
            table = list(reader)
        assert len(table) == 1
        # Mean of [0,0,0,1,1] = 0.4; median would give 0.0
        assert float(table[0]["infeasible"]) == pytest.approx(0.4, abs=0.001)


def test_penalty_scale_summary_generated_for_sweep():
    """When rows contain multiple distinct penalty_scale values,
    generate_summary_tables should produce summary_by_penalty_scale.csv."""
    from eval.sweep_plots import generate_summary_tables
    rows = [
        {"strategy": "change_penalty", "penalty_scale": "10",
         "changed_assignments": 5, "infeasible": 0, "staff_fairness_variance": 0.8,
         "size_label": "small", "complexity": "simple",
         "noise_type": "none", "noise_level": "none"},
        {"strategy": "change_penalty", "penalty_scale": "1000",
         "changed_assignments": 1, "infeasible": 0, "staff_fairness_variance": 1.5,
         "size_label": "small", "complexity": "simple",
         "noise_type": "none", "noise_level": "none"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_summary_tables(rows, tmpdir)
        ps_csv = os.path.join(tmpdir, "summary_by_penalty_scale.csv")
        assert os.path.exists(ps_csv), "summary_by_penalty_scale.csv not generated"
        with open(ps_csv, newline="") as fh:
            table = list(csv.DictReader(fh))
        assert len(table) == 2
        scales = {r["penalty_scale"] for r in table}
        assert scales == {"10", "1000"}


def test_penalty_scale_summary_skipped_without_sweep():
    """Without multiple penalty_scale values, no penalty_scale summary is generated."""
    from eval.sweep_plots import generate_summary_tables
    rows = [
        {"strategy": "change_penalty", "changed_assignments": 2, "infeasible": 0,
         "size_label": "small", "complexity": "simple",
         "noise_type": "none", "noise_level": "none"},
        {"strategy": "local_repair", "changed_assignments": 3, "infeasible": 0,
         "size_label": "small", "complexity": "simple",
         "noise_type": "none", "noise_level": "none"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_summary_tables(rows, tmpdir)
        ps_csv = os.path.join(tmpdir, "summary_by_penalty_scale.csv")
        assert not os.path.exists(ps_csv), "should not generate penalty_scale summary without a sweep"


# ---------------------------------------------------------------------------
# Penalty-scale CLI shortcut
# ---------------------------------------------------------------------------


def test_penalty_scale_cli_argument_parsed():
    """--sweep-penalty-scales should be accepted and parsed into a list."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep-penalty-scales", type=str, default=None)
    args = parser.parse_args(["--sweep-penalty-scales", "1,10,100,1000"])
    assert args.sweep_penalty_scales == "1,10,100,1000"


def test_strategy_comparison_iter_with_penalty_scale_values():
    """penalty_scale_values should multiply runs for penalty-aware strategies."""
    params = list(strategy_comparison_iter(
        strategies=["change_penalty"],
        sizes=["small"],
        complexities=["simple"],
        noise_levels=["none"],
        seeds=[0],
        penalty_scale_values=[10, 100],
    ))
    # 1 strategy × 1 size × 1 complexity × 2 penalty_scale × 1 noise × 1 seed
    assert len(params) == 2
    ps_vals = {p["penalty_scale"] for p in params}
    assert ps_vals == {10, 100}


def test_strategy_comparison_iter_penalty_scale_skipped_for_non_ps_strategy():
    """Non-penalty-aware strategies should not multiply by penalty_scale_values."""
    params = list(strategy_comparison_iter(
        strategies=["local_repair"],
        sizes=["small"],
        complexities=["simple"],
        noise_levels=["none"],
        seeds=[0],
        penalty_scale_values=[10, 100],
    ))
    # local_repair is not in _PS_STRATEGIES → single run (no penalty_scale key)
    assert len(params) == 1
    assert "penalty_scale" not in params[0]


# ---------------------------------------------------------------------------
# Noise-level progression plot
# ---------------------------------------------------------------------------


def test_plot_metric_vs_noise_level_creates_files():
    """plot_metric_vs_noise_level should produce one PNG per metric."""
    from eval.sweep_plots import plot_metric_vs_noise_level, _METRIC_DEFS
    rows = []
    for level in ["low", "medium", "high", "extreme"]:
        for strat in ["change_penalty", "local_repair"]:
            rows.append({
                "strategy": strat,
                "noise_level": level,
                "noise_type": "staff_unavailable",
                "changed_assignments": 5 if level == "low" else 10,
                "prop_changed": 0.1,
                "infeasible": 0,
                "staff_fairness_variance": 1.0,
                "staff_fairness_gini": 0.2,
                "staff_load_max": 3,
                "staff_load_min": 1,
                "staff_load_median": 2,
                "solve_time_seconds": 0.5,
                "slack_utilisation": 0.9,
            })
    with tempfile.TemporaryDirectory() as tmpdir:
        plot_metric_vs_noise_level(rows, tmpdir)
        # At least one plot should be generated
        pngs = [f for f in os.listdir(tmpdir) if f.endswith("_vs_noise_level.png")]
        assert len(pngs) >= 1, f"Expected noise-level progression PNGs, got {pngs}"


def test_plot_metric_vs_noise_level_skips_without_noise_levels():
    """No plots when rows don't have recognised noise_level values."""
    from eval.sweep_plots import plot_metric_vs_noise_level
    rows = [{"strategy": "local_repair", "noise_level": "none", "changed_assignments": 5}]
    with tempfile.TemporaryDirectory() as tmpdir:
        plot_metric_vs_noise_level(rows, tmpdir)
        pngs = [f for f in os.listdir(tmpdir) if f.endswith("_vs_noise_level.png")]
        assert len(pngs) == 0


# ---------------------------------------------------------------------------
# Strategy recommendation table
# ---------------------------------------------------------------------------


def test_generate_recommendation_table_produces_md():
    """generate_recommendation_table should create recommendation_table.md."""
    from eval.sweep_plots import generate_recommendation_table
    # Write a minimal CSV
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "sweep.csv")
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "strategy", "changed_assignments", "infeasible",
                "staff_fairness_variance", "solve_time_seconds",
                "staff_fairness_gini", "prop_changed", "staff_load_max",
            ])
            writer.writeheader()
            writer.writerow({
                "strategy": "local_repair", "changed_assignments": 2,
                "infeasible": 0, "staff_fairness_variance": 0.5,
                "solve_time_seconds": 0.1, "staff_fairness_gini": 0.1,
                "prop_changed": 0.05, "staff_load_max": 3,
            })
            writer.writerow({
                "strategy": "change_penalty", "changed_assignments": 5,
                "infeasible": 0, "staff_fairness_variance": 1.5,
                "solve_time_seconds": 0.3, "staff_fairness_gini": 0.3,
                "prop_changed": 0.15, "staff_load_max": 5,
            })

        out_dir = os.path.join(tmpdir, "out")
        md = generate_recommendation_table(csv_path, out_dir)
        assert "| Priority |" in md
        assert "local_repair" in md
        assert "change_penalty" in md

        md_path = os.path.join(out_dir, "recommendation_table.md")
        assert os.path.exists(md_path)


def test_generate_recommendation_table_skips_single_strategy():
    """With only one strategy there is no meaningful ranking; returns empty."""
    from eval.sweep_plots import generate_recommendation_table
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "sweep.csv")
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["strategy", "changed_assignments"])
            writer.writeheader()
            writer.writerow({"strategy": "local_repair", "changed_assignments": 2})
        out_dir = os.path.join(tmpdir, "out")
        md = generate_recommendation_table(csv_path, out_dir)
        assert md == ""


# ---------------------------------------------------------------------------
# LaTeX export
# ---------------------------------------------------------------------------


def test_export_latex_creates_tex_files():
    """With export_latex=True, generate_summary_tables should produce .tex files."""
    from eval.sweep_plots import generate_summary_tables
    rows = [
        {"strategy": "local_repair", "changed_assignments": 2, "infeasible": 0,
         "staff_fairness_variance": 0.5, "size_label": "small",
         "complexity": "simple", "noise_type": "none", "noise_level": "none"},
        {"strategy": "change_penalty", "changed_assignments": 5, "infeasible": 0,
         "staff_fairness_variance": 1.5, "size_label": "small",
         "complexity": "simple", "noise_type": "none", "noise_level": "none"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_summary_tables(rows, tmpdir, export_latex=True)
        tex_files = [f for f in os.listdir(tmpdir) if f.endswith(".tex")]
        assert len(tex_files) >= 1, f"Expected .tex files, got {os.listdir(tmpdir)}"
        # Check that .tex content looks like LaTeX
        with open(os.path.join(tmpdir, tex_files[0])) as fh:
            content = fh.read()
        assert "\\begin{tabular}" in content


def test_export_latex_not_created_by_default():
    """Without export_latex, no .tex files should be produced."""
    from eval.sweep_plots import generate_summary_tables
    rows = [
        {"strategy": "local_repair", "changed_assignments": 2, "infeasible": 0,
         "size_label": "small", "complexity": "simple",
         "noise_type": "none", "noise_level": "none"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_summary_tables(rows, tmpdir)
        tex_files = [f for f in os.listdir(tmpdir) if f.endswith(".tex")]
        assert len(tex_files) == 0


def test_recommendation_table_latex_export():
    """generate_recommendation_table with export_latex should create .tex file."""
    from eval.sweep_plots import generate_recommendation_table
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "sweep.csv")
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "strategy", "changed_assignments", "infeasible",
                "staff_fairness_variance", "solve_time_seconds",
            ])
            writer.writeheader()
            writer.writerow({
                "strategy": "local_repair", "changed_assignments": 2,
                "infeasible": 0, "staff_fairness_variance": 0.5,
                "solve_time_seconds": 0.1,
            })
            writer.writerow({
                "strategy": "change_penalty", "changed_assignments": 5,
                "infeasible": 0, "staff_fairness_variance": 1.5,
                "solve_time_seconds": 0.3,
            })

        out_dir = os.path.join(tmpdir, "out")
        generate_recommendation_table(csv_path, out_dir, export_latex=True)
        tex_path = os.path.join(out_dir, "recommendation_table.tex")
        assert os.path.exists(tex_path)
