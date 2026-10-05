"""Browser-facing API of the scheduler.

Runs unchanged under CPython (it is unit-tested there) and under Pyodide, where
the web page calls :func:`dispatch` through a Web Worker.  Everything is
JSON-in / JSON-out and the CSV files arrive as *text* read by the browser, so
no applicant data ever leaves the user's machine.

The solver backend is always the pure-Python MIP backend (HiGHS via scipy),
because OR-Tools has no WebAssembly build.
"""

import copy
import json
import re
from typing import Any, Dict, List, Optional

from data_models.csv_text import (
    YES_AND_IF_NEEDED,
    YES_ONLY,
    parse_availability_text,
    parse_forbidden_pairs_text,
    parse_staff_text,
)
from data_models.loaders import (
    objects_to_solver_inputs_from_models,
    parse_forbidden_pairs_inline,
    unify_slots,
)
from scheduler.solver import reschedule, solve_initial_schedule
from webapi.example import make_example

OK_STATUSES = ("OPTIMAL", "FEASIBLE")


class _State:
    """The single working session (one user per browser tab)."""

    def __init__(self):
        self.ds: Optional[Dict[str, Any]] = None
        self.last: Optional[Dict[str, Any]] = None  # last successful result payload
        self.if_needed_mode = "unavailable"
        self.if_needed_cells = 0


STATE = _State()


# ------------------------------------------------------------------ helpers

def _base(slot: str) -> str:
    """Strip a parallel-room suffix (``"<slot>.2"`` -> ``"<slot>"``)."""
    return re.sub(r"\.\d+$", "", slot)


def _room(slot: str) -> int:
    m = re.search(r"\.(\d+)$", slot)
    return int(m.group(1)) if m else 1


def _date_time(slot: str):
    base = _base(slot)
    return tuple(base.split(" ", 1)) if " " in base else ("", base)


def _pretty_time(time: str) -> str:
    """Display/sort time of a slot.  Doodle polls write afternoon hours as 1-7 (for
    13:00-19:00), which the loader keeps as ``01:00``..; interviews do not start
    before 8am, so hours 1-7 are shown as afternoon (the slot id itself is unchanged)."""
    m = re.match(r"^(\d{1,2}):(\d{2})(.*)$", time)
    if m and 1 <= int(m.group(1)) <= 7:
        return f"{int(m.group(1)) + 12:02d}:{m.group(2)}{m.group(3)}"
    return time


def _label(slot: str) -> str:
    """Readable slot name: ``2026-03-12 16:45`` (plus ``room 2`` for parallel rooms)."""
    d, t = _date_time(slot)
    room = _room(slot)
    return f"{d} {_pretty_time(t)}".strip() + (f" (room {room})" if room > 1 else "")


def _count_if_needed(text: str) -> int:
    """Number of "If needed" answers in an availability export."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))[2:]
    extra = YES_AND_IF_NEEDED - YES_ONLY
    return sum(1 for r in rows for c in r[1:] if c.strip().lower() in extra)


def _dedupe(people, label, policy, warnings):
    """Poll exports list a person twice when they answered twice.  Keep one row per
    name: the last (default), the first, or only the slots where both rows say yes."""
    groups: Dict[str, list] = {}
    for p in people:
        groups.setdefault(p.id, []).append(p)
    if all(len(g) == 1 for g in groups.values()):
        return people
    out, names = [], []
    for name, rows in groups.items():
        if len(rows) == 1:
            out.append(rows[0])
            continue
        chosen = rows[-1] if policy == "last" else rows[0]
        differ = any(r.availability != rows[0].availability for r in rows[1:])
        if policy == "both":
            chosen = rows[0]
            chosen.availability = {t: int(all(r.availability.get(t, 0) == 1 for r in rows))
                                   for t in rows[0].availability}
        names.append(f"{name}{'' if differ else ' (identical answers)'}")
        out.append(chosen)
    how = {"last": "the last row is used", "first": "the first row is used",
           "both": "a slot counts only if every row says yes"}.get(policy, "the last row is used")
    warnings.append(f"Listed more than once in the {label} file — {how}: " + ", ".join(names))
    return out


def _need_session():
    if STATE.ds is None:
        raise ValueError("No data loaded yet: load the applicants and staff CSV files first.")


def _params(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "min_staff_per_slot": int(p.get("min_staff", 2)),
        "max_staff_per_slot": int(p.get("max_staff", p.get("min_staff", 2))),
        "fairness": p.get("fairness", "balanced"),
        "time_limit": float(p.get("time_limit", 30)),
        "allow_parallel": bool(p.get("allow_parallel", False)),
        "max_parallel": int(p.get("max_parallel", 2)),
        "backend": "mip",
        "persist": False,
        "random_seed": 0,
    }
    if out["max_staff_per_slot"] < out["min_staff_per_slot"]:
        raise ValueError("Maximum panel size cannot be smaller than the minimum.")
    if out["fairness"] not in ("balanced", "min_dev", "min_max", "none"):
        raise ValueError(f"Unknown fairness objective {out['fairness']!r}.")
    return out


def _info(ds: Dict[str, Any]) -> Dict[str, Any]:
    leads = set(ds.get("lead_ids") or [])
    slots = list(ds["time_slots"])
    return {
        "candidates": list(ds["candidates"]),
        "staff": [{"id": s, "lead": s in leads} for s in ds["staff"]],
        "slots": slots,
        "slot_labels": [_label(t) for t in slots],
        "dates": sorted({_date_time(t)[0] for t in slots}),
        "leads": sorted(leads),
        "n_forbidden": len(ds["forbidden_pairs"]),
    }


# ------------------------------------------------------------------ loading

def load(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the CSV texts and open a new session."""
    accept = YES_AND_IF_NEEDED if payload.get("if_needed") == "available" else YES_ONLY
    STATE.if_needed_mode = "available" if accept is YES_AND_IF_NEEDED else "unavailable"
    STATE.if_needed_cells = _count_if_needed(payload["applicants"]) + _count_if_needed(payload["staff"])
    cands, slots_a = parse_availability_text(payload["applicants"], accept=accept)
    staff, slots_s = parse_staff_text(payload["staff"], accept=accept)
    warnings: List[str] = []
    for label, slots in (("applicants", slots_a), ("staff", slots_s)):
        bad = [t for t in slots if not re.match(r"^\d{4}-\d{2}-\d{2}", t)]
        if not slots or bad:
            raise ValueError(
                f"The {label} file does not look like an availability export: the first row should hold "
                "dates (like 2026-03-11) and the second row the slot times.")
    policy = payload.get("duplicates", "last")
    cands = _dedupe(cands, "applicants", policy, warnings)
    staff = _dedupe(staff, "staff", policy, warnings)
    if not cands:
        raise ValueError("The applicants file contains no applicant rows.")
    if not staff:
        raise ValueError("The staff file contains no staff rows.")

    # Doodle exports sometimes put "2026-04-01 ..." in the date row of the applicants file:
    # re-key by the first date token so both files use the same slot labels.
    if set(slots_a) != set(slots_s):
        fixed = {s: f"{s.split()[0]} {s.rsplit(' ', 1)[-1]}" for s in slots_a}
        if set(fixed.values()) == set(slots_s):
            for c in cands:
                c.availability = {fixed[k]: v for k, v in c.availability.items()}
            slots_a = [fixed[s] for s in slots_a]
            warnings.append("Applicant date labels were normalised to match the staff file.")
        else:
            only_a, only_s = set(slots_a) - set(slots_s), set(slots_s) - set(slots_a)
            warnings.append(
                f"The two files do not list the same time slots ({len(only_a)} only in applicants, "
                f"{len(only_s)} only in staff). Missing availability counts as unavailable.")

    forbidden = set()
    if (payload.get("forbidden") or "").strip():
        forbidden |= parse_forbidden_pairs_text(payload["forbidden"])
    if (payload.get("forbidden_inline") or "").strip():
        forbidden |= parse_forbidden_pairs_inline(payload["forbidden_inline"])

    raw = (payload.get("lead_ids") or "").strip()
    if raw.lower() == "none":
        lead_ids: Optional[List[str]] = []
    elif raw:
        lead_ids = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        lead_ids = None  # auto-detect: staff ids starting with "lead"

    cids, sids, avail, savail, required, fp = objects_to_solver_inputs_from_models(
        cands, staff, lead_ids=lead_ids, forbidden_pairs=forbidden)
    if len(set(cids)) != len(cids):
        raise ValueError("Applicant names must be unique.")
    if len(set(sids)) != len(sids):
        raise ValueError("Staff names must be unique.")
    leads = sorted({l for v in required.values() for l in v})
    never = [c.id for c in cands if not any(v == 1 for v in c.availability.values())]
    if never:
        warnings.append("No availability at all (will make the problem infeasible): " + ", ".join(never[:8])
                        + ("…" if len(never) > 8 else ""))
    if lead_ids and set(lead_ids) - set(sids):
        warnings.append("Unknown lead id(s) ignored: " + ", ".join(sorted(set(lead_ids) - set(sids))))
    if not leads:
        warnings.append("No lead staff: panels have no lead requirement "
                        "(name leads 'lead…' in the staff file or list them in the Lead IDs box).")
    unknown = sorted({c for c, _ in fp if c not in set(cids)} | {s for _, s in fp if s not in set(sids)})
    if unknown:
        warnings.append("Forbidden pairs mention names not in the files (kept, they apply if the "
                        "person is added later): " + ", ".join(unknown[:8]) + ("…" if len(unknown) > 8 else ""))

    STATE.ds = {
        "candidates": cids, "time_slots": sorted(unify_slots(slots_a, slots_s)),
        "avail": avail, "staff": sids, "staff_avail": savail,
        "required_staff": required, "forbidden_pairs": fp,
        "prev_schedule": {}, "prev_staff_assignment": None, "lead_ids": leads,
    }
    STATE.last = None
    if STATE.if_needed_cells:
        warnings.append(f"{STATE.if_needed_cells} “If needed” answers are being counted as "
                        f"{'available' if STATE.if_needed_mode == 'available' else 'unavailable'} "
                        "(change this with the “If needed” setting).")
    return {"info": _info(STATE.ds), "warnings": warnings}


def load_example(payload: Dict[str, Any]) -> Dict[str, Any]:
    texts = make_example(int(payload.get("seed", 7)))
    return load({"applicants": texts["applicants"], "staff": texts["staff"],
                 "forbidden": texts["forbidden"], "lead_ids": ""})


def set_leads(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Choose which staff are leads (every panel then gets at least one of them)."""
    _need_session()
    ids = [x for x in payload.get("lead_ids", []) if x in STATE.ds["staff"]]
    STATE.ds["lead_ids"] = sorted(ids)
    STATE.ds["required_staff"] = {c: list(ids) for c in STATE.ds["candidates"]} if ids else {}
    STATE.ds["prev_schedule"], STATE.ds["prev_staff_assignment"] = {}, None
    STATE.last = None
    return {"info": _info(STATE.ds)}


# -------------------------------------------------------------- diagnostics

def diagnose(ds: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Explain why a problem is infeasible: applicants with (almost) no usable slot."""
    leads = set(ds.get("lead_ids") or [])
    mn = params["min_staff_per_slot"]
    usable = []
    for t in ds["time_slots"]:
        avail_staff = [s for s in ds["staff"] if ds["staff_avail"].get(s, {}).get(t, 0) == 1]
        ok = len(avail_staff) >= mn and (not leads or any(s in leads for s in avail_staff))
        if ok:
            usable.append(t)
    usable_set = set(usable)
    no_slot, tight = [], []
    for c in ds["candidates"]:
        mine = [t for t in usable if ds["avail"].get(c, {}).get(t, 0) == 1]
        n_avail = sum(1 for v in ds["avail"].get(c, {}).values() if v == 1)
        if not mine:
            no_slot.append({"candidate": c, "available_slots": n_avail,
                            "reason": "no slot where this applicant is free and a valid panel "
                                      f"(at least {mn} staff{', including a lead' if leads else ''}) is free"})
        elif len(mine) <= 2:
            tight.append({"candidate": c, "usable_slots": len(mine)})
    rooms = params["max_parallel"] if params["allow_parallel"] else 1
    return {"no_slot": no_slot, "tight": tight,
            "slots_with_valid_panel": len(usable_set), "capacity": len(usable_set) * rooms,
            "n_candidates": len(ds["candidates"])}


# ------------------------------------------------------------------ results

def _result(ds, schedule, meta, params, prev=None) -> Dict[str, Any]:
    status = meta.get("status")
    ok = status in OK_STATUSES and bool(schedule) and all(t is not None for t in schedule.values())
    out: Dict[str, Any] = {
        "status": status, "ok": ok, "objective": meta.get("objective_value"),
        "solve_seconds": round(float(meta.get("solve_time_seconds") or 0), 2),
    }
    if not ok:
        out["diagnostics"] = diagnose(ds, params)
        if STATE.if_needed_mode == "unavailable" and STATE.if_needed_cells:
            out["diagnostics"]["hint_if_needed"] = STATE.if_needed_cells
        return out

    leads = set(ds.get("lead_ids") or [])
    panels = {t: list(p) for t, p in (meta.get("staff_assignment") or {}).items()}
    prev_sched = (prev or {}).get("schedule") or {}
    prev_panels = (prev or {}).get("panels") or {}

    rows = []
    for c, t in schedule.items():
        date, time = _date_time(t)
        time = _pretty_time(time)
        panel = sorted(panels.get(t, []), key=lambda s: (s not in leads, s))
        change = None
        if prev is not None:
            if c not in prev_sched:
                change = "new"
            elif prev_sched[c] != t:
                change = "moved"
            elif set(prev_panels.get(t, [])) != set(panel):
                change = "panel"
        rows.append({"candidate": c, "slot": t, "date": date, "time": time, "room": _room(t),
                     "panel": panel, "change": change,
                     "was": _label(prev_sched[c]) if change == "moved" else None})
    rows.sort(key=lambda r: (r["date"], r["time"], r["room"]))

    load = {s: 0 for s in ds["staff"]}
    for t, p in panels.items():
        for s in p:
            if s in load:
                load[s] += 1
    vals = list(load.values()) or [0]
    mean = sum(vals) / len(vals)
    out.update({
        "rows": rows,
        "staff_load": [{"staff": s, "lead": s in leads, "interviews": n} for s, n in load.items()],
        "load_stats": {"max": max(vals), "min": min(vals), "mean": round(mean, 2),
                       "variance": round(sum((v - mean) ** 2 for v in vals) / len(vals), 2)},
        "schedule": dict(schedule), "panels": panels,
    })
    if prev is not None:
        counts = {k: sum(1 for r in rows if r["change"] == k) for k in ("moved", "panel", "new")}
        counts["removed"] = len([c for c in prev_sched if c not in schedule])
        out["changes"] = counts
    return out


def _public(result: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in result.items() if k not in ("schedule", "panels")}


# --------------------------------------------------------------------- solve

def solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the initial schedule."""
    _need_session()
    params = _params(payload.get("params", {}))
    ds = copy.deepcopy(STATE.ds)
    ds["prev_schedule"], ds["prev_staff_assignment"] = {}, None
    schedule, meta = solve_initial_schedule(data_store=ds, params=dict(params))
    result = _result(STATE.ds, schedule, meta, params)
    if result["ok"]:
        STATE.ds["prev_schedule"] = dict(schedule)
        STATE.ds["prev_staff_assignment"] = meta["staff_assignment"]
        STATE.last = result
    return {"result": _public(result), "info": _info(STATE.ds)}


def _expand(ds, items, key, what):
    """Expand ``[(person, date)]`` entries into ``(person, slot)`` pairs."""
    pairs = []
    for person, date in items:
        slots = [t for t in ds["time_slots"] if _date_time(t)[0] == date]
        if not slots:
            raise ValueError(f"No slot on {date!r} for {what} {person!r}.")
        pairs += [(person, t) for t in slots]
    return pairs


def _apply_event(ds: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Make the session data reflect an event the solver accepted."""
    for s, t in event.get("staff_unavailable", []):
        ds["staff_avail"].setdefault(s, {})[t] = 0
    for c, t in event.get("candidate_unavailable", []):
        ds["avail"].setdefault(c, {})[t] = 0
    for c in event.get("remove_candidate", []):
        if c in ds["candidates"]:
            ds["candidates"].remove(c)
        ds["avail"].pop(c, None)
        ds["required_staff"].pop(c, None)
    for c in event.get("add_candidate", []):
        if c not in ds["candidates"]:
            ds["candidates"].append(c)
        if ds.get("lead_ids"):
            ds["required_staff"][c] = list(ds["lead_ids"])
    for s in event.get("staff_removed", []):
        if s in ds["staff"]:
            ds["staff"].remove(s)
        ds["staff_avail"].pop(s, None)
        ds["required_staff"] = {k: [x for x in (v or []) if x != s] for k, v in ds["required_staff"].items()}
        if s in (ds.get("lead_ids") or []):
            ds["lead_ids"] = [x for x in ds["lead_ids"] if x != s]
    for s in event.get("staff_added", []):
        if s not in ds["staff"]:
            ds["staff"].append(s)


def reschedule_(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply staged changes and reschedule with minimal disruption."""
    _need_session()
    if STATE.last is None:
        raise ValueError("Solve the initial schedule first.")
    params = _params(payload.get("params", {}))
    params["strategy"] = payload.get("strategy", "local_repair")
    ch = payload.get("changes", {})
    work = copy.deepcopy(STATE.ds)
    event: Dict[str, Any] = {}

    su = [tuple(x) for x in ch.get("staff_unavailable", [])] + \
        _expand(work, ch.get("staff_unavailable_dates", []), "staff", "staff")
    cu = [tuple(x) for x in ch.get("candidate_unavailable", [])] + \
        _expand(work, ch.get("candidate_unavailable_dates", []), "candidate", "applicant")
    for s, _ in su:
        if s not in work["staff"]:
            raise ValueError(f"Unknown staff member {s!r}.")
    for c, _ in cu:
        if c not in work["candidates"]:
            raise ValueError(f"Unknown applicant {c!r}.")
    if su:
        event["staff_unavailable"] = su
    if cu:
        event["candidate_unavailable"] = cu
    rc = list(ch.get("remove_candidate", []))
    for c in rc:
        if c not in work["candidates"]:
            raise ValueError(f"Unknown applicant {c!r}.")
    if rc:
        event["remove_candidate"] = rc
    sr = list(ch.get("staff_removed", []))
    for s in sr:
        if s not in work["staff"]:
            raise ValueError(f"Unknown staff member {s!r}.")
    if sr:
        event["staff_removed"] = sr

    def new_person(spec, existing, kind):
        pid = (spec.get("id") or "").strip()
        if not pid:
            raise ValueError(f"A new {kind} needs a name.")
        if pid in existing:
            raise ValueError(f"{pid!r} already exists.")
        slots = spec.get("slots")
        return pid, {t: (1 if (slots is None or t in set(slots)) else 0) for t in work["time_slots"]}

    for spec in ch.get("add_candidate", []):
        pid, av = new_person(spec, work["candidates"], "applicant")
        work["avail"][pid] = av
        event.setdefault("add_candidate", []).append(pid)
    for spec in ch.get("staff_added", []):
        pid, av = new_person(spec, work["staff"], "staff member")
        work["staff_avail"][pid] = av
        event.setdefault("staff_added", []).append(pid)
    if not event:
        raise ValueError("No change staged.")

    freeze = payload.get("freeze_date")
    if freeze:
        base = {t for t in work["time_slots"] if _date_time(t)[0] <= freeze}
        frozen = set(base)
        if params["allow_parallel"]:  # rooms of a frozen slot are frozen too
            frozen |= {f"{t}.{i}" for t in base for i in range(2, params["max_parallel"] + 1)}
        params["frozen_slots"] = frozen

    schedule, meta = reschedule(data_store=work, change_event=event, params=dict(params))
    after = _after(work, event)   # the session data as it would be once the event is accepted
    result = _result(after, schedule, meta, params, prev=STATE.last)
    if result["ok"]:
        after["prev_schedule"] = dict(schedule)
        after["prev_staff_assignment"] = meta["staff_assignment"]
        STATE.ds = after
        STATE.last = result
    return {"result": _public(result), "info": _info(STATE.ds)}


def _after(ds, event):
    """A copy of *ds* with *event* applied (used for diagnostics of a failed solve)."""
    tmp = copy.deepcopy(ds)
    _apply_event(tmp, event)
    return tmp


# ------------------------------------------------------------------- export

def export(payload: Dict[str, Any]) -> Dict[str, Any]:
    """CSV text of the current schedule: ``table`` (readable) or ``prev`` (re-importable)."""
    if STATE.last is None:
        raise ValueError("Nothing to export yet.")
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if payload.get("kind") == "prev":
        w.writerow(["candidate_id", "timeslot_id", "staff_ids"])
        for r in sorted(STATE.last["rows"], key=lambda r: r["candidate"]):
            w.writerow([r["candidate"], r["slot"], ";".join(r["panel"])])
    else:
        w.writerow(["candidate", "date", "time", "room", "panel"])
        for r in STATE.last["rows"]:
            w.writerow([r["candidate"], r["date"], r["time"], r["room"], " + ".join(r["panel"])])
    return {"csv": buf.getvalue()}


# ----------------------------------------------------------------- dispatch

_METHODS = {
    "load": load, "load_example": load_example, "set_leads": set_leads, "solve": solve,
    "reschedule": reschedule_, "export": export,
}


def dispatch(method: str, payload_json: str = "{}") -> str:
    """Entry point used by the Web Worker: JSON string in, JSON string out."""
    try:
        data = _METHODS[method](json.loads(payload_json or "{}"))
        return json.dumps({"ok": True, "data": data})
    except Exception as exc:  # shown to the user, never a stack trace
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)})
