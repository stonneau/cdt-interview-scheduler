"""JSON-file-based persistence layer for schedules and change events.

Provides :class:`DataStore`, which persists schedule versions and change
events as individual JSON files organised under a configurable base
directory.  Each *run* gets its own subdirectory so that related artefacts
are grouped together.  The store also exposes helpers for loading initial
CSV data and exporting schedules back to CSV.
"""

from typing import Any, Dict, Iterable, Optional
import json
import uuid
import time
import os
from pathlib import Path
import csv

from data_models.loaders import (
    load_availability_objects_from_csv,
    load_staff_objects_from_csv,
    load_prev_schedule_from_csv,
)


class DataStore:
    """JSON-file-backed data store for schedules and change events.

    Artefacts are organised on disk as::

        <base_dir>/<run_id>/schedules/<schedule_id>.json
        <base_dir>/<run_id>/events/<event_id>.json

    Logical sequence counters are restored from existing files so that a
    store re-opened against a prior *run_id* continues numbering correctly.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialise the data store.

        :param config: Optional configuration dictionary.  Recognised keys:
            * ``run_id`` – explicit run identifier (auto-generated if absent).
            * ``base_dir`` – root directory for artefacts (default ``"data"``).
            * ``data_dir`` – directory containing source CSV files.
            * ``id_prefix`` – prefix for generated schedule IDs.
        """
        self.config = config or {}
        self.run_id = str(self.config.get("run_id") or f"run-{uuid.uuid4().hex}")
        base_dir_root = Path(self.config.get("base_dir", "data"))
        self.base_dir = base_dir_root / self.run_id
        self.schedules_dir = self.base_dir / "schedules"
        self.events_dir = self.base_dir / "events"
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)

        self._schedule_seq = self._max_seq_in_dir(self.schedules_dir)
        self._event_seq = self._max_seq_in_dir(self.events_dir)

    @staticmethod
    def _max_seq_in_dir(directory: Path) -> int:
        """Return the highest ``seq`` value found in JSON files under *directory*.

        :param directory: Path to scan for JSON files.
        :returns: The maximum sequence number found, or ``0`` if the directory
            is empty or no file contains a ``seq`` field.
        """
        max_seq = 0
        if not directory.exists():
            return max_seq
        for p in directory.iterdir():
            if p.is_file() and p.suffix == ".json":
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    seq = int(payload.get("seq", 0))
                    if seq > max_seq:
                        max_seq = seq
                except (OSError, json.JSONDecodeError, ValueError, TypeError):
                    continue
        return max_seq

    def load_initial_data(self) -> Dict[str, Any]:
        """Load canonical entities from standard CSV files.

        Attempts to load staff, candidate, and previous-schedule CSVs from
        the configured ``data_dir``.  Missing files are silently ignored and
        the corresponding key is set to ``None``.

        :returns: Dictionary with keys ``"staff"``, ``"candidates"``, and
            ``"prev_schedule"``.  Each value is either a tuple of loaded
            objects or ``None`` if the file was not found.
        """
        data_dir = self.config.get("data_dir", str(self.base_dir))
        result: Dict[str, Any] = {}
        try:
            staff_objs, staff_slots = load_staff_objects_from_csv(os.path.join(data_dir, "staff_aligned_45min.csv"))
            result["staff"] = (staff_objs, staff_slots)
        except Exception:
            result["staff"] = None

        try:
            candidates, cand_slots = load_availability_objects_from_csv(os.path.join(data_dir, "applicants_availabilities.csv"))
            result["candidates"] = (candidates, cand_slots)
        except Exception:
            result["candidates"] = None

        try:
            prev = load_prev_schedule_from_csv(os.path.join(data_dir, "prev_schedule.csv"))
            result["prev_schedule"] = prev
        except Exception:
            result["prev_schedule"] = None

        return result

    def save_schedule(self, schedule: Dict[str, str], metadata: Optional[Dict[str, Any]] = None) -> str:
        """Persist a schedule version and return its unique ID.

        :param schedule: Mapping of ``candidate_id`` → ``timeslot_id``.
        :param metadata: Optional dictionary of additional metadata to store
            alongside the schedule.
        :returns: The generated schedule ID string.
        """
        self._schedule_seq += 1
        sid = self.config.get("id_prefix", "sch-") + uuid.uuid4().hex
        ts = int(time.time())
        payload = {
            "id": sid,
            "run_id": self.run_id,
            "seq": self._schedule_seq,
            "created_at": ts,
            "schedule": schedule,
            "metadata": metadata or {},
        }
        path = self.schedules_dir / f"{sid}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return sid

    def get_schedule(self, schedule_id: str) -> Dict[str, str]:
        """Retrieve the candidate-to-timeslot mapping for a saved schedule.

        :param schedule_id: The unique schedule identifier.
        :returns: Dictionary mapping ``candidate_id`` → ``timeslot_id``.
        :raises FileNotFoundError: If no schedule with the given ID exists.
        """
        path = self.schedules_dir / f"{schedule_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Schedule {schedule_id!r} not found")
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("schedule", {})

    def iter_change_events(self) -> Iterable[Dict[str, Any]]:
        """Yield stored change-event payloads in filename-sorted order.

        :returns: An iterable of parsed JSON event dictionaries.
        """
        for p in sorted(self.events_dir.iterdir()):
            if p.is_file() and p.suffix == ".json":
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        yield json.load(fh)
                except Exception:
                    continue

    def append_event(self, event: Dict[str, Any]) -> str:
        """Persist a change event and return its unique ID.

        :param event: Arbitrary event dictionary to store.
        :returns: The generated event ID string.
        """
        self._event_seq += 1
        eid = "evt-" + uuid.uuid4().hex
        event_payload = {
            "id": eid,
            "run_id": self.run_id,
            "seq": self._event_seq,
            "ts": int(time.time()),
            "event": event
            }
        path = self.events_dir / f"{eid}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(event_payload, fh, indent=2)
        return eid

    def list_schedules(self) -> Iterable[Dict[str, Any]]:
        """Yield full JSON payloads for all saved schedules, oldest first.

        :returns: An iterable of parsed schedule payload dictionaries as
            saved by :meth:`save_schedule`.
        """
        for p in sorted(self.schedules_dir.iterdir()):
            if p.is_file() and p.suffix == ".json":
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        yield json.load(fh)
                except Exception:
                    continue

    def get_schedule_metadata(self, schedule_id: str) -> Dict[str, Any]:
        """Return the full persisted payload for a given schedule ID.

        :param schedule_id: The unique schedule identifier.
        :returns: The complete JSON payload including ``id``, ``created_at``,
            ``schedule``, and ``metadata``.
        :raises FileNotFoundError: If no schedule with the given ID exists.
        """
        path = self.schedules_dir / f"{schedule_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Schedule {schedule_id!r} not found")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def update_schedule_metadata(self, schedule_id: str, metadata_updates: Dict[str, Any]) -> None:
        """Merge updates into the metadata of an existing saved schedule.

        :param schedule_id: The unique schedule identifier.
        :param metadata_updates: Key-value pairs to merge into the existing
            metadata dictionary.
        :raises FileNotFoundError: If no schedule with the given ID exists.
        """
        path = self.schedules_dir / f"{schedule_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Schedule {schedule_id!r} not found")
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload_metadata = payload.get("metadata") or {}
        payload_metadata.update(metadata_updates or {})
        payload["metadata"] = payload_metadata
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    def export_schedule_as_prev_csv(self, schedule_id: str, out_path: str) -> str:
        """Export a saved schedule as a ``prev_schedule`` CSV.

        The CSV follows the schema expected by
        :func:`~data_models.loaders.load_prev_schedule_from_csv`::

            candidate_id,timeslot_id,staff_ids

        :param schedule_id: The unique schedule identifier to export.
        :param out_path: Filesystem path for the output CSV file.
        :returns: The resolved path to the written CSV file.
        :raises ValueError: If the schedule's metadata does not contain a
            ``staff_assignment`` mapping.
        :raises FileNotFoundError: If no schedule with the given ID exists.
        """
        payload = self.get_schedule_metadata(schedule_id)
        schedule = payload.get("schedule", {})
        metadata = payload.get("metadata", {}) or {}
        staff_assignment = metadata.get("staff_assignment")

        if not staff_assignment:
            raise ValueError(
                "Saved schedule does not contain 'staff_assignment' in metadata; cannot export prev_schedule.csv"
            )

        out_path_p = Path(out_path)
        if out_path_p.parent:
            out_path_p.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path_p, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["candidate_id", "timeslot_id", "staff_ids"])
            for cand in sorted(schedule.keys()):
                slot = schedule.get(cand, "")
                staff_list = staff_assignment.get(slot, []) or []
                staff_str = ";".join(staff_list)
                writer.writerow([cand, slot, staff_str])

        return str(out_path_p)