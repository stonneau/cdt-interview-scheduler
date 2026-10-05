"""
Event store for logging scheduling changes (placeholder).

From checklist.md:
- Record each schedule version and reason for change.
- Store: timestamp, change_event, prev_schedule_id, new_schedule_id, metrics, user locks.
"""

from typing import Any, Dict, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EventRecord:
    """In-memory representation of a stored event (placeholder only)."""

    id: str
    timestamp: datetime
    change_event: Dict[str, Any]
    prev_schedule_id: str
    new_schedule_id: str
    metrics: Dict[str, Any] = field(default_factory=dict)


class InMemoryEventStore:
    """
    Non-persistent event store for experiments (placeholder).

    Replace with a JSON/DB-backed implementation later.
    """

    def __init__(self) -> None:
        self._events: List[EventRecord] = []

    def append(self, event: EventRecord) -> None:
        """Append a new event record."""
        self._events.append(event)

    def all_events(self) -> List[EventRecord]:
        """Return all recorded events."""
        return list(self._events)