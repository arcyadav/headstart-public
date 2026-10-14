"""Planners on the hosted site, each in its own folder (setup.json, progress.json,
plan.json, plan.txt) under the planners directory:

- demo/: the shared try-it-yourself planner. Never saved anywhere else: it is wiped by
  Reset, and when the server restarts it starts blank again.
- kept/<id>/: planners copied from someone's own computer with publish.py (the owner's,
  to show it online). Only these are kept across restarts (see sync.py). The id in the
  link is the only key, so it is long enough not to be guessed.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import setup_file

DEMO = "demo"
KEPT = "kept"
ID = re.compile(r"^[a-z0-9]{4,32}$")

# Study slots a new planner starts with: mornings, afternoons and evenings every day,
# with breaks for lunch and dinner. Changed on the Settings page.
DEFAULT_SLOTS = [["08:00", "13:00"], ["14:00", "19:00"], ["20:00", "23:00"]]


def starter(now: datetime | None = None) -> dict:
    """A blank planner: default study slots and limits, no semester yet (the first screen
    asks for it), no subjects."""
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    return {
        "tracking_since": now.isoformat(timespec="minutes"),
        "availability": {d: [list(s) for s in DEFAULT_SLOTS] for d in setup_file.DAYS},
        "settings": {"max_work_hr": 6, "min_session_min": 45, "max_session_min": 120},
        "areas": [],
    }


def folder(root: str | Path, planner_id: str) -> Path | None:
    """The planner's folder, or None if the id is malformed or unknown. The demo is made
    blank on first use."""
    if planner_id == DEMO:
        d = Path(root) / DEMO
        return d if d.is_dir() else reset(root, now=None)
    if not ID.match(planner_id or ""):
        return None
    d = Path(root) / KEPT / planner_id
    return d if d.is_dir() else None


def paths(d: Path) -> dict[str, str]:
    return {"input": str(d / "setup.json"), "progress": str(d / "progress.json"),
            "output": str(d / "plan.json")}


def reset(root: str | Path, now: datetime | None = None) -> Path:
    """Make (or wipe) the demo, back to the blank first screen."""
    d = Path(root) / DEMO
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    setup_file.write(d / "setup.json", starter(now))
    (d / "progress.json").write_text("[]\n", encoding="utf-8")
    return d


def publish(root: str | Path, planner_id: str, setup: dict, progress: list) -> Path:
    """Replace a kept planner's data with a copy from someone's computer."""
    d = Path(root) / KEPT / planner_id
    d.mkdir(parents=True, exist_ok=True)
    setup_file.write(d / "setup.json", setup)
    (d / "progress.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    for name in ("plan.json", "plan.txt"):  # the old plan belongs to the old data
        (d / name).unlink(missing_ok=True)
    return d
