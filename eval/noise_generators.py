"""
Noise generation system for creating perturbations in scheduling problems.

Supports multiple noise types (staff unavailability, candidate changes, etc.)
with configurable intensity levels for robustness testing.

Intensity meanings:
- staff_unavailable: number of slots each staff member becomes unavailable
- candidate_unavailable: number of slots each candidate becomes unavailable
- candidate_removal: number of candidates to remove (as a percentage if 0 < x < 1, else absolute count)
- candidate_addition: number of new candidates to add
- staff_removal: number of staff to remove
"""

from typing import Dict, List, Tuple, Any, Optional, Set
import random
import copy


class NoiseGenerator:
    """Base class for noise generators."""
    
    def __init__(self, seed: int = None):
        """
        Parameters
        ----------
        seed : int, optional
            Random seed for reproducibility.
        """
        self.seed = seed
        if seed is not None:
            random.seed(seed)
    
    def generate(self, avail: Dict, staff_avail: Dict, 
                 num_people: int = 1, intensity: int = 1,
                 assigned_staff: Optional[List[str]] = None,
                 assigned_candidates: Optional[List[str]] = None,
                 active_slots: Optional[Set[str]] = None,
                 staff_assignment: Optional[Dict[str, List[str]]] = None,
                 schedule: Optional[Dict[str, str]] = None) -> Tuple[Dict, Dict]:
        """
        Generate noise in the availability matrices.
        
        Parameters
        ----------
        avail : Dict
            Candidate availability dict (candidate_id -> {slot -> 0/1})
        staff_avail : Dict
            Staff availability dict (staff_id -> {slot -> 0/1})
        num_people : int
            Number of people/candidates to affect.
        intensity : int
            Intensity of perturbation (meaning varies by noise type).
        
        Returns
        -------
        Tuple[Dict, Dict]
            Modified (avail, staff_avail) dicts.
        """
        raise NotImplementedError


class StaffUnavailableNoise(NoiseGenerator):
    """Make specific staff members unavailable for certain slots."""
    
    def generate(self, avail: Dict, staff_avail: Dict,
                 num_people: int = 1, intensity: int = 1,
                 assigned_staff: Optional[List[str]] = None,
                 assigned_candidates: Optional[List[str]] = None,
                 active_slots: Optional[Set[str]] = None,
                 staff_assignment: Optional[Dict[str, List[str]]] = None,
                 schedule: Optional[Dict[str, str]] = None) -> Tuple[Dict, Dict]:
        """
        Make num_people staff unavailable for intensity slots each.
        
        Parameters
        ----------
        num_people : int
            Number of distinct staff to affect.
        intensity : int
            Number of slots to make each staff member unavailable for.
        """
        new_avail = copy.deepcopy(avail)
        new_staff_avail = copy.deepcopy(staff_avail)
        
        # Preferred behavior: if a staff_assignment mapping is provided, only
        # affect staff on the slots they are actually assigned to.
        if staff_assignment is not None:
            # Build staff -> assigned slots mapping (intersection with active_slots if provided)
            staff_to_slots: Dict[str, List[str]] = {}
            for slot, staff_list in staff_assignment.items():
                if active_slots is not None and slot not in active_slots:
                    continue
                for s in staff_list:
                    if s not in staff_to_slots:
                        staff_to_slots[s] = []
                    staff_to_slots[s].append(slot)

            if not staff_to_slots:
                return new_avail, new_staff_avail

            staff_ids = list(staff_to_slots.keys())
            chosen_staff = random.sample(staff_ids, min(num_people, len(staff_ids)))
            for target_staff in chosen_staff:
                assigned_slots = [t for t in staff_to_slots.get(target_staff, []) if new_staff_avail.get(target_staff, {}).get(t, 0) == 1]
                if not assigned_slots:
                    continue
                # pick up to intensity slots among their assigned slots
                targets = random.sample(assigned_slots, min(intensity, len(assigned_slots)))
                for t in targets:
                    new_staff_avail[target_staff][t] = 0
            return new_avail, new_staff_avail

        # Fallback: previous behavior (respect assigned_staff list and active_slots)
        staff_ids = list(assigned_staff) if assigned_staff is not None else list(new_staff_avail.keys())
        if not staff_ids:
            return new_avail, new_staff_avail

        # Choose up to num_people distinct staff
        chosen = random.sample(staff_ids, min(num_people, len(staff_ids)))

        for target_staff in chosen:
            slots = list(new_staff_avail.get(target_staff, {}).keys())
            # Only consider slots that are currently available for that staff
            available_slots = [t for t in slots if new_staff_avail[target_staff][t] == 1]
            # If active_slots provided, further restrict to those slots
            if active_slots is not None:
                available_slots = [t for t in available_slots if t in active_slots]

            if not available_slots:
                continue

            # Select up to intensity slots to make unavailable
            targets = random.sample(available_slots, min(intensity, len(available_slots)))
            for t in targets:
                new_staff_avail[target_staff][t] = 0
        
        return new_avail, new_staff_avail


class CandidateUnavailableNoise(NoiseGenerator):
    """Make specific candidates unavailable for certain slots."""
    
    def generate(self, avail: Dict, staff_avail: Dict,
                 num_people: int = 1, intensity: int = 1,
                 assigned_staff: Optional[List[str]] = None,
                 assigned_candidates: Optional[List[str]] = None,
                 active_slots: Optional[Set[str]] = None,
                 staff_assignment: Optional[Dict[str, List[str]]] = None,
                 schedule: Optional[Dict[str, str]] = None) -> Tuple[Dict, Dict]:
        """
        Make num_people candidates unavailable for intensity slots each.
        
        Parameters
        ----------
        num_people : int
            Number of distinct candidates to affect.
        intensity : int
            Number of slots to make each candidate unavailable for.
        """
        new_avail = copy.deepcopy(avail)
        new_staff_avail = copy.deepcopy(staff_avail)
        
        # If schedule mapping provided, restrict to the candidate's scheduled slot
        cand_ids = list(assigned_candidates) if assigned_candidates is not None else list(new_avail.keys())
        if not cand_ids:
            return new_avail, new_staff_avail
        
        # Choose up to num_people distinct candidates
        chosen = random.sample(cand_ids, min(num_people, len(cand_ids)))
        
        for target_cand in chosen:
            # If schedule mapping provided, only consider their scheduled slot
            if schedule is not None and target_cand in schedule:
                slots = [schedule[target_cand]]
            else:
                slots = list(new_avail.get(target_cand, {}).keys())

            available_slots = [t for t in slots if new_avail.get(target_cand, {}).get(t, 0) == 1]
            if active_slots is not None:
                available_slots = [t for t in available_slots if t in active_slots]

            if not available_slots:
                continue

            # Select up to intensity slots to make unavailable
            targets = random.sample(available_slots, min(intensity, len(available_slots)))
            for t in targets:
                new_avail[target_cand][t] = 0
        
        return new_avail, new_staff_avail


class CandidateRemovalNoise(NoiseGenerator):
    """Remove candidates from the problem."""
    
    def generate(self, avail: Dict, staff_avail: Dict,
                 num_people: int = 1, intensity: int = None,
                 **kwargs) -> Tuple[Dict, Dict]:
        """
        Remove num_people candidates from the problem.
        
        Parameters
        ----------
        num_people : int
            Number of candidates to remove (if > 1) or percentage (if 0 < x <= 1).
        intensity : int
            Unused for this noise type.
        """
        new_avail = copy.deepcopy(avail)
        new_staff_avail = copy.deepcopy(staff_avail)
        
        cand_ids = list(new_avail.keys())
        if not cand_ids:
            return new_avail, new_staff_avail
        
        # Determine how many to remove
        if 0 < num_people < 1:
            # Percentage
            num_to_remove = max(1, int(len(cand_ids) * num_people))
        else:
            # Absolute count
            num_to_remove = min(int(num_people), len(cand_ids))
        
        # Select and remove
        chosen = random.sample(cand_ids, num_to_remove)
        for cand in chosen:
            del new_avail[cand]
        
        return new_avail, new_staff_avail


class StaffRemovalNoise(NoiseGenerator):
    """Remove staff members from the problem."""
    
    def generate(self, avail: Dict, staff_avail: Dict,
                 num_people: int = 1, intensity: int = None,
                 **kwargs) -> Tuple[Dict, Dict]:
        """
        Remove num_people staff from the problem.
        
        Parameters
        ----------
        num_people : int
            Number of staff to remove (if > 1) or percentage (if 0 < x <= 1).
        intensity : int
            Unused for this noise type.
        """
        new_avail = copy.deepcopy(avail)
        new_staff_avail = copy.deepcopy(staff_avail)
        
        staff_ids = list(new_staff_avail.keys())
        if not staff_ids:
            return new_avail, new_staff_avail
        
        # Determine how many to remove
        if 0 < num_people < 1:
            # Percentage
            num_to_remove = max(1, int(len(staff_ids) * num_people))
        else:
            # Absolute count
            num_to_remove = min(int(num_people), len(staff_ids))
        
        # Select and remove
        chosen = random.sample(staff_ids, num_to_remove)
        for staff in chosen:
            del new_staff_avail[staff]
        
        return new_avail, new_staff_avail


# Registry of available noise generators
NOISE_GENERATORS: Dict[str, type] = {
    "staff_unavailable": StaffUnavailableNoise,
    "candidate_unavailable": CandidateUnavailableNoise,
    "candidate_removal": CandidateRemovalNoise,
    "staff_removal": StaffRemovalNoise,
}


def get_noise_generator(noise_type: str, seed: int = None) -> NoiseGenerator:
    """
    Retrieve a noise generator by type.
    
    Parameters
    ----------
    noise_type : str
        Type of noise to generate (key in NOISE_GENERATORS).
    seed : int, optional
        Random seed for reproducibility.
    
    Returns
    -------
    NoiseGenerator
        Instantiated noise generator.
    
    Raises
    ------
    ValueError
        If noise_type is not registered.
    """
    if noise_type not in NOISE_GENERATORS:
        raise ValueError(f"Unknown noise type: {noise_type}. Available: {list(NOISE_GENERATORS.keys())}")
    
    generator_class = NOISE_GENERATORS[noise_type]
    return generator_class(seed=seed)


def apply_noise(avail: Dict, staff_avail: Dict,
                noise_type: str = "staff_unavailable",
                num_people: int = 1,
                intensity: int = 1,
                seed: int = None,
                assigned_staff: Optional[List[str]] = None,
                assigned_candidates: Optional[List[str]] = None,
                active_slots: Optional[Set[str]] = None,
                staff_assignment: Optional[Dict[str, List[str]]] = None,
                schedule: Optional[Dict[str, str]] = None) -> Tuple[Dict, Dict]:
    """
    Apply noise to availability matrices (convenience function).
    
    Parameters
    ----------
    avail : Dict
        Candidate availability dict.
    staff_avail : Dict
        Staff availability dict.
    noise_type : str
        Type of noise (from NOISE_GENERATORS keys).
    num_people : int
        Number of people affected by the noise.
    intensity : int
        Intensity level of the noise.
    seed : int, optional
        Random seed for reproducibility.
    
    Returns
    -------
    Tuple[Dict, Dict]
        Modified (avail, staff_avail) with noise applied.
    """
    generator = get_noise_generator(noise_type, seed=seed)
    return generator.generate(
        avail,
        staff_avail,
        num_people=num_people,
        intensity=intensity,
        assigned_staff=assigned_staff,
        assigned_candidates=assigned_candidates,
        active_slots=active_slots,
        staff_assignment=staff_assignment,
        schedule=schedule,
    )
