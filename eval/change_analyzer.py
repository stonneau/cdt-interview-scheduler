"""
Compute human-readable summaries of availability changes.

Used when creating change events to capture what actually changed
(e.g., "lead1, lead2 unavailable on 2025-04-01 08:00-08:45; lead3 unavailable on 2025-04-02 09:30-10:15").
"""

from typing import Dict, List, Tuple, Any


def compute_staff_unavailable_details(
    staff_avail_before: Dict[str, Dict[str, int]],
    staff_avail_after: Dict[str, Dict[str, int]],
    max_items: int = 15,
) -> str:
    """
    Compute which staff became unavailable and on which timeslots.
    
    Parameters
    ----------
    staff_avail_before : Dict[str, Dict[str, int]]
        Staff availability before the change (staff_id -> timeslot -> 0/1)
    staff_avail_after : Dict[str, Dict[str, int]]
        Staff availability after the change
    max_items : int
        Maximum number of changes to include in summary (rest summarized as "+N more")
    
    Returns
    -------
    str
        Human-readable summary, e.g., "lead1 on 2025-04-01 08:00-08:45; lead2 on 2025-04-02 09:30-10:15; (+2 more)"
    """
    changes = []
    
    # Find staff-timeslots that changed from available to unavailable
    all_staff = set(staff_avail_before.keys()) | set(staff_avail_after.keys())
    all_slots = set()
    for s_avail in [staff_avail_before, staff_avail_after]:
        for slots in s_avail.values():
            all_slots.update(slots.keys())
    
    for staff_id in sorted(all_staff):
        before_slots = staff_avail_before.get(staff_id, {})
        after_slots = staff_avail_after.get(staff_id, {})
        
        for slot in sorted(all_slots):
            before_avail = before_slots.get(slot, 1)
            after_avail = after_slots.get(slot, 1)
            
            # Only record transitions to unavailable (1 -> 0)
            if before_avail == 1 and after_avail == 0:
                changes.append(f"{staff_id} on {slot}")
    
    if not changes:
        return ""
    
    # Format with truncation
    result = "; ".join(changes[:max_items])
    if len(changes) > max_items:
        result += f" (+{len(changes) - max_items} more)"
    
    return result


def compute_candidate_unavailable_details(
    avail_before: Dict[str, Dict[str, int]],
    avail_after: Dict[str, Dict[str, int]],
    max_items: int = 15,
) -> str:
    """
    Compute which candidates became unavailable and on which timeslots.
    
    Parameters
    ----------
    avail_before : Dict[str, Dict[str, int]]
        Candidate availability before the change (candidate_id -> timeslot -> 0/1)
    avail_after : Dict[str, Dict[str, int]]
        Candidate availability after the change
    max_items : int
        Maximum number of changes to include in summary
    
    Returns
    -------
    str
        Human-readable summary
    """
    changes = []
    
    all_cands = set(avail_before.keys()) | set(avail_after.keys())
    all_slots = set()
    for a_dict in [avail_before, avail_after]:
        for slots in a_dict.values():
            all_slots.update(slots.keys())
    
    for cand_id in sorted(all_cands):
        before_slots = avail_before.get(cand_id, {})
        after_slots = avail_after.get(cand_id, {})
        
        for slot in sorted(all_slots):
            before_avail = before_slots.get(slot, 1)
            after_avail = after_slots.get(slot, 1)
            
            # Only record transitions to unavailable (1 -> 0)
            if before_avail == 1 and after_avail == 0:
                changes.append(f"{cand_id} on {slot}")
    
    if not changes:
        return ""
    
    result = "; ".join(changes[:max_items])
    if len(changes) > max_items:
        result += f" (+{len(changes) - max_items} more)"
    
    return result


def compute_removal_details(
    removed_ids: List[str],
    removal_type: str = "candidate",
    max_items: int = 15,
) -> str:
    """
    Compute summary of removed candidates or staff.
    
    Parameters
    ----------
    removed_ids : List[str]
        List of IDs removed (candidate_ids or staff_ids)
    removal_type : str
        "candidate" or "staff"
    max_items : int
        Maximum number to include in summary
    
    Returns
    -------
    str
        Human-readable summary, e.g., "cand1, cand2, cand3 (+5 more)" or "lead1, lead2"
    """
    if not removed_ids:
        return ""
    
    result = ", ".join(str(id_) for id_ in removed_ids[:max_items])
    if len(removed_ids) > max_items:
        result += f" (+{len(removed_ids) - max_items} more)"
    
    return result
