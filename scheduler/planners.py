"""Separate planners for the hosted site: each lives in its own folder (setup.json,
progress.json, plan.json, plan.txt) under the planners directory, named by its id. The
id in the link is the only key, so it is long enough not to be guessed.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from . import setup_file

ID = re.compile(r"^[a-z0-9]{4,32}$")
FILES = ("setup.json", "progress.json", "plan.json", "plan.txt")

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
    """The planner's folder, or None if the id is malformed or unknown."""
    if not ID.match(planner_id or ""):
        return None
    d = Path(root) / planner_id
    return d if d.is_dir() else None


def paths(d: Path) -> dict[str, str]:
    return {"input": str(d / "setup.json"), "progress": str(d / "progress.json"),
            "output": str(d / "plan.json")}


def reset(root: str | Path, planner_id: str, now: datetime | None = None) -> Path:
    """Make (or wipe) a planner back to the blank first screen."""
    d = Path(root) / planner_id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    setup_file.write(d / "setup.json", starter(now))
    (d / "progress.json").write_text("[]\n", encoding="utf-8")
    return d


def create(root: str | Path, now: datetime | None = None) -> str:
    """A new blank planner; returns its id."""
    while True:
        pid = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(10))
        if not (Path(root) / pid).exists():
            reset(root, pid, now)
            return pid


def publish(root: str | Path, planner_id: str, setup: dict, progress: list) -> Path:
    """Replace a planner's data with a copy from elsewhere (e.g. the laptop)."""
    d = Path(root) / planner_id
    d.mkdir(parents=True, exist_ok=True)
    setup_file.write(d / "setup.json", setup)
    (d / "progress.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    for name in ("plan.json", "plan.txt"):  # the old plan belongs to the old data
        (d / name).unlink(missing_ok=True)
    return d
