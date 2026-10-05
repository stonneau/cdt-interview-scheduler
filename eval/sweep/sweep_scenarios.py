"""Generate parameter grids for sweep_runner experiments.

Provides convenient presets for dataset sizes, staffing ratios, noise scenarios,
penalty-weight grids, and strategies. Consumers should iterate the returned
generator and pass dicts into `eval.sweep_runner.run_single_experiment` or
`run_sweep`.

The central helper is ``strategy_comparison_iter`` which sweeps strategies
across sizes, complexities, noise levels, and seeds — producing a manageable
grid for comparative analysis.

Example usage:
    from eval.sweep.sweep_scenarios import strategy_comparison_iter
    for params in strategy_comparison_iter(strategies=["change_penalty", "local_repair"]):
        print(params)
"""
from typing import Iterable, Dict, Any, List, Optional
import math
from scheduler import strategies as strategies_mod


# ---------------------------------------------------------------------------
# Preset helpers
# ---------------------------------------------------------------------------

def _size_presets():
    """Dataset size presets.

    Each entry contains the synthetic-generator kwargs **plus** a
    ``"size_label"`` key that is carried through to the CSV output.
    """
    return {
        "small": {"num_candidates": 20, "num_staff": 8, "num_days": 4, "slots_per_day": 10},
        "medium": {"num_candidates": 60, "num_staff": 20, "num_days": 6, "slots_per_day": 20},
        "large": {"num_candidates": 200, "num_staff": 60, "num_days": 14, "slots_per_day": 20},
    }


def _complexity_presets() -> List[str]:
    """Availability-complexity levels supported by data_generators."""
    return ["simple", "medium", "complex"]


def _noise_presets(num_staff: int = 8, num_candidates: int = 20):
    """Noise scenarios scaled to dataset size.

    ``num_people`` is set proportionally so that the *fraction* of affected
    entities stays meaningful across small and large datasets.

    All four registered noise types are covered at four severity levels
    (low / medium / high / extreme) so that sweeps can produce a
    research-grade comparison of how strategies cope with very different
    amounts and kinds of disruption.

    The ``noise_level`` tag carried through to the CSV enables grouped
    analysis across noise types at the same severity.
    """
    # -- unavailability noise (slots blocked) --------------------------------
    su_lo   = max(1, int(math.ceil(num_staff * 0.10)))
    su_med  = max(1, int(math.ceil(num_staff * 0.35)))
    su_hi   = max(1, int(math.ceil(num_staff * 0.60)))
    su_ext  = max(1, int(math.ceil(num_staff * 0.80)))

    cu_lo   = max(1, int(math.ceil(num_candidates * 0.10)))
    cu_med  = max(1, int(math.ceil(num_candidates * 0.35)))
    cu_hi   = max(1, int(math.ceil(num_candidates * 0.60)))
    cu_ext  = max(1, int(math.ceil(num_candidates * 0.80)))

    # -- removal noise (entities deleted) ------------------------------------
    sr_lo   = max(1, int(math.ceil(num_staff * 0.05)))
    sr_med  = max(1, int(math.ceil(num_staff * 0.20)))
    sr_hi   = max(1, int(math.ceil(num_staff * 0.40)))
    sr_ext  = max(1, int(math.ceil(num_staff * 0.60)))

    cr_lo   = max(1, int(math.ceil(num_candidates * 0.05)))
    cr_med  = max(1, int(math.ceil(num_candidates * 0.20)))
    cr_hi   = max(1, int(math.ceil(num_candidates * 0.40)))
    cr_ext  = max(1, int(math.ceil(num_candidates * 0.60)))

    return [
        None,
        {"type": "staff_unavailable",    "intensity": 1, "num_people": su_lo,  "noise_level": "low"},
        {"type": "staff_unavailable",    "intensity": 2, "num_people": su_med, "noise_level": "medium"},
        {"type": "staff_unavailable",    "intensity": 3, "num_people": su_hi,  "noise_level": "high"},
        {"type": "staff_unavailable",    "intensity": 4, "num_people": su_ext, "noise_level": "extreme"},
        {"type": "candidate_unavailable","intensity": 1, "num_people": cu_lo,  "noise_level": "low"},
        {"type": "candidate_unavailable","intensity": 2, "num_people": cu_med, "noise_level": "medium"},
        {"type": "candidate_unavailable","intensity": 3, "num_people": cu_hi,  "noise_level": "high"},
        {"type": "candidate_unavailable","intensity": 4, "num_people": cu_ext, "noise_level": "extreme"},
        {"type": "candidate_removal",    "intensity": 1, "num_people": cr_lo,  "noise_level": "low"},
        {"type": "candidate_removal",    "intensity": 2, "num_people": cr_med, "noise_level": "medium"},
        {"type": "candidate_removal",    "intensity": 3, "num_people": cr_hi,  "noise_level": "high"},
        {"type": "candidate_removal",    "intensity": 4, "num_people": cr_ext, "noise_level": "extreme"},
        {"type": "staff_removal",        "intensity": 1, "num_people": sr_lo,  "noise_level": "low"},
        {"type": "staff_removal",        "intensity": 2, "num_people": sr_med, "noise_level": "medium"},
        {"type": "staff_removal",        "intensity": 3, "num_people": sr_hi,  "noise_level": "high"},
        {"type": "staff_removal",        "intensity": 4, "num_people": sr_ext, "noise_level": "extreme"},
    ]


def _penalty_grid():
    # Candidate vs staff change penalty sweep (coarse)
    cand = [0.1, 1.0, 10.0]
    staff = [0.1, 1.0, 10.0]
    pairs = []
    for c in cand:
        for s in staff:
            pairs.append({"candidate_change_penalty_weight": c, "staff_change_penalty_weight": s})
    return pairs


def _strategies() -> List[str]:
    # Expose the registry keys (deduplicated, skip aliases)
    seen = set()
    out = []
    for name, fn in strategies_mod._STRATEGIES.items():
        if fn is not None and id(fn) not in seen:
            seen.add(id(fn))
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Primary iterator: strategy comparison
# ---------------------------------------------------------------------------

def strategy_comparison_iter(
    strategies: Optional[List[str]] = None,
    sizes: Optional[List[str]] = None,
    complexities: Optional[List[str]] = None,
    noise_levels: Optional[List[str]] = None,
    seeds: Optional[List[int]] = None,
    penalty_weights: Optional[Dict[str, float]] = None,
    penalty_scale_values: Optional[List[int]] = None,
    fairness_weight_values: Optional[List[int]] = None,
    persist: bool = False,
    base_dir: str = "data/sweep_runs",
    time_limit: Optional[int] = None,
    num_workers: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield parameter dicts that compare *strategies* across scenarios.

    The grid is:  strategy × size × complexity × noise × seed.

    Penalty weights are held constant (default 1/1) so that the comparison
    isolates strategy behaviour rather than tuning knobs.  Pass
    ``penalty_weights`` to override.

    Parameters
    ----------
    strategies : list of str, optional
        Strategy names to compare.  Defaults to the five distinct strategies.
    sizes : list of str, optional
        Size preset labels (default ``["small", "medium"]``).
    complexities : list of str, optional
        Complexity levels (default ``["simple", "complex"]``).
    noise_levels : list of str or None, optional
        Which noise *types* to include.  ``None`` → all presets including
        the no-noise baseline.  Pass ``["none"]`` for no noise only, or
        ``["staff_unavailable"]`` etc.
    seeds : list of int, optional
        Random seeds (default ``[0, 1, 2]``).
    penalty_weights : dict, optional
        Fixed penalty weights dict.  Defaults to ``{cpw: 1, spw: 1}``.
    penalty_scale_values : list of int, optional
        If provided, sweeps ``penalty_scale`` across these values for
        strategies that use it (``change_penalty`` / ``min_disturbance``,
        ``variance_minimizing``, ``slack_based``, ``fairness_weighted``).
        Other strategies get one run with no explicit penalty_scale
        (they use their own defaults).
        Example: ``[1, 10, 100, 1000]``.
    fairness_weight_values : list of int, optional
        If provided, sweeps ``fairness_weight`` across these values for
        penalty-scale-aware strategies.  Combined with
        ``penalty_scale_values`` this lets you explore the full
        λ_p / λ_f ratio surface.
        Example: ``[1, 10, 50, 100]``.
    persist : bool
        Whether to persist schedules to DataStore.
    base_dir : str
        Base directory for sweep data.
    time_limit : int, optional
        Solver time limit in seconds per experiment.  ``None`` uses the
        sweep_runner default (30 s).  Increase for stress testing to
        separate timeouts from true infeasibility.
    num_workers : int, optional
        Number of CP-SAT search threads per solve.  ``None`` lets OR-Tools
        use all available cores.  Set this when running parallel sweeps to
        avoid CPU over-subscription (e.g. ``2`` with ``max_workers=4``).
    """
    if strategies is None:
        strategies = _strategies()
    if sizes is None:
        sizes = ["small", "medium"]
    if complexities is None:
        complexities = ["simple", "complex"]
    if seeds is None:
        seeds = [0, 1, 2]
    if penalty_weights is None:
        penalty_weights = {"candidate_change_penalty_weight": 1, "staff_change_penalty_weight": 1}

    # Strategies whose objective includes penalty_scale and/or
    # fairness_weight terms.  All five accept penalty_scale (change-penalty
    # multiplier).  fairness_weighted and variance_minimizing also set a
    # scaled fairness_weight by default; sweeping fairness_weight overrides
    # those defaults.  change_penalty/min_disturbance use fairness_weight=1
    # by default (negligible); sweeping it lets the solver trade stability
    # for equity.  slack_based inherits the same objective via _solve_model.
    _PS_STRATEGIES = {
        "change_penalty", "min_disturbance", "variance_minimizing",
        "slack_based", "fairness_weighted",
    }

    size_map = _size_presets()

    for size_name in sizes:
        spec_base = size_map[size_name]
        num_c = spec_base["num_candidates"]
        num_s = spec_base["num_staff"]

        # Build noise scenarios scaled to this dataset size
        all_noises = _noise_presets(num_staff=num_s, num_candidates=num_c)

        # Optionally filter noise scenarios
        if noise_levels is not None:
            filtered: list = []
            for n in all_noises:
                if n is None and "none" in noise_levels:
                    filtered.append(n)
                elif n is not None and n.get("type") in noise_levels:
                    filtered.append(n)
            # Always include the no-noise baseline if nothing matched
            if not filtered:
                filtered = [None]
            noises = filtered
        else:
            noises = all_noises

        for complexity in complexities:
            for strat in strategies:
                # Determine penalty_scale values to sweep for this strategy
                if penalty_scale_values and strat in _PS_STRATEGIES:
                    ps_values = penalty_scale_values
                else:
                    ps_values = [None]  # single run with strategy default

                # Determine fairness_weight values to sweep
                if fairness_weight_values and strat in _PS_STRATEGIES:
                    fw_values = fairness_weight_values
                else:
                    fw_values = [None]

                for ps in ps_values:
                    for fw in fw_values:
                        for noise in noises:
                            for seed in seeds:
                                spec = dict(spec_base, complexity=complexity)
                                p: Dict[str, Any] = {
                                    "dataset": {"type": "synthetic", "spec": spec},
                                    "strategy": strat,
                                    "size_label": size_name,
                                    "noise": noise,
                                    "penalty_weights": dict(penalty_weights),
                                    "random_seed": seed,
                                    "persist": persist,
                                    "base_dir": base_dir,
                                }
                                if ps is not None:
                                    p["penalty_scale"] = ps
                                if fw is not None:
                                    p["fairness_weight"] = fw
                                if time_limit is not None:
                                    p["time_limit"] = time_limit
                                if num_workers is not None:
                                    p["num_workers"] = num_workers
                                yield p


# ---------------------------------------------------------------------------
# Legacy / full-grid iterator
# ---------------------------------------------------------------------------

def default_param_iter(seeds: List[int] = None, sizes: List[str] = None) -> Iterable[Dict[str, Any]]:
    """Yield parameter dicts for sweeps.

    Params returned match the shape expected by `eval/sweep_runner.run_single_experiment`.
    - dataset: {type: 'synthetic', spec: {...}}
    - strategy: strategy name
    - noise: noise dict or None
    - penalty_weights included inline
    - random_seed
    - persist: False by default
    """
    if seeds is None:
        seeds = [0, 1, 2]
    size_map = _size_presets()
    if sizes is None:
        sizes = ["small", "medium", "large"]

    strategies = _strategies()
    penalties = _penalty_grid()

    for size_name in sizes:
        spec_base = size_map[size_name]
        num_c = spec_base["num_candidates"]
        num_s = spec_base["num_staff"]
        noises = _noise_presets(num_staff=num_s, num_candidates=num_c)

        for strat in strategies:
            for noise in noises:
                for pen in penalties:
                    for seed in seeds:
                        spec = dict(spec_base, complexity="simple")
                        params = {
                            "dataset": {"type": "synthetic", "spec": spec},
                            "strategy": strat,
                            "size_label": size_name,
                            "noise": noise,
                            "penalty_weights": pen,
                            "random_seed": seed,
                            "persist": False,
                        }
                        yield params
