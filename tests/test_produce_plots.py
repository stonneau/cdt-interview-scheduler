from pathlib import Path
import shutil

from eval.harness import run_demo_small
from eval.produce_plots import main as produce_main


def test_produce_plots_smoke(tmp_path, monkeypatch):
    base = tmp_path / "data"
    base.mkdir()

    # run harness to populate base with nested run_id structure
    ds = run_demo_small(random_seed=42, base_dir=str(base), persist=True)

    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    # call produce_plots main with args by monkeypatching argv
    import sys
    monkeypatch.setattr(sys, "argv", ["produce_plots", "--base", str(base), "--out", str(out_dir)])
    # run
    produce_main()

    # produce_plots.main() writes plots to out_dir/<run_id>/ (one sub-dir per run)
    # so collect all png files recursively
    all_files = list(out_dir.rglob("*"))
    names = [p.name for p in all_files if p.is_file()]
    assert any("solver_time" in n for n in names)
    assert any("bar_changes" in n for n in names)
