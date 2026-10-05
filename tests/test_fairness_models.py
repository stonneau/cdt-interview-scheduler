"""Workload fairness: no idle-slot cheating, and leads balanced among themselves."""

import collections
import copy

import pytest

pytest.importorskip("scipy")

from scheduler.solver import solve_initial_schedule  # noqa: E402
from webapi.example import make_example  # noqa: E402
from data_models.csv_text import parse_availability_text, parse_staff_text  # noqa: E402
from data_models.loaders import objects_to_solver_inputs_from_models, unify_slots  # noqa: E402


def cdt_dataset(n_candidates=15, n_staff=10, n_leads=3, n_days=6):
    """A small anonymised CDT-style instance (3 leads, 7 other staff, 60 slots, 15 applicants)."""
    t = make_example(7, n_candidates, n_staff, n_leads, n_days)
    cands, sa = parse_availability_text(t["applicants"])
    staff, ss = parse_staff_text(t["staff"])
    cids, sids, avail, savail, required, fp = objects_to_solver_inputs_from_models(cands, staff)
    return {"candidates": cids, "time_slots": sorted(unify_slots(sa, ss)), "avail": avail, "staff": sids,
            "staff_avail": savail, "required_staff": required, "forbidden_pairs": fp,
            "prev_schedule": {}, "prev_staff_assignment": None}


def solve(ds, **params):
    captured = []
    sched, meta = solve_initial_schedule(
        data_store=copy.deepcopy(ds),
        params={"min_staff_per_slot": 2, "max_staff_per_slot": 2, "time_limit": 8, "persist": False,
                "random_seed": 0, **params, "_result_hook": lambda kw, r: captured.append((kw, r))})
    assert meta["status"] in ("OPTIMAL", "FEASIBLE"), meta["status"]
    kw, res = captured[0]
    real = collections.Counter(s for panel in meta["staff_assignment"].values() for s in panel)
    seen = {s: sum(res.value_y(s, t) for t in kw["time_slots"]) for s in kw["staff"]}
    return sched, meta, {s: real.get(s, 0) for s in kw["staff"]}, seen


@pytest.fixture(scope="module")
def ds():
    return cdt_dataset()


@pytest.mark.parametrize("backend", ["mip", "cpsat"])
def test_objective_sees_exactly_the_published_workloads(ds, backend):
    """Default model: what the fairness terms count is what the published schedule contains."""
    if backend == "cpsat":
        pytest.importorskip("ortools")
    _, _, real, seen = solve(ds, fairness="min_dev", backend=backend)
    assert real == seen


def test_original_model_hides_idle_assignments(ds):
    """allow_idle_staff=True reproduces the original model: staff parked on empty slots."""
    pytest.importorskip("ortools")
    _, _, real, seen = solve(ds, fairness="min_dev", backend="cpsat", allow_idle_staff=True)
    assert sum(seen.values()) > sum(real.values())


@pytest.mark.parametrize("backend", ["mip", "cpsat"])
def test_balanced_mode_balances_leads_and_others(ds, backend):
    if backend == "cpsat":
        pytest.importorskip("ortools")
    leads = sorted({l for v in ds["required_staff"].values() for l in v})
    _, _, real, seen = solve(ds, fairness="balanced", backend=backend)
    lead_loads = [real[l] for l in leads]
    other_loads = [v for k, v in real.items() if k not in leads]
    assert max(lead_loads) - min(lead_loads) <= 1, lead_loads      # 15 interviews over 3 leads
    assert max(other_loads) - min(other_loads) <= 2, sorted(other_loads)
    assert sum(lead_loads) <= len(ds["candidates"]) + 1, "leads doubled up on panels needlessly"
    assert real == seen


def test_balanced_is_much_fairer_for_leads_than_the_original_min_dev(ds):
    """The original min_dev objective is flat for leads (all above the mean)."""
    leads = sorted({l for v in ds["required_staff"].values() for l in v})
    spread = {}
    for mode in ("balanced", "min_dev"):
        _, _, real, _ = solve(ds, fairness=mode, backend="mip")
        spread[mode] = max(real[l] for l in leads) - min(real[l] for l in leads)
    assert spread["balanced"] <= 1
    assert spread["balanced"] <= spread["min_dev"]
