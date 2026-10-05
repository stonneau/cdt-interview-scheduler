"""
Synthetic dataset generators for experimentation.

Generates candidates, staff, timeslots, and availability matrices with
configurable sizes and complexity levels.
"""

from typing import Dict, List, Tuple, Set
import random
from datetime import datetime, timedelta


def generate_time_slots(num_days: int, slots_per_day: int, start_date: str = "2025-04-01", slot_duration_min: int = 45) -> List[str]:
    """
    Generate a list of timeslot strings like "2025-04-01 08:00-08:45".
    
    Parameters
    ----------
    num_days : int
        Number of consecutive days.
    slots_per_day : int
        Number of slots per day.
    start_date : str
        Starting date in YYYY-MM-DD format.
    slot_duration_min : int
        Duration of each slot in minutes.
    
    Returns
    -------
    List[str]
        Sorted list of timeslot strings.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    slots = []
    
    for day_offset in range(num_days):
        current_date = start + timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Generate slots starting at 08:00
        current_time = datetime.strptime("08:00", "%H:%M")
        for slot_idx in range(slots_per_day):
            start_time_str = current_time.strftime("%H:%M")
            end_time = current_time + timedelta(minutes=slot_duration_min)
            end_time_str = end_time.strftime("%H:%M")
            slot_str = f"{date_str} {start_time_str}-{end_time_str}"
            slots.append(slot_str)
            current_time = end_time
    
    return sorted(slots)


def generate_candidates(num_candidates: int) -> List[str]:
    """Generate candidate IDs like cand1, cand2, ..."""
    return [f"cand{i+1}" for i in range(num_candidates)]


def generate_staff(num_staff: int, num_leads: int = 3) -> List[str]:
    """
    Generate staff IDs with lead/panel roles.
    
    Parameters
    ----------
    num_staff : int
        Total number of staff.
    num_leads : int
        Number of lead staff (named lead1, lead2, ...).
    
    Returns
    -------
    List[str]
        Staff IDs: [lead1, lead2, ..., panel1, panel2, ...].
    """
    leads = [f"lead{i+1}" for i in range(num_leads)]
    panel_count = max(0, num_staff - num_leads)
    panel = [f"panel{i+1}" for i in range(panel_count)]
    return leads + panel


def generate_availability_matrix(
    ids: List[str],
    time_slots: List[str],
    complexity: str = "simple",
    unavail_prob: float = 0.1,
    seed: int = None,
) -> Dict[str, Dict[str, int]]:
    """
    Generate availability matrix (0/1) for candidates or staff.
    
    Parameters
    ----------
    ids : List[str]
        Candidate or staff IDs.
    time_slots : List[str]
        List of timeslot strings.
    complexity : str
        "simple": everyone available (unavail_prob small)
        "medium": moderate unavailability
        "complex": clustered unavailability, temporal patterns
    unavail_prob : float
        Base probability of unavailability (0-1).
    seed : int, optional
        Random seed for reproducibility.
    
    Returns
    -------
    Dict[str, Dict[str, int]]
        Nested dict {person: {timeslot: 0/1}}.
    """
    if seed is not None:
        random.seed(seed)
    
    # Complexity determines unavailability level
    if complexity == "simple":
        unavail_prob = 0.05
    elif complexity == "medium":
        unavail_prob = 0.15
    elif complexity == "complex":
        unavail_prob = 0.30
    
    avail = {}
    for person in ids:
        avail[person] = {}
        for slot in time_slots:
            if complexity == "complex":
                # Clustered unavailability: use deterministic seeding per person+slot
                # to create correlated patterns (same person likely unavailable multiple times)
                slot_parts = slot.split()  # ["2025-04-01", "08:00-08:45"]
                date = slot_parts[0]
                time_range = slot_parts[1]
                
                # Seed a local RNG per person+date for correlation
                # (person is unavailable on a "bad day" -> multiple slots on same day)
                person_day_seed = hash((person, date, seed or 0)) & 0x7fffffff
                person_rng = random.Random(person_day_seed)
                
                # If this person has a bad day, they're likely unavailable all day
                is_bad_day = person_rng.random() < (unavail_prob * 0.5)
                if is_bad_day:
                    is_unavail = person_rng.random() < 0.7  # 70% of slots on bad day
                else:
                    is_unavail = random.random() < unavail_prob
            else:
                is_unavail = random.random() < unavail_prob
            
            avail[person][slot] = 0 if is_unavail else 1
    
    return avail


def generate_required_staff(
    candidates: List[str],
    staff: List[str],
    leads_only: bool = True,
    seed: int = None,
) -> Dict[str, List[str]]:
    """
    Generate required staff mapping for candidates.
    
    Parameters
    ----------
    candidates : List[str]
        Candidate IDs.
    staff : List[str]
        Staff IDs (typically with lead1, lead2, ... first).
    leads_only : bool
        If True, all candidates require a lead.
        If False, some candidates may only require panel staff.
    seed : int, optional
        Random seed.
    
    Returns
    -------
    Dict[str, List[str]]
        {candidate: [required_staff_ids]}.
    """
    if seed is not None:
        random.seed(seed)
    
    required = {}
    
    # Extract leads from staff list (assume they're named leadN)
    leads = [s for s in staff if s.startswith("lead")]
    
    for cand in candidates:
        if leads_only and leads:
            # All candidates require at least one lead
            required[cand] = [random.choice(leads)]
        else:
            # Some candidates just need any staff member
            if random.random() < 0.3:  # 30% need a lead
                required[cand] = [random.choice(leads)] if leads else []
            else:
                required[cand] = []
    
    return required


def generate_forbidden_pairs(
    candidates: List[str],
    staff: List[str],
    num_pairs: int = 0,
    seed: int = None,
) -> Set[Tuple[str, str]]:
    """
    Generate a set of (candidate, staff) forbidden pairs.
    
    Parameters
    ----------
    candidates : List[str]
        Candidate IDs.
    staff : List[str]
        Staff IDs.
    num_pairs : int
        Number of forbidden pairs to generate (0 for none).
    seed : int, optional
        Random seed.
    
    Returns
    -------
    Set[Tuple[str, str]]
        Set of (candidate, staff) tuples.
    """
    if seed is not None:
        random.seed(seed)
    
    forbidden = set()
    max_pairs = min(num_pairs, len(candidates) * len(staff) // 10)
    
    for _ in range(max_pairs):
        c = random.choice(candidates)
        s = random.choice(staff)
        forbidden.add((c, s))
    
    return forbidden


def generate_synthetic_dataset(
    num_candidates: int = 10,
    num_staff: int = 6,
    num_days: int = 3,
    slots_per_day: int = 4,
    complexity: str = "simple",
    num_leads: int = 3,
    require_leads: bool = False,
    seed: int = None,
) -> Dict:
    """
    Generate a complete synthetic scheduling dataset.
    
    Parameters
    ----------
    num_candidates : int
        Number of candidates.
    num_staff : int
        Total number of staff members.
    num_days : int
        Number of days in the schedule.
    slots_per_day : int
        Number of timeslots per day.
    complexity : str
        "simple", "medium", or "complex" (affects availability patterns).
    num_leads : int
        Number of lead staff (required for each candidate).
    seed : int, optional
        Random seed for reproducibility.
    
    Returns
    -------
    Dict
        Dictionary with keys:
        - candidates: List[str]
        - staff: List[str]
        - time_slots: List[str]
        - avail: Dict[candidate][timeslot] -> 0/1
        - staff_avail: Dict[staff][timeslot] -> 0/1
        - required_staff: Dict[candidate] -> [staff_ids]
        - forbidden_pairs: Set[(candidate, staff)]
    """
    if seed is not None:
        random.seed(seed)
    
    # Generate basic components
    candidates = generate_candidates(num_candidates)
    staff = generate_staff(num_staff, num_leads=num_leads)
    time_slots = generate_time_slots(num_days, slots_per_day)
    
    # Generate availability
    avail = generate_availability_matrix(candidates, time_slots, complexity=complexity, seed=seed)
    staff_avail = generate_availability_matrix(staff, time_slots, complexity=complexity, unavail_prob=0.05, seed=seed)
    
    # Generate constraints
    # Use explicit require_leads flag so callers can control whether each
    # candidate requires a lead, independent of the availability complexity.
    required_staff = generate_required_staff(candidates, staff, leads_only=require_leads, seed=seed)
    forbidden_pairs = generate_forbidden_pairs(candidates, staff, num_pairs=0, seed=seed)
    
    return {
        "candidates": candidates,
        "staff": staff,
        "time_slots": time_slots,
        "avail": avail,
        "staff_avail": staff_avail,
        "required_staff": required_staff,
        "forbidden_pairs": forbidden_pairs,
    }
