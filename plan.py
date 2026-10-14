"""Build a plan: python plan.py [input.json] [output.json] [--now 2026-10-01T09:00]

Applies the progress log (data/progress.json) and plans from the real time unless --now
is given. Also saves the readable text version next to the JSON (same name, .txt).
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from scheduler import load_input
from scheduler.engine import solve
from scheduler.report import read_previous, to_json, to_text

DEFAULT_INPUT = "data/sem5.json"
DEFAULT_OUTPUT = "out/plan.json"
DEFAULT_PROGRESS = "data/progress.json"


def build(src: str, dst: str, now: datetime | None = None, progress: str = DEFAULT_PROGRESS) -> str:
    """Plan and save it; returns the text version. The plan stays close to the one saved
    before at `dst`."""
    inp = load_input(src, now=now, progress=progress)
    plan = solve(inp, previous=read_previous(dst))
    text = to_text(inp, plan)
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(to_json(inp, plan), indent=2), encoding="utf-8")
    out.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the plan.")
    ap.add_argument("input", nargs="?", default=DEFAULT_INPUT)
    ap.add_argument("output", nargs="?", default=DEFAULT_OUTPUT)
    ap.add_argument("--now", type=datetime.fromisoformat, help="plan as if it were this time")
    ap.add_argument("--progress", default=DEFAULT_PROGRESS, help="progress log to apply")
    args = ap.parse_args()
    print(build(args.input, args.output, args.now, args.progress))
    print(f"\nSaved {args.output} and {Path(args.output).with_suffix('.txt')}")


if __name__ == "__main__":
    main()
