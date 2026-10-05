"""Data models package — domain objects, persistence, and CSV loading.

Public API
----------
- :mod:`models` — dataclass definitions (Candidate, Staff, TimeSlot, etc.).
- :mod:`store` — JSON-based DataStore for persisting schedules and events.
- :mod:`loaders` — CSV loaders and model-to-solver converters.
- :mod:`utils` — staff availability alignment utilities.
"""

from data_models.models import (
    Candidate,
    Staff,
    TimeSlot,
    Availability,
    PanelRequirement,
    ForbiddenPair,
    ScheduleAssignment,
    ChangeEvent,
)
from data_models.store import DataStore

__all__ = [
    "Candidate",
    "Staff",
    "TimeSlot",
    "Availability",
    "PanelRequirement",
    "ForbiddenPair",
    "ScheduleAssignment",
    "ChangeEvent",
    "DataStore",
]
