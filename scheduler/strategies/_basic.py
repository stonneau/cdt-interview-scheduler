"""
Basic rescheduling strategies: reschedule_from_scratch and change_penalty.
"""

from typing import Any, Dict, Tuple
import copy

from scheduler.strategies._core import _solve_model


def reschedule_from_scratch(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Ignore the previous schedule and solve from scratch.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data (candidates, time_slots, avail, staff, etc.).
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver / objective parameters forwarded to ``_solve_model``.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    ds["prev_schedule"] = None
    ds["prev_staff_assignment"] = None
    return _solve_model(ds, params, use_prev=False)


def change_penalty(data_store: Dict[str, Any], change_event: Dict[str, Any], params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Solve using a change-penalty objective that penalises moves from the previous schedule.

    Parameters
    ----------
    data_store : Dict[str, Any]
        Problem data including ``prev_schedule`` and ``prev_staff_assignment``.
    change_event : Dict[str, Any]
        Description of the disruption that triggered rescheduling.
    params : Dict[str, Any]
        Solver / objective parameters forwarded to ``_solve_model``.

    Returns
    -------
    Tuple[Dict[str, Any], Dict[str, Any]]
        A tuple of (schedule, metadata).
    """
    ds = copy.deepcopy(data_store)
    return _solve_model(ds, params, use_prev=True)
