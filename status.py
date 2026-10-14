"""Record what you did, then rebuild the plan (see spec.md, "Session status update").

    python status.py session "project 2" --left 4   # finished a session; 4 hr still needed
    python status.py session "project 2"            # finished a session; left = left - session
    python status.py session "project 2" --left 0   # finished a session and the task
    python status.py done "rp 8/9"                  # the task is finished
    python status.py missed "ps 6"                  # logged only; the plan moves it anyway
    python status.py session workout                # a weekly-activity session
    python status.py reopen "project 2" --left 6    # marked done by mistake: 6 hr left
    python status.py undo                           # take back the last entry
    python status.py list [query]                   # what is still open

The hours worked in a session default to the length of that task's next session in the
last plan (the one you just did); add --spent 2 if you worked a different amount.

Names match loosely: every word must appear in the title or its initials, so "ps 6"
finds "RP Problem Set 6". Entries go to data/progress.json.
"""

import argparse
import sys
from datetime import datetime

from plan import DEFAULT_INPUT, DEFAULT_OUTPUT, DEFAULT_PROGRESS, build
from scheduler import load_input
from scheduler.models import Item, display_title
from scheduler.progress import append, entry as make_entry, find, planned_session_min, read_log, take_back
from scheduler.report import hm


def _describe(c) -> str:
    title = display_title(c.title, c.area)
    if isinstance(c, Item):
        due = f", by {c.finish_by:%a %d %b %H:%M}" if c.finish_by else ""
        return f"{title} ({hm(c.estimate_min)} left{due})"
    return f"{title} (weekly)"


def _pick(matches: list, query: str):
    exact = [c for c in matches if display_title(c.title, c.area).lower() == query.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"Nothing open matches {query!r}. Try: python status.py list")
    options = "\n".join(f"  - {_describe(c)}" for c in matches)
    sys.exit(f"{query!r} matches several things; be more specific:\n{options}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Record progress and re-plan.")
    ap.add_argument("status", choices=["session", "done", "missed", "reopen", "undo", "list"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--left", type=float, help="hours still needed after this session")
    ap.add_argument("--spent", type=float, help="hours actually worked (default: the planned session)")
    ap.add_argument("--now", type=datetime.fromisoformat, help="record and plan as if at this time")
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--progress", default=DEFAULT_PROGRESS)
    args = ap.parse_args()

    if args.status == "undo":
        log = read_log(args.progress)
        if not log:
            sys.exit("Nothing to undo.")
        take_back(args.progress, [log[-1]])
        print(f"Took back: {log[-1]}\n")
        print(build(args.input, DEFAULT_OUTPUT, args.now, args.progress).splitlines()[2])
        return

    inp = load_input(args.input, now=args.now, progress=args.progress)
    matches = find(inp, args.query, include_done=args.status == "reopen")
    if args.status == "list":
        for c in matches:
            print(f"  {_describe(c)}")
        return
    if not args.query:
        sys.exit("Say what you did, e.g.: python status.py session \"project 2\" --left 4")

    target = _pick(matches, args.query)
    title = display_title(target.title, target.area)
    spent = args.spent
    if args.status == "session" and isinstance(target, Item) and spent is None:
        planned = planned_session_min(DEFAULT_OUTPUT, target.id)
        if planned is None:
            sys.exit(f"{title} isn't in the last plan; say how long you worked with --spent")
        spent = planned / 60
    if args.status == "reopen" and args.left is None:
        sys.exit("reopen needs --left: how many hours are still needed?")
    left = args.left if args.status in ("session", "reopen") else None
    entry = make_entry(inp.now, target, args.status, spent, left)
    append(args.progress, entry)

    if args.status == "session" and isinstance(target, Item):
        after = load_input(args.input, now=args.now, progress=args.progress)
        item = next(i for i in after.items if i.id == target.id)
        state = "Task finished." if item.done else f"{hm(item.estimate_min)} left."
        print(f"Recorded: {title} session {entry['session']} done "
              f"({hm(round(entry['spent_hr'] * 60))}). {state}\n")
    else:
        print(f"Recorded: {title} {args.status}.\n")

    text = build(args.input, DEFAULT_OUTPUT, args.now, args.progress)
    lines = text.splitlines()
    print("\n".join(lines[2:3]))  # the "Now/Next" line
    problems = lines[next(i for i, line in enumerate(lines) if line.startswith("Problems")):]
    print("\n".join(problems))
    print(f"\nFull plan: {DEFAULT_OUTPUT.replace('.json', '.txt')}")


if __name__ == "__main__":
    main()
