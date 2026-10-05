"""Rescheduling strategies package.

Provides eight strategies ranging from optimal CP-SAT solutions to a greedy
heuristic, plus a shared ``_solve_model`` helper and a ``get_strategy``
registry lookup.

Strategies
----------
- ``reschedule_from_scratch`` / ``full`` — ignore previous schedule, solve fresh.
- ``change_penalty`` / ``min_disturbance`` — penalise moves from the baseline.
- ``local_repair`` — restrict solver to a local neighbourhood.
- ``slack_based`` — reserve slack slots, then solve with penalties.
- ``fairness_weighted`` — balanced stability + min-max fairness.
- ``greedy_least_loaded`` — fast heuristic (no solver).
- ``variance_minimizing`` — balanced stability + variance fairness.
- ``plns`` — Parallel Large Neighborhood Search (Destroy and Repair).
"""

from scheduler.strategies._core import _solve_model
from scheduler.strategies._basic import reschedule_from_scratch, change_penalty
from scheduler.strategies._advanced import (
    local_repair,
    slack_based,
    fairness_weighted,
    greedy_least_loaded,
    variance_minimizing,
)
from scheduler.strategies._plns import plns

from typing import Any, Callable, Dict

# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_STRATEGIES: Dict[str, Callable] = {
    "full": reschedule_from_scratch,
    "reschedule_from_scratch": reschedule_from_scratch,
    "change_penalty": change_penalty,
    "min_disturbance": change_penalty,
    "local_repair": local_repair,
    "slack_based": slack_based,
    "fairness_weighted": fairness_weighted,
    "greedy_least_loaded": greedy_least_loaded,
    "variance_minimizing": variance_minimizing,
    "plns": plns,
}

STRATEGY_REGISTRY = _STRATEGIES


def get_strategy(name: str) -> Callable:
    """Look up a strategy function by name (case-insensitive).

    Parameters
    ----------
    name : str
        Strategy name.  Falls back to ``"change_penalty"`` when empty.

    Returns
    -------
    Callable
        The strategy function.

    Raises
    ------
    KeyError
        If no strategy matches *name*.
    """
    if not name:
        name = "change_penalty"
    n = name.lower()
    if n in _STRATEGIES:
        return _STRATEGIES[n]
    for key in _STRATEGIES:
        if key.lower() == n:
            return _STRATEGIES[key]
    raise KeyError(f"Unknown strategy '{name}'")


__all__ = [
    "_solve_model",
    "reschedule_from_scratch",
    "change_penalty",
    "local_repair",
    "slack_based",
    "fairness_weighted",
    "greedy_least_loaded",
    "variance_minimizing",
    "plns",
    "get_strategy",
    "_STRATEGIES",
    "STRATEGY_REGISTRY",
]
