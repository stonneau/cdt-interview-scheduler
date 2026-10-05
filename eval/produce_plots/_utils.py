"""Shared utility helpers for the produce_plots package.

Provides schedule loading, output directory creation, and change-counting
helpers used by multiple plotting submodules.
"""
from pathlib import Path
from typing import Dict, Any, List


def load_schedules(base_dir: str, run_id: str):
    """Load schedules and change events from a DataStore.

    Parameters
    ----------
    base_dir : str
        Root directory that contains run sub-directories.
    run_id : str
        Identifier of the specific run to load.

    Returns
    -------
    tuple[list, list]
        A ``(schedules, events)`` pair where *schedules* is a list of
        schedule dicts and *events* is a list of change-event dicts.
    """
    from data_models.store import DataStore

    ds = DataStore(config={"base_dir": base_dir, "run_id": run_id})
    print(f"Loading schedules and events from DataStore at {base_dir}/{run_id}...")
    schedules = list(ds.list_schedules())
    events = list(ds.iter_change_events())
    return schedules, events


def ensure_outdir(out_dir: Path):
    """Create *out_dir* and any missing parents.

    Parameters
    ----------
    out_dir : Path
        Directory path to create.
    """
    out_dir.mkdir(parents=True, exist_ok=True)


def compute_num_changed(baseline: Dict[str, Any], target: Dict[str, Any]) -> int:
    """Return number of candidates whose assigned slot differs.

    Treats added or removed candidates as changed.

    Parameters
    ----------
    baseline : dict
        Mapping of candidate → slot for the baseline schedule.
    target : dict
        Mapping of candidate → slot for the target schedule.

    Returns
    -------
    int
        Count of candidates with differing assignments.
    """
    if not baseline and not target:
        return 0
    baseline = baseline or {}
    target = target or {}
    keys = set(list(baseline.keys()) + list(target.keys()))
    changed = 0
    for k in keys:
        if baseline.get(k) != target.get(k):
            changed += 1
    return changed


def infer_change_idx(meta: Dict[str, Any], events: List[Dict[str, Any]]) -> int:
    """Infer a change/event index from schedule metadata.

    Checks several plausible keys that may be present in saved metadata.
    If an event id is present and matches an event in the provided list,
    return that event's index (0-based).  Otherwise return 0.

    Parameters
    ----------
    meta : dict
        Schedule metadata dictionary.
    events : list[dict]
        Ordered list of change-event dictionaries.

    Returns
    -------
    int
        Zero-based index of the matching change event.
    """
    if not meta:
        return 0
    for key in ("change_idx", "change_index", "change_event_index", "event_idx", "change_num"):
        v = meta.get(key)
        if isinstance(v, int):
            return v
        try:
            if v is not None:
                return int(v)
        except Exception:
            pass

    for key in ("change_event_id", "event_id", "applied_event_id", "source_event_id"):
        eid = meta.get(key)
        if not eid:
            continue
        for idx, ev in enumerate(events):
            if ev.get("id") == eid or ev.get("event_id") == eid:
                return idx

    return 0
