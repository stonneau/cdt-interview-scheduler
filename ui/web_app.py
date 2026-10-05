"""
Streamlit web UI for the Interview Scheduler.

Launch with:
    streamlit run ui/web_app.py

Features:
- Upload applicants and staff availability CSVs
- Upload an optional previous-schedule CSV to use as a baseline
- Solve the initial schedule and view it in a table
- Stage changes interactively (staff unavailability, candidate add/remove, etc.)
- Reschedule with a chosen strategy and view stability / robustness metrics
- Generate and display all plots from the eval package (Gantt, bar, Pareto, heatmap)
- Persist every solve to a DataStore so the full history is always available
- Resume a previous session from data/ on restart
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import pandas as pd

# Ensure project root is on sys.path so local packages like `data_models` are importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_models.loaders import (
    _normalize_slot_label,
    load_forbidden_pairs_from_csv,
    parse_forbidden_pairs_inline,
)


# ---------------------------------------------------------------------------
# Page configuration (must be the first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Interview Scheduler",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Lazy imports – keep solver / eval out of module-level so Streamlit can
# import this file even when optional packages are missing.
# ---------------------------------------------------------------------------


def _import_solver():
    """Lazily import the solver entry-points.

    :returns: A tuple of ``(solve_initial_schedule, reschedule)`` callables
        from :mod:`scheduler.solver`.
    :rtype: tuple[callable, callable]
    """
    from scheduler.solver import solve_initial_schedule, reschedule
    return solve_initial_schedule, reschedule


def _import_loaders():
    """Lazily import CSV-loading and conversion helpers.

    :returns: A tuple of ``(load_availability_objects_from_csv,
        load_staff_objects_from_csv, load_prev_schedule_from_csv,
        objects_to_solver_inputs_from_models, unify_slots)`` from
        :mod:`data_models.loaders`.
    :rtype: tuple[callable, callable, callable, callable, callable]
    """
    from data_models.loaders import (
        load_availability_objects_from_csv,
        load_staff_objects_from_csv,
        load_prev_schedule_from_csv,
        objects_to_solver_inputs_from_models,
        unify_slots,
    )
    return (
        load_availability_objects_from_csv,
        load_staff_objects_from_csv,
        load_prev_schedule_from_csv,
        objects_to_solver_inputs_from_models,
        unify_slots,
    )


def _import_metrics():
    """Lazily import the :class:`~eval.metrics.ScheduleMetrics` class.

    :returns: The ``ScheduleMetrics`` class.
    :rtype: type
    """
    from eval.metrics import ScheduleMetrics
    return ScheduleMetrics


def _import_store():
    """Lazily import the :class:`~data_models.store.DataStore` class.

    :returns: The ``DataStore`` class.
    :rtype: type
    """
    from data_models.store import DataStore
    return DataStore


def _import_produce_plots():
    """Lazily import the ``produce_plots.main`` function from :mod:`eval`.

    :returns: The ``main`` callable from :mod:`eval.produce_plots`.
    :rtype: callable
    """
    from eval.produce_plots import main as produce_main
    return produce_main


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------

_STATE_DEFAULTS: Dict[str, Any] = {
    "data_store": None,          # in-memory dict for solver
    "persist_store": None,       # DataStore instance (always created)
    "schedule": None,            # current best schedule {cand: slot}
    "staff_assignment": None,    # current staff_assignment {slot: [staff]}
    "pending_changes": {},       # change_event dict queued by user
    "params": {
        "min_staff_per_slot": 2,
        "fairness": "min_max",
        "staff_change_penalty_weight": 1,
        "time_limit": 10,
        "strategy": "change_penalty",
    },
    "history": [],
    "error": None,
}


def _init_state() -> None:
    """Initialise Streamlit session-state with default values.

    Iterates over :data:`_STATE_DEFAULTS` and sets each key in
    ``st.session_state`` that has not already been set.  Called once at
    module-load time so that every page render has a consistent baseline.

    :returns: Nothing.  Session state is mutated in place.
    :rtype: None
    """
    for key, default in _STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


_init_state()

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _schedule_to_rows(
    schedule: Dict[str, str],
    staff_assignment: Dict[str, List[str]],
) -> List[Dict[str, str]]:
    """Convert a schedule and staff-assignment into display-ready table rows.

    Each row is a dictionary with keys ``"Candidate"``, ``"Time Slot"``, and
    ``"Staff"``, sorted alphabetically by candidate ID.

    :param schedule: Schedule mapping ``{candidate_id: slot_id}``.
    :param staff_assignment: Staff assignment mapping
        ``{slot_id: [staff_id, ...]}``.
    :returns: A list of row dictionaries suitable for
        :func:`pandas.DataFrame` or :func:`streamlit.table`.
    :rtype: list[dict[str, str]]
    """
    rows = []
    for cand, slot in sorted(schedule.items()):
        staff = staff_assignment.get(slot, [])
        rows.append(
            {
                "Candidate": cand,
                "Time Slot": slot or "(unassigned)",
                "Staff": ", ".join(staff) if staff else "—",
            }
        )
    return rows


def _save_uploaded_file(uploaded_file) -> str:
    """Persist a Streamlit ``UploadedFile`` to a temporary path on disk.

    The file is written to a system temporary directory so that downstream
    CSV loaders can read it by path.

    :param uploaded_file: A Streamlit ``UploadedFile`` object received from
        a file-uploader widget.
    :returns: Absolute path to the temporary file.
    :rtype: str
    """
    suffix = Path(uploaded_file.name).suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getbuffer())
    tmp.flush()
    tmp.close()
    return tmp.name


def _parse_add_csv(
    uploaded_file,
    expected_slots: List[str],
    entity_kind: str = "candidate",
) -> Tuple[Dict[str, Dict[str, int]], List[str]]:
    """Parse an uploaded availability CSV for new candidates or staff.

    The CSV must have the **same format** as the original applicants / staff
    CSV: header-less, with dates in row 0 (columns 1+) and slot labels in
    row 1, followed by data rows where column 0 is the entity ID and the
    remaining columns are ``yes``/``no`` availability values.

    Validates that the time-slot columns match *expected_slots* exactly.

    Returns
    -------
    avail_map : dict
        ``{entity_id: {slot: 0|1, ...}}``
    new_ids : list[str]
        Ordered list of entity IDs found in the CSV.

    Raises
    ------
    ValueError
        If the CSV is empty, the slot columns do not match, or no data rows
        are present.
    """
    try:
        df = pd.read_csv(uploaded_file, header=None)
    except Exception as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc

    if df.shape[0] < 3:
        raise ValueError(
            "CSV must have at least 3 rows (date row, slot row, and one or more data rows)."
        )

    # Reconstruct time-slot labels the same way the original loaders do.
    date_row = df.iloc[0, 1:].tolist()
    slot_row = df.iloc[1, 1:].tolist()
    # Staff CSV dates may include a trailing time component; strip to date-only
    # just as load_staff_objects_from_csv does.
    if entity_kind == "staff":
        date_row = [str(d).split()[0] for d in date_row]
    csv_slots = [
        f"{d} {_normalize_slot_label(s)}" for d, s in zip(date_row, slot_row)
    ]

    if csv_slots != expected_slots:
        # Build a helpful diff message
        missing = set(expected_slots) - set(csv_slots)
        extra = set(csv_slots) - set(expected_slots)
        parts = []
        if missing:
            parts.append(f"missing slots: {sorted(missing)}")
        if extra:
            parts.append(f"unexpected slots: {sorted(extra)}")
        if not parts:
            parts.append("slot order differs")
        raise ValueError(
            f"Time-slot columns in the uploaded CSV do not match the original. "
            + "; ".join(parts)
        )

    avail_map: Dict[str, Dict[str, int]] = {}
    new_ids: List[str] = []

    for i in range(2, len(df)):
        raw_eid = df.iloc[i, 0]
        if pd.isna(raw_eid):
            continue
        eid = str(raw_eid).strip()
        if not eid:
            continue
        avail_dict: Dict[str, int] = {}
        for j, slot in enumerate(csv_slots):
            val = df.iloc[i, j + 1]
            avail_dict[slot] = 1 if str(val).strip().lower() in ("yes", "if needed") else 0
        avail_map[eid] = avail_dict
        new_ids.append(eid)

    if not new_ids:
        raise ValueError("CSV contains no data rows (only header rows found).")

    return avail_map, new_ids


def _build_data_store(
    applicants_path: str,
    staff_path: str,
    prev_schedule_path: Optional[str],
    lead_ids: Optional[List[str]] = None,
    forbidden_pairs: Optional[set] = None,
) -> Dict[str, Any]:
    """Load CSV files and assemble the in-memory data store for the solver.

    Reads applicant availability, staff availability, and an optional
    previous-schedule CSV, then converts them into the flat dictionaries
    expected by :func:`~scheduler.solver.solve_initial_schedule`.  Missing
    availability entries are defaulted to ``0`` (unavailable) after slot
    unification.

    :param applicants_path: File-system path to the applicants availability
        CSV.
    :param staff_path: File-system path to the staff availability CSV.
    :param prev_schedule_path: Optional path to a previous-schedule CSV for
        the change-penalty objective.  May be ``None``.
    :param lead_ids: Optional list of staff IDs that must be present on
        every panel (lead requirement).
    :param forbidden_pairs: Optional set of ``(candidate, candidate)``
        tuples that must not be scheduled in adjacent slots.
    :returns: A dictionary containing all solver inputs (``candidates``,
        ``time_slots``, ``avail``, ``staff``, ``staff_avail``,
        ``required_staff``, ``forbidden_pairs``, ``prev_schedule``,
        ``prev_staff_assignment``, ``lead_ids``).
    :rtype: dict[str, Any]
    """
    (
        load_availability_objects_from_csv,
        load_staff_objects_from_csv,
        load_prev_schedule_from_csv,
        objects_to_solver_inputs_from_models,
        unify_slots,
    ) = _import_loaders()

    candidates_objs, time_slots1 = load_availability_objects_from_csv(applicants_path)
    staff_objs, time_slots2 = load_staff_objects_from_csv(staff_path)

    candidates, staff, avail, staff_avail, required_staff, fp = (
        objects_to_solver_inputs_from_models(
            candidates_objs, staff_objs,
            lead_ids=lead_ids,
            forbidden_pairs=forbidden_pairs,
        )
    )
    time_slots = unify_slots(time_slots1, time_slots2)

    # After unifying time slots (union of candidate CSV + staff CSV), some
    # slots may exist in the unified set but not in a candidate's or staff
    # member's availability dict (because each CSV only covers its own
    # slots).  Default those missing entries to 0 (unavailable) so the
    # solver never schedules someone at a slot that wasn't in their CSV.
    for c in candidates:
        c_avail = avail.get(c, {})
        for t in time_slots:
            c_avail.setdefault(t, 0)
        avail[c] = c_avail
    for s in staff:
        s_avail = staff_avail.get(s, {})
        for t in time_slots:
            s_avail.setdefault(t, 0)
        staff_avail[s] = s_avail

    prev_schedule: Dict[str, str] = {}
    prev_staff_assignment: Optional[Dict[str, List[str]]] = None
    if prev_schedule_path:
        prev_schedule, prev_staff_assignment = load_prev_schedule_from_csv(prev_schedule_path)

    return {
        "candidates": candidates,
        "time_slots": time_slots,
        "avail": avail,
        "staff": staff,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": fp,
        "prev_schedule": prev_schedule,
        "prev_staff_assignment": prev_staff_assignment,
        # Persist the canonical lead list so rescheduling can inherit it for
        # new candidates without needing to infer it from required_staff.
        "lead_ids": sorted(set(l for leads in required_staff.values() for l in leads)),
    }


def _run_solve(data_store: Dict[str, Any], params: Dict[str, Any], persist_store) -> Tuple[Dict, Dict]:
    """Run the initial-schedule solver and return results.

    Delegates to :func:`~scheduler.solver.solve_initial_schedule`, passing
    the in-memory *data_store* dict and solver *params*.  Persistence is
    always enabled so that the result is recorded in *persist_store*.

    :param data_store: In-memory solver data dictionary as built by
        :func:`_build_data_store`.
    :param params: Solver parameter dictionary (e.g. ``min_staff_per_slot``,
        ``fairness``, ``time_limit``).
    :param persist_store: A :class:`~data_models.store.DataStore` instance
        for persisting the schedule.
    :returns: A tuple of ``(schedule, metadata)`` where *schedule* maps
        ``{candidate_id: slot_id}`` and *metadata* contains solver output
        such as ``staff_assignment``.
    :rtype: tuple[dict, dict]
    """
    solve_initial_schedule, _ = _import_solver()

    p = dict(params)
    p["persist"] = True
    p["_data_store_dict"] = data_store
    # Include lead_ids in params so the solver embeds them in saved metadata;
    # this allows _resume_run to recover the lead configuration.
    if "lead_ids" in data_store:
        p["lead_ids"] = data_store["lead_ids"]
    schedule, metadata = solve_initial_schedule(data_store=persist_store, params=p)
    return schedule, metadata


def _run_reschedule(
    current_ds: Dict[str, Any],
    change_event: Dict[str, Any],
    params: Dict[str, Any],
    persist_store,
) -> Tuple[Dict, Dict]:
    """Apply a change event and reschedule.

    Delegates to :func:`~scheduler.solver.reschedule`, forwarding the
    current solver data, the pending change event, solver parameters, and
    the persistence store.

    :param current_ds: Current in-memory solver data dictionary.
    :param change_event: Dictionary describing the changes to apply (e.g.
        staff unavailability, candidate additions/removals).
    :param params: Solver parameter dictionary including the rescheduling
        ``strategy``.
    :param persist_store: A :class:`~data_models.store.DataStore` instance
        for persisting the updated schedule.
    :returns: A tuple of ``(schedule_new, metadata_new)`` with the
        rescheduled result.
    :rtype: tuple[dict, dict]
    """
    _, reschedule = _import_solver()

    p = dict(params)
    p["persist"] = True
    p["_data_store_dict"] = current_ds
    # Carry lead_ids forward so every saved reschedule also records the lead list.
    if "lead_ids" in current_ds:
        p["lead_ids"] = current_ds["lead_ids"]
    schedule_new, meta_new = reschedule(
        data_store=persist_store,
        change_event=change_event,
        params=p,
    )
    return schedule_new, meta_new


def _compute_metrics(
    schedule: Dict[str, str],
    prev_schedule: Dict[str, str],
    staff_assignment: Dict[str, List[str]],
    time_slots: List[str],
    prev_staff_assignment: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict, Dict]:
    """Compute stability and robustness metrics for a schedule pair.

    Instantiates :class:`~eval.metrics.ScheduleMetrics` and returns the
    results of both metric calculations.

    :param schedule: Current schedule mapping ``{candidate_id: slot_id}``.
    :param prev_schedule: Previous/baseline schedule mapping
        ``{candidate_id: slot_id}``.
    :param staff_assignment: Current staff assignment mapping
        ``{slot_id: [staff_id, ...]}``.
    :param time_slots: Ordered list of all timeslot identifiers.
    :param prev_staff_assignment: Optional previous staff assignment mapping.
        When provided, staff-level stability metrics are also computed.
    :returns: A tuple of ``(stability_dict, robustness_dict)``.
    :rtype: tuple[dict, dict]
    """
    ScheduleMetrics = _import_metrics()
    m = ScheduleMetrics(
        schedule=schedule,
        prev_schedule=prev_schedule,
        staff_assignment=staff_assignment,
        time_slots=time_slots,
        prev_staff_assignment=prev_staff_assignment,
    )
    return m.stability_metrics(), m.robustness_metrics()


def _generate_plots(run_id: str, base_dir: str) -> Optional[Path]:
    """Generate all plots for the given run; return output directory or None.

    ``produce_plots.main()`` writes plots to ``<out_arg>/<run_id>/``, so we
    pass ``<base_dir>/plots`` as the ``--out`` argument and the actual files
    land in ``<base_dir>/plots/<run_id>/``.
    """
    try:
        produce_main = _import_produce_plots()
    except Exception:
        return None

    # produce_plots.main() appends run_id to the --out path, so pass the
    # parent directory.  Actual files will be at plots_root / run_id.
    plots_root = Path(base_dir) / "plots"
    plots_root.mkdir(parents=True, exist_ok=True)
    actual_out = plots_root / run_id  # where files will actually appear

    orig_argv = sys.argv[:]
    sys.argv = [
        "produce_plots",
        "--base", base_dir,
        "--run-id", run_id,
        "--out", str(plots_root),
    ]
    try:
        produce_main()
        return actual_out
    except Exception:
        return None
    finally:
        sys.argv = orig_argv


# Default base directory for all DataStore runs
_BASE_DIR = "data"


def _discover_runs(base_dir: str = _BASE_DIR) -> List[Dict[str, Any]]:
    """Return a list of known runs in *base_dir*, newest first.

    Each entry contains:
        run_id, path, num_schedules, latest_ts (epoch int), latest_ts_str
    """
    base = Path(base_dir)
    if not base.exists():
        return []

    runs = []
    for run_dir in base.iterdir():
        if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
            continue
        sched_dir = run_dir / "schedules"
        if not sched_dir.exists():
            continue
        sched_files = list(sched_dir.glob("*.json"))
        if not sched_files:
            continue
        # Find the most recent created_at across saved schedules
        latest_ts = 0
        num_schedules = len(sched_files)
        for sf in sched_files:
            try:
                with open(sf) as fh:
                    payload = json.load(fh)
                ts = int(payload.get("created_at", 0))
                if ts > latest_ts:
                    latest_ts = ts
            except Exception:
                pass
        if latest_ts:
            ts_str = datetime.datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d %H:%M")
        else:
            ts_str = "unknown"
        runs.append({
            "run_id": run_dir.name,
            "path": run_dir,
            "num_schedules": num_schedules,
            "latest_ts": latest_ts,
            "latest_ts_str": ts_str,
        })

    runs.sort(key=lambda r: r["latest_ts"], reverse=True)
    return runs


def _resume_run(run_id: str, base_dir: str = _BASE_DIR) -> bool:
    """Restore session state from a previously persisted run.

    Loads the DataStore for *run_id* and the latest saved schedule as the
    current schedule / prev_schedule baseline. Returns True on success.
    Availability data (avail/staff_avail) is restored from the saved schedule
    metadata when available; older runs that pre-date this persistence will
    fall back to all-available defaults.
    """
    DataStore = _import_store()
    try:
        ds = DataStore(config={"base_dir": base_dir, "run_id": run_id})
        schedules = sorted(
            list(ds.list_schedules()),
            key=lambda s: (s.get("seq") or 0, s.get("created_at", 0)),
        )
        if not schedules:
            return False

        latest = schedules[-1]
        schedule = latest.get("schedule", {}) or {}
        meta = latest.get("metadata", {}) or {}
        staff_assignment = meta.get("staff_assignment", {}) or {}

        # Recover lead_ids from the saved schedule metadata.  All schedules
        # saved after commit 66e23d0 include a "lead_ids" key in metadata.
        # For older runs we fall back to an empty list (no lead requirement).
        lead_ids: List[str] = list(meta.get("lead_ids") or [])

        # Reconstruct required_staff: every known candidate gets the saved leads.
        candidates_list = sorted(schedule.keys())
        required_staff_resumed = {c: list(lead_ids) for c in candidates_list}

        # Restore the full time_slots universe from the saved metadata.
        # Falling back to occupied-only slots (one per candidate) would make
        # any "add candidate" reschedule infeasible because the model enforces
        # ≤ 1 candidate per slot and there would be no free slot.
        saved_time_slots: List[str] = list(meta.get("time_slots") or [])
        occupied_slots: List[str] = sorted(set(v for v in schedule.values() if v))
        # Use saved_time_slots when available; fall back to occupied_slots for
        # old runs that pre-date time_slots persistence.
        time_slots_restored: List[str] = saved_time_slots if saved_time_slots else occupied_slots

        # Recover forbidden_pairs from saved metadata so they persist
        # across session resumes and apply to future staged changes.
        saved_fp_raw = meta.get("forbidden_pairs") or []
        forbidden_pairs_restored = {tuple(p) for p in saved_fp_raw if len(p) == 2}

        # Restore session state
        st.session_state.persist_store = ds
        st.session_state.schedule = schedule
        st.session_state.staff_assignment = staff_assignment
        st.session_state.history = [
            {
                "label": f"Resumed (seq={s.get('seq', '?')})",
                "schedule": s.get("schedule", {}),
                "staff_assignment": (s.get("metadata") or {}).get("staff_assignment", {}),
                "metadata": s.get("metadata", {}),
            }
            for s in schedules
        ]
        # Restore availability from saved metadata when available (persisted
        # since the avail/staff_avail fix).  Fall back to all-available for
        # older runs that pre-date availability persistence.
        staff_set = sorted({s for sl in staff_assignment.values() for s in sl})

        saved_avail = meta.get("avail")
        if saved_avail is not None and isinstance(saved_avail, dict):
            avail_restored = saved_avail
            # Ensure every candidate has an entry (new candidates added
            # after the save won't be in saved_avail yet).
            for c in candidates_list:
                if c not in avail_restored:
                    avail_restored[c] = {t: 1 for t in time_slots_restored}
        else:
            avail_restored = {c: {t: 1 for t in time_slots_restored} for c in candidates_list}

        saved_staff_avail = meta.get("staff_avail")
        if saved_staff_avail is not None and isinstance(saved_staff_avail, dict):
            staff_avail_restored = saved_staff_avail
            for s in staff_set:
                if s not in staff_avail_restored:
                    staff_avail_restored[s] = {t: 1 for t in time_slots_restored}
        else:
            staff_avail_restored = {s: {t: 1 for t in time_slots_restored} for s in staff_set}

        st.session_state.data_store = {
            "candidates": candidates_list,
            "time_slots": time_slots_restored,
            "avail": avail_restored,
            "staff": staff_set,
            "staff_avail": staff_avail_restored,
            "required_staff": required_staff_resumed,
            "forbidden_pairs": forbidden_pairs_restored,
            "prev_schedule": schedule,
            "prev_staff_assignment": staff_assignment,
            "lead_ids": lead_ids,
        }
        st.session_state.pending_changes = {}
        st.session_state.error = None

        # Pre-fill the lead_ids text field so Page 1 reflects the restored leads.
        if lead_ids:
            st.session_state["lead_ids_input"] = ", ".join(sorted(lead_ids))
        else:
            st.session_state["lead_ids_input"] = "none"

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sidebar – navigation & session info
# ---------------------------------------------------------------------------

st.sidebar.title("📅 Interview Scheduler")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "1 · Load Data & Solve",
        "2 · Stage Changes & Reschedule",
        "3 · Metrics",
        "4 · Plots",
        "5 · History & DataStore",
    ],
)

if st.session_state.persist_store is not None:
    run_id = st.session_state.persist_store.run_id
    resumed = st.session_state.get("_resumed", False)
    label = "🔄 Resumed" if resumed else "🟢 Active"
    st.sidebar.info(f"{label} **Run ID:** `{run_id[:12]}…`")
else:
    st.sidebar.info("No active session yet.")

# ---- Resume previous session widget (always visible in sidebar) ----
st.sidebar.markdown("---")
_prev_runs = _discover_runs(_BASE_DIR)
if _prev_runs:
    with st.sidebar.expander("🔁 Resume previous run", expanded=st.session_state.persist_store is None):
        run_labels = [
            f"{r['run_id'][:14]}… | {r['latest_ts_str']} | {r['num_schedules']} schedules"
            for r in _prev_runs
        ]
        chosen_label = st.selectbox("Select run", run_labels, key="resume_run_select")
        chosen_idx = run_labels.index(chosen_label)
        chosen_run = _prev_runs[chosen_idx]
        if st.button("↩ Resume this run", key="btn_resume"):
            ok = _resume_run(chosen_run["run_id"], _BASE_DIR)
            if ok:
                st.session_state["_resumed"] = True
                st.success(f"Resumed run `{chosen_run['run_id'][:14]}…` — upload CSVs on Page 1 to enable rescheduling.")
                st.rerun()
            else:
                st.error("Could not resume this run (no schedules found).")

st.sidebar.markdown("---")
st.sidebar.caption("Powered by OR-Tools CP-SAT & Streamlit")

# ===========================================================================
# PAGE 1 – Load Data & Solve
# ===========================================================================
if page == "1 · Load Data & Solve":
    st.title("1 · Load Data & Solve Initial Schedule")

    # Show resumed-session banner if applicable
    if st.session_state.get("_resumed") and st.session_state.persist_store is not None:
        resumed_run_id = st.session_state.persist_store.run_id
        st.info(
            f"🔄 **Resumed run** `{resumed_run_id}` — "
            "latest schedule loaded as baseline. Upload CSVs below and click **Solve** "
            "to continue rescheduling within this run, or start fresh."
        )

    st.markdown(
        "Upload your availability CSVs and (optionally) a previous schedule, then "
        "configure solver parameters and click **Solve**."
    )

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Input files")
        applicants_file = st.file_uploader(
            "Applicants availability CSV",
            type=["csv"],
            key="applicants_file",
        )
        staff_file = st.file_uploader(
            "Staff availability CSV",
            type=["csv"],
            key="staff_file",
        )
        lead_ids_input = st.text_input(
            "Lead staff IDs (comma-separated)",
            value="",
            key="lead_ids_input",
            help=(
                "Specify which staff members are leads. "
                "Leave blank to auto-detect: staff whose IDs start with 'lead' are treated as leads. "
                "Enter IDs explicitly (e.g. 'alice, bob') to override auto-detection. "
                "Enter 'none' to disable lead requirements entirely."
            ),
        )
        forbidden_pairs_input = st.text_input(
            "Forbidden candidate–staff pairs",
            value="",
            key="forbidden_pairs_input",
            help=(
                "Pairs of (candidate, staff) that must NOT be in the same interview. "
                "Format: 'candidate1:staff1, candidate2:staff2'. "
                "Leave blank for no restrictions."
            ),
        )
        forbidden_pairs_file = st.file_uploader(
            "Forbidden pairs CSV (optional)",
            type=["csv"],
            key="forbidden_pairs_file",
            help=(
                "Upload a CSV with forbidden candidate–staff pairings. "
                "Supports two formats: (1) simple 'candidate_id,staff_id' columns, or "
                "(2) real-data format with 'Surname, First name(s), Potential Supervisors' columns. "
                "Pairs from the file are merged with any inline pairs above."
            ),
        )
        prev_schedule_file = st.file_uploader(
            "Previous schedule CSV (optional)",
            type=["csv"],
            key="prev_schedule_file",
        )

    with col_right:
        st.subheader("Solver parameters")
        min_staff = st.number_input(
            "Min staff per slot", min_value=1, max_value=10, value=2, step=1
        )
        fairness = st.selectbox(
            "Fairness objective",
            ["min_max", "none", "min_dev", "balanced"],
            index=0,
        )
        staff_penalty = st.number_input(
            "Staff change penalty weight",
            min_value=0,
            max_value=100,
            value=1,
            step=1,
        )
        strategy = st.selectbox(
            "Solve strategy",
            [
                "change_penalty",
                "full",
                "local_repair",
                "slack_based",
                "fairness_weighted",
                "variance_minimizing",
                "greedy_least_loaded",
            ],
            index=0,
        )
        time_limit = st.number_input(
            "Time limit (seconds)", min_value=1, max_value=300, value=10, step=1
        )
        allow_parallel = st.checkbox(
            "Allow parallel interviews",
            value=False,
            help="When enabled, multiple candidates can interview at the same time with different staff panels.",
        )
        if allow_parallel:
            max_parallel = st.number_input(
                "Max parallel slots",
                min_value=2,
                max_value=10,
                value=2,
                step=1,
                help="Maximum number of interviews that can run in parallel at each time slot.",
            )
        else:
            max_parallel = 2

    st.markdown("---")

    if st.button("🔍 Solve Initial Schedule", type="primary"):
        if applicants_file is None or staff_file is None:
            st.error("Please upload both applicants and staff CSV files.")
        else:
            with st.spinner("Solving… this may take a few seconds."):
                try:
                    DataStore = _import_store()

                    app_path = _save_uploaded_file(applicants_file)
                    staff_path = _save_uploaded_file(staff_file)
                    prev_path = (
                        _save_uploaded_file(prev_schedule_file)
                        if prev_schedule_file
                        else None
                    )

                    # Parse lead IDs from the text input
                    lead_ids_raw = (lead_ids_input or "").strip()
                    if lead_ids_raw.lower() == "none":
                        # Explicit "none" → disable lead requirements
                        parsed_lead_ids: Optional[List[str]] = []
                    elif lead_ids_raw:
                        # Explicit list → parse comma-separated IDs
                        parsed_lead_ids = [s.strip() for s in lead_ids_raw.split(",") if s.strip()]
                    else:
                        # Blank → auto-detect from name prefix (pass None)
                        parsed_lead_ids = None

                    # Parse forbidden pairs from text input and/or CSV upload
                    raw_forbidden_pairs_input = (forbidden_pairs_input or "").strip()
                    parsed_forbidden_pairs = (
                        parse_forbidden_pairs_inline(raw_forbidden_pairs_input)
                        if raw_forbidden_pairs_input else set()
                    )

                    # Merge pairs from uploaded CSV file (if any)
                    if forbidden_pairs_file is not None:
                        fp_path = _save_uploaded_file(forbidden_pairs_file)
                        try:
                            csv_fp = load_forbidden_pairs_from_csv(fp_path)
                            parsed_forbidden_pairs |= csv_fp
                        finally:
                            try:
                                os.unlink(fp_path)
                            except Exception:
                                pass

                    ds_dict = _build_data_store(
                        app_path, staff_path, prev_path,
                        lead_ids=parsed_lead_ids,
                        forbidden_pairs=parsed_forbidden_pairs if parsed_forbidden_pairs else None,
                    )

                    # Show forbidden pairs if any are active
                    active_forbidden = ds_dict.get("forbidden_pairs", set())
                    if active_forbidden:
                        pairs_str = ", ".join(
                            f"{c} ✕ {s}" for c, s in sorted(active_forbidden)
                        )
                        st.info(f"🚫 Forbidden pairs: {pairs_str}")

                    # Show which staff are treated as leads so user can verify.
                    # Derive directly from the stored lead_ids key rather than
                    # inferring from per-candidate required_staff entries.
                    active_leads = ds_dict.get("lead_ids", [])
                    if active_leads:
                        st.info(f"🎯 Lead staff detected: {', '.join(sorted(active_leads))}")
                    else:
                        st.info("ℹ️ No lead requirements — all staff slots are interchangeable.")

                    # Reuse the existing persist_store when continuing a resumed run
                    # so all new schedules land in the same run directory.
                    if st.session_state.get("_resumed") and st.session_state.persist_store is not None:
                        persist_store = st.session_state.persist_store
                        # Carry over the resumed baseline if no explicit prev CSV was uploaded
                        if not prev_path and st.session_state.schedule:
                            ds_dict["prev_schedule"] = st.session_state.schedule
                            ds_dict["prev_staff_assignment"] = st.session_state.staff_assignment or {}
                    else:
                        persist_store = DataStore(config={"base_dir": _BASE_DIR})

                    params = {
                        "min_staff_per_slot": int(min_staff),
                        "fairness": fairness,
                        "staff_change_penalty_weight": int(staff_penalty),
                        "time_limit": float(time_limit),
                        "strategy": strategy,
                        "allow_parallel": bool(allow_parallel),
                        "max_parallel": int(max_parallel),
                    }

                    schedule, metadata = _run_solve(ds_dict, params, persist_store)
                    staff_assignment = metadata.get("staff_assignment", {})

                    st.session_state.data_store = ds_dict
                    st.session_state.persist_store = persist_store
                    st.session_state.schedule = schedule
                    st.session_state.staff_assignment = staff_assignment
                    st.session_state.params = params
                    st.session_state.pending_changes = {}
                    st.session_state["_resumed"] = False  # now a fresh active session
                    # Append to history (preserve resumed history if present)
                    if not st.session_state.history:
                        st.session_state.history = []
                    solve_num = len([e for e in st.session_state.history if not e["label"].startswith("Resumed")])
                    label = "Initial solve" if solve_num == 0 else f"Solve #{solve_num + 1}"
                    st.session_state.history.append(
                        {
                            "label": label,
                            "schedule": copy.deepcopy(schedule),
                            "staff_assignment": copy.deepcopy(staff_assignment),
                            "metadata": metadata,
                        }
                    )
                    st.session_state.error = None

                    st.session_state.data_store["prev_schedule"] = schedule or {}
                    st.session_state.data_store["prev_staff_assignment"] = staff_assignment or {}

                    for p in [app_path, staff_path] + ([prev_path] if prev_path else []):
                        try:
                            os.unlink(p)
                        except Exception:
                            pass

                    st.success(
                        f"✅ Solved! Status: {metadata.get('status', '?')} | "
                        f"Assigned: {len(schedule)} candidates | "
                        f"Solve time: {metadata.get('solve_time_seconds', 0):.2f}s"
                    )

                except Exception as exc:
                    st.session_state.error = traceback.format_exc()
                    st.error(f"Solve failed: {exc}")

    if st.session_state.schedule:
        st.subheader("Current Schedule")
        rows = _schedule_to_rows(
            st.session_state.schedule,
            st.session_state.staff_assignment or {},
        )
        st.dataframe(rows, use_container_width=True)

    if st.session_state.error:
        with st.expander("Error details"):
            st.code(st.session_state.error)

# ===========================================================================
# PAGE 2 – Stage Changes & Reschedule
# ===========================================================================
elif page == "2 · Stage Changes & Reschedule":
    st.title("2 · Stage Changes & Reschedule")

    if st.session_state.data_store is None:
        st.warning("No active session. Please complete **Step 1** first.")
    else:
        ds = st.session_state.data_store
        candidates: List[str] = list(ds.get("candidates", []))
        staff_list: List[str] = list(ds.get("staff", []))
        time_slots: List[str] = list(ds.get("time_slots", []))

        pending = st.session_state.pending_changes
        if pending:
            with st.expander("📋 Pending changes", expanded=True):
                for k, v in pending.items():
                    st.write(f"**{k}:** {v}")
        else:
            st.info("No pending changes. Add changes below, then click **Reschedule**.")

        st.markdown("---")

        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "Staff unavailable",
            "Candidate unavailable",
            "Bulk unavailability",
            "Remove candidate",
            "Add candidate",
            "Remove staff",
            "Add staff",
        ])

        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                su_staff = st.selectbox("Staff member", staff_list, key="su_staff") if staff_list else st.text_input("Staff ID", key="su_staff_text")
            with col2:
                su_slot = st.selectbox("Time slot", time_slots, key="su_slot") if time_slots else st.text_input("Time slot", key="su_slot_text")
            if st.button("➕ Queue staff unavailable", key="btn_su"):
                s = st.session_state.get("su_staff") or st.session_state.get("su_staff_text", "")
                t = st.session_state.get("su_slot") or st.session_state.get("su_slot_text", "")
                if s and t:
                    pending.setdefault("staff_unavailable", []).append((s, t))
                    if s in ds.get("staff_avail", {}):
                        ds["staff_avail"][s][t] = 0
                    st.success(f"Queued: staff {s} unavailable at {t}")
                else:
                    st.error("Please select both a staff member and a time slot.")

        with tab2:
            col1, col2 = st.columns(2)
            with col1:
                cu_cand = st.selectbox("Candidate", candidates, key="cu_cand") if candidates else st.text_input("Candidate ID", key="cu_cand_text")
            with col2:
                cu_slot_options = ["(all slots)"] + time_slots
                cu_slot = st.selectbox("Time slot (or all)", cu_slot_options, key="cu_slot")
            if st.button("➕ Queue candidate unavailable", key="btn_cu"):
                c = st.session_state.get("cu_cand") or st.session_state.get("cu_cand_text", "")
                t_sel = cu_slot if cu_slot != "(all slots)" else None
                if c:
                    if t_sel:
                        pending.setdefault("candidate_unavailable", []).append((c, t_sel))
                        if c in ds.get("avail", {}):
                            ds["avail"][c][t_sel] = 0
                        st.success(f"Queued: candidate {c} unavailable at {t_sel}")
                    else:
                        pending.setdefault("candidate_unavailable", []).append(c)
                        if c in ds.get("avail", {}):
                            for _t in time_slots:
                                ds["avail"][c][_t] = 0
                        st.success(f"Queued: candidate {c} unavailable (all slots)")
                else:
                    st.error("Please select a candidate.")

        with tab3:
            st.markdown("Select multiple staff/candidates and dates to mark unavailable at once.")

            # Extract unique dates from time slots
            _dates_in_slots = sorted(set(
                t.split()[0] for t in time_slots if " " in t
            ))

            bulk_type = st.radio(
                "Entity type",
                ["Staff", "Candidates"],
                key="bulk_type",
                horizontal=True,
            )

            if bulk_type == "Staff":
                bulk_entities = st.multiselect(
                    "Select staff members",
                    staff_list,
                    key="bulk_staff_sel",
                )
            else:
                bulk_entities = st.multiselect(
                    "Select candidates",
                    candidates,
                    key="bulk_cand_sel",
                )

            bulk_date_sel = st.multiselect(
                "Select dates to mark unavailable",
                _dates_in_slots,
                key="bulk_date_sel",
            )

            # Show which slots will be affected
            _bulk_affected_slots = [
                t for t in time_slots
                if any(t.startswith(d + " ") for d in bulk_date_sel)
            ]
            if bulk_date_sel:
                st.caption(f"This will affect **{len(_bulk_affected_slots)}** slot(s) × **{len(bulk_entities)}** entity/entities = **{len(_bulk_affected_slots) * len(bulk_entities)}** unavailability entries.")

            if st.button("➕ Queue bulk unavailability", key="btn_bulk_unavail"):
                if not bulk_entities:
                    st.error("Please select at least one entity.")
                elif not bulk_date_sel:
                    st.error("Please select at least one date.")
                else:
                    count = 0
                    if bulk_type == "Staff":
                        for s in bulk_entities:
                            for t in _bulk_affected_slots:
                                pending.setdefault("staff_unavailable", []).append((s, t))
                                if s in ds.get("staff_avail", {}):
                                    ds["staff_avail"][s][t] = 0
                                count += 1
                    else:
                        for c in bulk_entities:
                            for t in _bulk_affected_slots:
                                pending.setdefault("candidate_unavailable", []).append((c, t))
                                if c in ds.get("avail", {}):
                                    ds["avail"][c][t] = 0
                                count += 1
                    st.success(f"Queued: {count} unavailability entries ({len(bulk_entities)} {'staff' if bulk_type == 'Staff' else 'candidates'} × {len(_bulk_affected_slots)} slots)")

        with tab4:
            rc_cand = st.selectbox("Candidate to remove", candidates, key="rc_cand") if candidates else st.text_input("Candidate ID", key="rc_cand_text")
            if st.button("➕ Queue remove candidate", key="btn_rc"):
                c = st.session_state.get("rc_cand") or st.session_state.get("rc_cand_text", "")
                if c:
                    pending.setdefault("remove_candidate", []).append(c)
                    if c in ds.get("candidates", []):
                        ds["candidates"].remove(c)
                        ds["avail"].pop(c, None)
                        ds.get("required_staff", {}).pop(c, None)
                    st.success(f"Queued: remove candidate {c}")
                else:
                    st.error("Please enter a candidate ID.")

        with tab5:
            ac_method = st.radio(
                "How to specify availability?",
                ["All available (default)", "Select unavailable slots", "Upload CSV"],
                key="ac_method",
                horizontal=True,
            )

            if ac_method == "Upload CSV":
                st.markdown(
                    "Upload a CSV with the **same format and time slots** as the "
                    "original applicants CSV. New candidate IDs will be added; "
                    "existing candidates will have their availability refreshed."
                )
                ac_csv = st.file_uploader(
                    "New candidates CSV", type=["csv"], key="ac_csv_upload"
                )
                if st.button("➕ Queue candidates from CSV", key="btn_ac_csv"):
                    if ac_csv is None:
                        st.error("Please upload a CSV file.")
                    else:
                        try:
                            _avail_map, _new_ids = _parse_add_csv(
                                ac_csv, time_slots, entity_kind="candidate",
                            )
                            existing = set(ds.get("candidates", []))
                            added = []
                            refreshed = []
                            for cid, avail_dict in _avail_map.items():
                                if cid in existing:
                                    # Refresh availability for existing candidates
                                    # so resumed sessions pick up CSV unavailability.
                                    ds["avail"][cid] = avail_dict
                                    refreshed.append(cid)
                                    continue
                                pending.setdefault("add_candidate", []).append(cid)
                                ds["candidates"].append(cid)
                                ds["avail"][cid] = avail_dict
                                added.append(cid)
                            if added:
                                st.success(f"Queued {len(added)} new candidate(s): {', '.join(added)}")
                            if refreshed:
                                st.info(f"🔄 Refreshed availability for {len(refreshed)} existing candidate(s): {', '.join(refreshed)}")
                            if not added and not refreshed:
                                st.info("No new candidates to add (all already exist).")
                        except ValueError as exc:
                            st.error(f"CSV validation error: {exc}")
            else:
                ac_cand = st.text_input("New candidate ID", key="ac_cand")
                unavail_slots: List[str] = []
                if ac_method == "Select unavailable slots" and time_slots:
                    unavail_slots = st.multiselect(
                        "Slots where this candidate is **unavailable**",
                        time_slots,
                        key="ac_unavail_slots",
                    )
                if st.button("➕ Queue add candidate", key="btn_ac"):
                    c = ac_cand.strip()
                    if c:
                        pending.setdefault("add_candidate", []).append(c)
                        if c not in ds.get("candidates", []):
                            ds["candidates"].append(c)
                            avail_dict = {t: 1 for t in time_slots}
                            for t in unavail_slots:
                                avail_dict[t] = 0
                            ds["avail"][c] = avail_dict
                        n_unavail = len(unavail_slots)
                        extra = f" ({n_unavail} slot(s) marked unavailable)" if n_unavail else ""
                        st.success(f"Queued: add candidate {c}{extra}")
                    else:
                        st.error("Please enter a candidate ID.")

        with tab6:
            rs_staff = st.selectbox("Staff to remove", staff_list, key="rs_staff") if staff_list else st.text_input("Staff ID", key="rs_staff_text")
            if st.button("➕ Queue remove staff", key="btn_rs"):
                s = st.session_state.get("rs_staff") or st.session_state.get("rs_staff_text", "")
                if s:
                    pending.setdefault("staff_removed", []).append(s)
                    if s in ds.get("staff", []):
                        ds["staff"].remove(s)
                        ds.get("staff_avail", {}).pop(s, None)
                    st.success(f"Queued: remove staff {s}")
                else:
                    st.error("Please select a staff member.")

        with tab7:
            as_method = st.radio(
                "How to specify availability?",
                ["All available (default)", "Select unavailable slots", "Upload CSV"],
                key="as_method",
                horizontal=True,
            )

            if as_method == "Upload CSV":
                st.markdown(
                    "Upload a CSV with the **same format and time slots** as the "
                    "original staff CSV. New staff IDs will be added; "
                    "existing staff will have their availability refreshed."
                )
                as_csv = st.file_uploader(
                    "New staff CSV", type=["csv"], key="as_csv_upload"
                )
                if st.button("➕ Queue staff from CSV", key="btn_as_csv"):
                    if as_csv is None:
                        st.error("Please upload a CSV file.")
                    else:
                        try:
                            _avail_map, _new_ids = _parse_add_csv(
                                as_csv, time_slots, entity_kind="staff",
                            )
                            existing = set(ds.get("staff", []))
                            added = []
                            refreshed = []
                            for sid, avail_dict in _avail_map.items():
                                if sid in existing:
                                    # Refresh availability for existing staff
                                    # so resumed sessions pick up CSV unavailability.
                                    ds.setdefault("staff_avail", {})[sid] = avail_dict
                                    refreshed.append(sid)
                                    continue
                                pending.setdefault("staff_added", []).append(sid)
                                ds["staff"].append(sid)
                                ds.setdefault("staff_avail", {})[sid] = avail_dict
                                added.append(sid)
                            if added:
                                st.success(f"Queued {len(added)} new staff member(s): {', '.join(added)}")
                            if refreshed:
                                st.info(f"🔄 Refreshed availability for {len(refreshed)} existing staff member(s): {', '.join(refreshed)}")
                            if not added and not refreshed:
                                st.info("No new staff to add (all already exist).")
                        except ValueError as exc:
                            st.error(f"CSV validation error: {exc}")
            else:
                as_staff = st.text_input("New staff ID", key="as_staff")
                staff_unavail_slots: List[str] = []
                if as_method == "Select unavailable slots" and time_slots:
                    staff_unavail_slots = st.multiselect(
                        "Slots where this staff member is **unavailable**",
                        time_slots,
                        key="as_unavail_slots",
                    )
                if st.button("➕ Queue add staff", key="btn_as"):
                    s = as_staff.strip()
                    if s:
                        pending.setdefault("staff_added", []).append(s)
                        if s not in ds.get("staff", []):
                            ds["staff"].append(s)
                            avail_dict = {t: 1 for t in time_slots}
                            for t in staff_unavail_slots:
                                avail_dict[t] = 0
                            ds.setdefault("staff_avail", {})[s] = avail_dict
                        n_unavail = len(staff_unavail_slots)
                        extra = f" ({n_unavail} slot(s) marked unavailable)" if n_unavail else ""
                        st.success(f"Queued: add staff {s}{extra}")
                    else:
                        st.error("Please enter a staff ID.")

        st.markdown("---")

        col_a, col_b = st.columns([3, 1])
        with col_a:
            strategy_opts = [
                "change_penalty",
                "full",
                "local_repair",
                "slack_based",
                "fairness_weighted",
                "variance_minimizing",
                "greedy_least_loaded",
            ]
            cur_strategy = st.session_state.params.get("strategy", "change_penalty")
            cur_idx = strategy_opts.index(cur_strategy) if cur_strategy in strategy_opts else 0
            new_strategy = st.selectbox(
                "Strategy for next reschedule",
                strategy_opts,
                index=cur_idx,
                key="reschedule_strategy",
            )
        with col_b:
            if st.button("🗑 Clear pending changes", key="btn_clear"):
                st.session_state.pending_changes = {}
                st.success("Pending changes cleared.")

        # ---- Freeze past dates (optional) ----
        # Extract unique dates from time slots for the date picker.
        _all_dates_str = sorted(set(
            t.split()[0] for t in time_slots if " " in t
        ))
        _all_dates = []
        for d_str in _all_dates_str:
            try:
                _all_dates.append(datetime.date.fromisoformat(d_str))
            except ValueError:
                pass

        frozen_slots_set: set = set()
        if _all_dates:
            with st.expander("🔒 Freeze past dates (optional)", expanded=False):
                st.markdown(
                    "Select a **cutoff date**: **all** interview slots **on or before** "
                    "this date will be frozen — assigned candidates and staff stay "
                    "fixed, and **empty slots are blocked** so the solver cannot use "
                    "them. Staff loads from frozen slots still count for the fairness "
                    "objective. Only slots **after** this date are rescheduled."
                )
                freeze_date = st.date_input(
                    "Freeze slots on or before",
                    value=None,
                    min_value=min(_all_dates),
                    max_value=max(_all_dates),
                    key="freeze_date",
                )
                if freeze_date is not None:
                    frozen_slots_set = {
                        t for t in time_slots
                        if " " in t and t.split()[0] <= str(freeze_date)
                    }
                    st.info(f"🔒 **{len(frozen_slots_set)}** slot(s) will be frozen (on or before {freeze_date}).")

        if st.button("🔄 Reschedule", type="primary", key="btn_reschedule"):
            if not pending:
                st.warning("No pending changes to apply. Stage changes first.")
            elif st.session_state.persist_store is None:
                st.error("No active session. Please complete Step 1.")
            else:
                with st.spinner("Rescheduling…"):
                    try:
                        p = dict(st.session_state.params)
                        p["strategy"] = new_strategy
                        st.session_state.params["strategy"] = new_strategy
                        if frozen_slots_set:
                            p["frozen_slots"] = frozen_slots_set

                        schedule_new, meta_new = _run_reschedule(
                            current_ds=st.session_state.data_store,
                            change_event=pending,
                            params=p,
                            persist_store=st.session_state.persist_store,
                        )
                        staff_assignment_new = meta_new.get("staff_assignment", {})

                        prev_sched = st.session_state.schedule or {}
                        prev_staff = st.session_state.staff_assignment or {}
                        stability, robustness = _compute_metrics(
                            schedule=schedule_new,
                            prev_schedule=prev_sched,
                            staff_assignment=staff_assignment_new,
                            time_slots=st.session_state.data_store.get("time_slots", []),
                            prev_staff_assignment=prev_staff,
                        )

                        st.session_state.schedule = schedule_new
                        st.session_state.staff_assignment = staff_assignment_new
                        st.session_state.data_store["prev_schedule"] = schedule_new
                        st.session_state.data_store["prev_staff_assignment"] = staff_assignment_new
                        st.session_state.pending_changes = {}
                        st.session_state.history.append(
                            {
                                "label": f"Reschedule #{len(st.session_state.history)} ({new_strategy})",
                                "schedule": copy.deepcopy(schedule_new),
                                "staff_assignment": copy.deepcopy(staff_assignment_new),
                                "metadata": meta_new,
                                "stability": stability,
                                "robustness": robustness,
                            }
                        )

                        st.success(
                            f"✅ Rescheduled! Status: {meta_new.get('status', '?')} | "
                            f"Changed: {stability.get('changed_assignments', '?')} candidates | "
                            f"Solve time: {meta_new.get('solve_time_seconds', 0):.2f}s"
                        )

                    except Exception as exc:
                        st.error(f"Reschedule failed: {exc}")
                        with st.expander("Error details"):
                            st.code(traceback.format_exc())

        if st.session_state.schedule:
            st.subheader("Current Schedule")
            rows = _schedule_to_rows(
                st.session_state.schedule,
                st.session_state.staff_assignment or {},
            )
            st.dataframe(rows, use_container_width=True)

# ===========================================================================
# PAGE 3 – Metrics
# ===========================================================================
elif page == "3 · Metrics":
    st.title("3 · Stability & Robustness Metrics")

    if st.session_state.schedule is None:
        st.warning("No active session. Please complete **Step 1** first.")
    else:
        ds = st.session_state.data_store
        sched = st.session_state.schedule
        prev = ds.get("prev_schedule") if ds else {}
        sa = st.session_state.staff_assignment or {}
        time_slots = ds.get("time_slots", []) if ds else []

        stability, robustness = _compute_metrics(
            schedule=sched,
            prev_schedule=prev or {},
            staff_assignment=sa,
            time_slots=time_slots,
            prev_staff_assignment=ds.get("prev_staff_assignment") if ds else None,
        )

        col_s, col_r = st.columns(2)

        with col_s:
            st.subheader("Stability")
            st.metric("Changed assignments", int(stability.get("changed_assignments", 0)))
            st.metric("Proportion changed", f"{stability.get('prop_changed', 0):.2%}")
            st.metric(
                "Temporal deviation (min)",
                f"{stability.get('temporal_deviation_minutes', 0):.1f}",
            )
            st.metric(
                "Weighted change distance",
                f"{stability.get('weighted_change_distance', 0):.1f}",
            )

        with col_r:
            st.subheader("Robustness")
            st.metric(
                "Fairness variance",
                f"{robustness.get('staff_fairness_variance', 0):.4f}",
            )
            st.metric(
                "Fairness Gini",
                f"{robustness.get('staff_fairness_gini', 0):.4f}",
            )
            st.metric("Max staff load", int(robustness.get("staff_load_max", 0)))
            st.metric("Min staff load", int(robustness.get("staff_load_min", 0)))
            st.metric(
                "Slack utilisation",
                f"{robustness.get('slack_utilisation', 0):.2%}",
            )

        st.markdown("---")
        st.subheader("History of reschedule events")
        if st.session_state.history:
            for i, entry in enumerate(st.session_state.history):
                with st.expander(
                    f"Event {i}: {entry['label']}",
                    expanded=(i == len(st.session_state.history) - 1),
                ):
                    meta = entry.get("metadata", {})
                    st.write(
                        f"Status: **{meta.get('status', '?')}** | "
                        f"Solve time: {meta.get('solve_time_seconds', 0):.2f}s | "
                        f"Strategy: {meta.get('strategy', '—')}"
                    )
                    if "stability" in entry:
                        st.write("**Stability:**", entry["stability"])
                    if "robustness" in entry:
                        st.write("**Robustness:**", entry["robustness"])
        else:
            st.info("No history yet.")

# ===========================================================================
# PAGE 4 – Plots
# ===========================================================================
elif page == "4 · Plots":
    st.title("4 · Visualisations")

    if st.session_state.persist_store is None:
        st.warning("No active session. Please complete **Step 1** first.")
    else:
        run_id = st.session_state.persist_store.run_id
        base_dir = str(st.session_state.persist_store.config.get("base_dir", "data"))

        if st.button("📊 Generate / refresh plots", type="primary"):
            with st.spinner("Generating plots…"):
                out_dir = _generate_plots(run_id=run_id, base_dir=base_dir)
                if out_dir is None:
                    st.error("Plot generation failed. See console for details.")
                else:
                    st.success(f"Plots saved to `{out_dir}`")
                    st.session_state["last_plots_dir"] = str(out_dir)

        plots_dir_str = st.session_state.get("last_plots_dir")
        if plots_dir_str:
            plots_dir = Path(plots_dir_str)
            png_files = sorted(plots_dir.glob("*.png"))
            if not png_files:
                st.info("No plot files found yet. Click **Generate / refresh plots** above.")
            else:
                st.markdown("---")
                for png in png_files:
                    with open(png, "rb") as fh:
                        img_bytes = fh.read()
                    st.image(img_bytes, caption=png.stem, use_container_width=True)
        else:
            st.info("Click **Generate / refresh plots** to produce visualisations.")

# ===========================================================================
# PAGE 5 – History & DataStore
# ===========================================================================
elif page == "5 · History & DataStore":
    st.title("5 · History & DataStore")

    if st.session_state.persist_store is None:
        st.warning("No active session. Please complete **Step 1** first.")
    else:
        persist_store = st.session_state.persist_store
        run_id = persist_store.run_id

        st.subheader(f"Run ID: `{run_id}`")
        st.write(f"Base directory: `{persist_store.base_dir}`")

        st.markdown("---")
        st.subheader("Saved Schedules")
        schedules = list(persist_store.list_schedules())
        if not schedules:
            st.info("No schedules saved yet.")
        else:
            rows = []
            for s in schedules:
                meta = s.get("metadata", {}) or {}
                rows.append(
                    {
                        "ID": s.get("id", "?")[:16] + "…",
                        "Seq": s.get("seq", "?"),
                        "Created": s.get("created_at", "?"),
                        "Assignments": len(s.get("schedule", {})),
                        "Status": meta.get("status", "—"),
                        "Strategy": meta.get("strategy", "—"),
                        "Solve time (s)": f"{meta.get('solve_time_seconds', 0):.2f}",
                    }
                )
            st.dataframe(rows, use_container_width=True)

            st.markdown("---")
            st.subheader("Export a schedule as prev_schedule CSV")
            schedule_ids = [s.get("id", "") for s in schedules]
            selected_id = st.selectbox("Select schedule to export", schedule_ids, key="export_id")
            export_name = st.text_input("Output filename", value="prev_schedule.csv", key="export_name")
            if st.button("💾 Export", key="btn_export"):
                try:
                    out = persist_store.export_schedule_as_prev_csv(selected_id, export_name)
                    st.success(f"Exported to `{out}`")
                    with open(out, "rb") as fh:
                        st.download_button(
                            label="⬇ Download CSV",
                            data=fh.read(),
                            file_name=Path(out).name,
                            mime="text/csv",
                        )
                except Exception as exc:
                    st.error(f"Export failed: {exc}")

        st.markdown("---")
        st.subheader("Change Events")
        events = list(persist_store.iter_change_events())
        if not events:
            st.info("No change events recorded yet.")
        else:
            for ev in events:
                inner = ev.get("event", {}) or {}
                st.write(
                    f"**{ev.get('id', '?')[:12]}…** | seq={ev.get('seq')} | ts={ev.get('ts')} | "
                    f"type={inner.get('type', '—')}"
                )


def run_dev_server() -> None:
    """Launch the Streamlit app programmatically.

    This is a convenience helper for callers who want to start the app from
    Python code rather than the shell.  Call it from a *separate* entry-point
    script; do NOT call it from within this file because Streamlit executes
    the script with ``__name__ == '__main__'``, which would cause a recursive
    subprocess loop.

    Example entry-point ``run_ui.py``::

        from ui.web_app import run_dev_server
        run_dev_server()
    """
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", __file__, "--server.headless", "true"],
        check=True,
    )