"""Shared helpers and metric definitions for sweep analysis.

Provides small utility functions and data-driven metric registries used
across all sweep-plot sub-modules.
"""
from typing import List, Dict, Any
from collections import defaultdict


# Each tuple: (csv_column, human_label, higher_is_better)
_METRIC_DEFS = [
    ("changed_assignments", "Changed Assignments", False),
    ("prop_changed", "Prop Changed", False),
    ("infeasible", "Infeasible Rate", False),
    ("timeout", "Timeout Rate", False),
    ("optimal", "Optimal Rate", True),
    ("staff_fairness_variance", "Fairness Var", False),
    ("staff_fairness_gini", "Gini Coeff", False),
    ("staff_load_max", "Max Staff Load", False),
    ("staff_load_min", "Min Staff Load", True),
    ("staff_load_median", "Median Staff Load", None),
    ("solve_time_seconds", "Solve Time (s)", False),
    ("slack_utilisation", "Slack Util", None),
]

# Metrics that should be aggregated with *mean* instead of median.
_MEAN_AGG_METRICS = {"infeasible", "timeout", "optimal"}


def _safe_float(value, default=0.0) -> float:
    """Convert *value* to float, returning *default* on failure.

    Parameters
    ----------
    value : Any
        The value to convert.
    default : float
        Fallback returned when conversion fails.

    Returns
    -------
    float
        The converted value or *default*.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _feasible_only(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only rows where the reschedule produced a usable schedule.

    Rows with ``infeasible == 1`` (INFEASIBLE, MODEL_INVALID, or UNKNOWN/
    timeout) are excluded so that their zero-valued metrics don't skew
    aggregates for non-rate metrics.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows to filter.

    Returns
    -------
    list of dict
        Subset of *rows* that are feasible.
    """
    return [r for r in rows if _safe_float(r.get("infeasible", 0)) == 0]


def _group_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group *rows* into a dict keyed by the value of *key* in each row.

    Parameters
    ----------
    rows : list of dict
        Sweep result rows.
    key : str
        Dictionary key to group by.

    Returns
    -------
    dict[str, list[dict]]
        Mapping from group value to the rows belonging to that group.
    """
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r.get(key, "unknown")].append(r)
    return dict(groups)
