"""Shared paths and settings for the Squint classifier pipeline (standard library only).

The calibration helpers (word counts, sentence splitting, JSONL IO, the CLI generator) are
imported from ../calibration rather than copied.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

CLF_DIR = Path(__file__).resolve().parent
ROOT = CLF_DIR.parent
CAL_DIR = ROOT / "calibration"
sys.path.append(str(CAL_DIR))  # after classifier/ so same-named scripts resolve here

DATA_DIR = CLF_DIR / "data"          # gitignored: human_extra.jsonl, ood/, dataset.jsonl
GEN_DIR = CLF_DIR / "generated"      # gitignored: plan.jsonl, ai_<source>.jsonl, call records
RUNS_DIR = CLF_DIR / "runs"          # gitignored: checkpoints, final models, predictions
STATE_DIR = CLF_DIR / "state"        # gitignored: nightly state file and lock
REPORTS_DIR = CLF_DIR / "reports"    # committed: dated gate reports and morning summaries
CONFIG_PATH = Path(os.environ.get("SQUINT_CLF_CONFIG", CLF_DIR / "config.toml"))

CAL_DATA = CAL_DIR / "data"
CAL_GEN = CAL_DIR / "generated"


def load_config(path: Path | None = None) -> dict:
    with open(path or CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def cal_module(name: str):
    """Import calibration/<name>.py under the alias `cal_<name>`. Some calibration scripts share
    a file name with a classifier script (build_dataset, fetch_human), so a plain import could
    pick the wrong one depending on sys.path order."""
    import importlib.util

    alias = f"cal_{name}"
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, CAL_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod
