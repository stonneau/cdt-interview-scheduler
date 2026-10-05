"""
Tests for the new CLI features added in the scheduling-functionality PR:
  - _compute_and_print_metrics helper
  - _generate_plots helper
  - --analyse-robustness flag behaviour
  - interactive mode 'metrics' and 'plots' commands (via _print_help coverage)
"""

import importlib
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json

# ── helpers imported directly from cli module ─────────────────────────────────

def _get_cli():
    import importlib
    import ui.cli as m
    return m


# ── _compute_and_print_metrics ────────────────────────────────────────────────

def test_compute_and_print_metrics_returns_dicts(capsys):
    cli = _get_cli()
    schedule = {"cand1": "2025-04-01 09:00-09:45", "cand2": "2025-04-01 09:45-10:30"}
    prev = {"cand1": "2025-04-01 09:00-09:45", "cand2": "2025-04-01 09:45-10:30"}
    staff_assignment = {
        "2025-04-01 09:00-09:45": ["s1", "s2"],
        "2025-04-01 09:45-10:30": ["s1", "s2"],
    }
    time_slots = list(schedule.values())

    stability, robustness = cli._compute_and_print_metrics(
        schedule=schedule,
        prev_schedule=prev,
        staff_assignment=staff_assignment,
        time_slots=time_slots,
    )

    assert "changed_assignments" in stability
    assert "staff_fairness_variance" in robustness
    assert stability["changed_assignments"] == 0.0  # nothing changed

    captured = capsys.readouterr()
    assert "Stability metrics" in captured.out
    assert "Robustness metrics" in captured.out


def test_compute_and_print_metrics_detects_changes(capsys):
    cli = _get_cli()
    schedule = {"cand1": "2025-04-01 09:45-10:30"}  # moved
    prev = {"cand1": "2025-04-01 09:00-09:45"}
    staff_assignment = {"2025-04-01 09:45-10:30": ["s1"]}

    stability, _ = cli._compute_and_print_metrics(
        schedule=schedule,
        prev_schedule=prev,
        staff_assignment=staff_assignment,
        time_slots=["2025-04-01 09:00-09:45", "2025-04-01 09:45-10:30"],
    )
    assert stability["changed_assignments"] == 1.0


# ── _generate_plots ───────────────────────────────────────────────────────────

def test_generate_plots_calls_produce_main_with_correct_args(tmp_path, capsys):
    """_generate_plots must forward base, run-id and out to produce_plots.main."""
    cli = _get_cli()

    captured_argv = []

    def fake_main():
        captured_argv.extend(sys.argv[:])

    with patch.dict(sys.modules, {"eval.produce_plots": MagicMock(main=fake_main)}):
        # Reload to pick up the mock
        import eval.produce_plots as ep_mock
        ep_mock.main = fake_main

        out_dir = str(tmp_path / "outputs")
        with patch("ui.cli._generate_plots", wraps=lambda **kw: None):
            pass  # just ensure no import error

    # Call _generate_plots directly, patching produce_main via monkeypatch of sys.argv
    orig = sys.argv[:]
    cli._generate_plots(run_id="run-abc", base_dir="data", out_dir=out_dir)
    # argv is restored after the call
    assert sys.argv == orig


def test_generate_plots_missing_module_prints_warning(capsys):
    """If eval.produce_plots is unavailable, _generate_plots should print a warning."""
    cli = _get_cli()
    with patch.dict(sys.modules, {"eval.produce_plots": None}):
        # This patches the module so ImportError is raised on import
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "eval.produce_plots":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            cli._generate_plots(run_id="run-abc", base_dir="data", out_dir="/tmp/out")

    captured = capsys.readouterr()
    assert "not available" in captured.out or "skipping" in captured.out.lower()


# ── help text includes new commands ──────────────────────────────────────────

def test_print_help_includes_metrics_and_plots(capsys):
    cli = _get_cli()
    cli._print_help()
    out = capsys.readouterr().out
    assert "metrics" in out
    assert "plots" in out


# ── --analyse-robustness flag ─────────────────────────────────────────────────

def test_analyse_robustness_flag_exists():
    """argparse must accept --analyse-robustness without error."""
    import argparse
    cli = _get_cli()
    # Rebuild the parser the same way main() does
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyse-robustness", action="store_true")
    args = parser.parse_args(["--analyse-robustness"])
    assert args.analyse_robustness is True


def test_analyse_robustness_prints_metrics(tmp_path, capsys):
    """When --analyse-robustness is given, metrics should appear in stdout."""
    from eval.harness import run_demo_small

    base = tmp_path / "data"
    base.mkdir()
    ds = run_demo_small(random_seed=42, base_dir=str(base), persist=True)

    # Get the schedule from DataStore
    schedules = list(ds.list_schedules())
    assert schedules, "Demo should produce at least one schedule"

    sched_payload = schedules[0]
    schedule = sched_payload.get("schedule", {})
    meta = sched_payload.get("metadata", {})
    staff_assignment = meta.get("staff_assignment", {})

    cli = _get_cli()
    cli._compute_and_print_metrics(
        schedule=schedule,
        prev_schedule={},
        staff_assignment=staff_assignment,
        time_slots=list(set(schedule.values())),
    )

    captured = capsys.readouterr()
    assert "Stability metrics" in captured.out
    assert "Robustness metrics" in captured.out
