"""Domain model dataclasses for the constraint-solver scheduling system.

Defines the core entities used throughout the application: candidates, staff
members, timeslots, availability records, panel requirements, forbidden
pairings, schedule assignments, and change events.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Candidate:
    """A candidate to be scheduled for an interview slot.

    :param id: Unique identifier for the candidate (typically their name).
    :param attrs: Arbitrary key-value attributes associated with the candidate.
    :param availability: Mapping of timeslot label to availability flag
        (1 = available, 0 = unavailable).
    """

    id: str
    attrs: Dict[str, Any] = field(default_factory=dict)
    availability: Dict[str, int] = field(default_factory=dict)

    def is_available(self, timeslot: str) -> bool:
        """Check whether the candidate is available for a given timeslot.

        :param timeslot: The timeslot label to check.
        :returns: ``True`` if the candidate is available, ``False`` otherwise.
        """
        return bool(self.availability.get(timeslot, 0))


@dataclass
class Staff:
    """A staff member who may be assigned to interview panels.

    :param id: Unique identifier for the staff member.
    :param is_lead: Whether this staff member is a panel lead.
    :param attrs: Arbitrary key-value attributes associated with the staff member.
    :param availability: Mapping of timeslot label to availability flag
        (1 = available, 0 = unavailable).
    """

    id: str
    is_lead: bool = False
    attrs: Dict[str, Any] = field(default_factory=dict)
    availability: Dict[str, int] = field(default_factory=dict)

    def can_attend(self, timeslot: str) -> bool:
        """Check whether the staff member can attend a given timeslot.

        :param timeslot: The timeslot label to check.
        :returns: ``True`` if the staff member is available, ``False`` otherwise.
        """
        return bool(self.availability.get(timeslot, 0))


@dataclass
class TimeSlot:
    """A canonical timeslot within the scheduling problem.

    :param id: Unique slot identifier (e.g. ``"2025-04-01 09:00"``).
    :param attrs: Optional attributes such as room or campus.
    """

    id: str
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Availability:
    """A record linking an entity to a timeslot with availability status.

    :param entity_id: Identifier of the entity (candidate or staff).
    :param timeslot_id: Identifier of the timeslot.
    :param is_available: Whether the entity is available in this slot.
    :param attrs: Optional metadata for the availability record.
    """

    entity_id: str
    timeslot_id: str
    is_available: bool = True
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PanelRequirement:
    """Describes which staff must attend a candidate's interview panel.

    :param candidate_id: The candidate who requires a specific panel.
    """

    candidate_id: str


@dataclass
class ForbiddenPair:
    """A forbidden candidate–staff pairing that the solver must respect.

    :param candidate_id: The candidate in the forbidden pair.
    :param staff_id: The staff member in the forbidden pair.
    """

    candidate_id: str
    staff_id: str


@dataclass
class ScheduleAssignment:
    """A single assignment within a generated schedule.

    :param candidate_id: The candidate assigned to this slot.
    :param timeslot_id: The timeslot assigned.
    :param staff_ids: List of staff member IDs on the interview panel.
    """

    candidate_id: str
    timeslot_id: str
    staff_ids: list[str] = field(default_factory=list)


@dataclass
class ChangeEvent:
    """An event representing a change to the scheduling state.

    Used by the simulation harness and event-store to track mutations such as
    staff unavailability or candidate availability changes.

    :param type: Event type identifier (e.g. ``"StaffUnavailable"``).
    :param payload: Event-specific data.
    :param source: Optional origin label for the event.
    """

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None