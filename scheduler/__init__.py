"""Scheduler package — constraint-based academic scheduling.

Public API
----------
- :func:`solver.solve_initial_schedule` — compute an initial schedule.
- :func:`solver.reschedule` — reschedule after a change event.
- :mod:`strategies` — eight rescheduling strategy implementations.
- :mod:`model_builder` — Google OR-Tools CP-SAT model construction.
"""
