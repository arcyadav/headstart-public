"""The progress log: what the user actually did (see spec.md, "Session status update").

A JSON list of entries, oldest first:

    {"at": "2026-09-30T19:22", "id": "aids/project-2", "status": "session", "session": 1, "spent_hr": 2}
    {"at": "2026-09-30T21:00", "id": "aids/project-2", "status": "session", "session": 2,
     "spent_hr": 1.33, "left_hr": 4}
    {"at": "2026-10-01T09:30", "id": "rp/lecture-0908", "status": "done", "spent_hr": 1.5}
    {"at": "2026-10-02T08:30", "id": "rp/problem-set-6", "status": "missed"}
    {"at": "2026-10-02T12:30", "id": "workout/workout", "status": "done"}

The input file stays the user's setup; the log only records progress, and applying it
changes what is left to plan.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from .models import Item, ScheduleInput, WeeklyActivity, display_title, round_up_to_slot

STATUSES = ("session", "done", "missed", "reopen", "adjust")


def read_log(path: str | Path) -> list[dict]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _write(path: str | Path, log: list[dict]) -> None:
    Path(path).write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")


def append(path: str | Path, entry: dict) -> None:
    _write(path, read_log(path) + [entry])


def drop(path: str | Path, item_id: str) -> None:
    """Forget a deleted task's progress."""
    _write(path, [e for e in read_log(path) if e["id"] != item_id])


def take_back(path: str | Path, entries: list[dict]) -> int:
    """Undo: take these exact entries back out of the log (the latest copy of each).
    Returns how many were taken out."""
    log, count = read_log(path), 0
    for e in entries:
        for i in range(len(log) - 1, -1, -1):
            if log[i] == e:
                del log[i]
                count += 1
                break
    _write(path, log)
    return count


def apply(inp: ScheduleInput, log: list[dict]) -> list[str]:
    """Apply the log to the input, oldest entry first:

    - session: a work session is done. Time left becomes the user's `left_hr` if given
      (0 = finished), else what was left minus the session's hours.
    - done: the task is finished.
    - missed: changes nothing; the plan simply moves on.
    - reopen: a finished task isn't finished after all; `left_hr` is what is left.
    - adjust: the task was edited; `left_hr` is what is left now.
    - session/done on a weekly activity: one session toward that week's target.

    Entries after `now` are ignored (useful when planning with --now). Returns warnings."""
    items = {i.id: i for i in inp.items}
    acts = {a.id: a for a in inp.activities}
    for item in items.values():
        item.total_min = item.estimate_min
    warnings = []
    for e in sorted(log, key=lambda e: e["at"]):
        at = datetime.fromisoformat(e["at"])
        if at > inp.now:
            continue
        status = e["status"]
        if e["id"] in items:
            item = items[e["id"]]
            if e.get("spent_hr"):
                item.spent_min += round(float(e["spent_hr"]) * 60)
            if status == "session":
                item.sessions_logged += 1
                if e.get("left_hr") is not None:
                    item.estimate_min = round_up_to_slot(round(float(e["left_hr"]) * 60))
                else:
                    spent = round(float(e["spent_hr"]) * 60)
                    item.estimate_min = max(0, round_up_to_slot(item.estimate_min - spent))
                if e.get("left_hr") == 0:
                    item.done = True
            elif status == "done":
                item.done, item.estimate_min = True, 0
            elif status == "reopen":
                item.done = False
                item.estimate_min = round_up_to_slot(round(float(e["left_hr"]) * 60))
            elif status == "adjust":
                item.estimate_min = round_up_to_slot(round(float(e["left_hr"]) * 60))
        elif e["id"] in acts:
            act = acts[e["id"]]
            if status in ("session", "done"):
                spent = e.get("spent_hr")
                mins = round(float(spent) * 60) if spent else (act.session_min or act.min_session_min)
                inp.activity_done.append((act.id, at.date(), mins))
        else:
            warnings.append(f"progress log: no item or activity {e['id']!r} (entry at {e['at']})")
    for item in items.values():
        if not item.done and item.estimate_min == 0 and any(e["id"] == item.id for e in log):
            warnings.append(f"{display_title(item.title, item.area)}: the sessions add up to its "
                            f"whole estimate. If it's finished, mark it done; if not, log your next "
                            f"session with --left.")
    return warnings


def entry(now: datetime, target: Item | WeeklyActivity, status: str,
          spent_hr: float | None = None, left_hr: float | None = None) -> dict:
    """A log entry. A session on a task gets the next session number."""
    e = {"at": now.isoformat(timespec="minutes"), "id": target.id, "status": status}
    if status == "session" and isinstance(target, Item):
        e["session"] = target.sessions_logged + 1
    if spent_hr is not None:
        e["spent_hr"] = round(spent_hr, 2)
    if left_hr is not None:
        e["left_hr"] = left_hr
    return e


def planned_session_min(plan_json: str | Path, item_id: str) -> int | None:
    """Length of the task's first session in the last saved plan: the one the user has
    just done, if they followed the plan."""
    p = Path(plan_json)
    if not p.exists():
        return None
    for s in json.loads(p.read_text(encoding="utf-8"))["sessions"]:
        if s["id"] == item_id:
            start, end = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
            return int((end - start).total_seconds() // 60)
    return None


# --------------------------------------------------------------------------- matching


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9/]+", text.lower())


def _matches(query: str, title: str) -> bool:
    """Every query word appears in the title, or in the initials of its words, so "rp 8/9",
    "ps 6" (Problem Set 6) and "project 2" all work."""
    words = _words(title)
    text, initials = " ".join(words), "".join(w[0] for w in words)
    return all(q in text or q in initials for q in _words(query))


def find(inp: ScheduleInput, query: str, include_done: bool = False) -> list[Item | WeeklyActivity]:
    """Open items (or, for reopening, done ones too) and flexible weekly activities whose
    title matches the query."""
    open_items = [i for i in inp.items if include_done or not i.done]
    candidates = open_items + [a for a in inp.activities if not a.is_fixed]
    return [c for c in candidates if _matches(query, display_title(c.title, c.area))]


def daily(inp: ScheduleInput, log: list[dict]) -> dict[date, dict]:
    """What the user got done each day up to now, for the "Today" tally and the Stats page:
    minutes studied (sessions on work areas, so a workout doesn't count), study sessions
    logged, and tasks done: tasks still finished, on the day they were last finished, plus
    each hobby session logged that day."""
    items = {i.id: i for i in inp.items}
    acts = {a.id: a for a in inp.activities}
    days: dict[date, dict] = {}
    finished_on: dict[str, date] = {}
    for e in log:
        at = datetime.fromisoformat(e["at"])
        target = items.get(e["id"]) or acts.get(e["id"])
        if at > inp.now or target is None or e["status"] not in ("session", "done"):
            continue
        d = days.setdefault(at.date(), {"study_min": 0, "sessions": 0, "tasks_done": 0})
        if e["id"] in items and (e["status"] == "done" or e.get("left_hr") == 0):
            finished_on[e["id"]] = at.date()
        if not inp.area(target.area).kind.is_work:
            d["tasks_done"] += e["id"] in acts
            continue
        spent = e.get("spent_hr")
        if spent:
            d["study_min"] += round(float(spent) * 60)
        elif e["id"] in acts:
            d["study_min"] += target.session_min or target.min_session_min
        if e["status"] == "session" or e["id"] in acts or spent:
            d["sessions"] += 1
    for item_id, day in finished_on.items():
        if items[item_id].done:
            days[day]["tasks_done"] += 1
    return days


def today(inp: ScheduleInput, log: list[dict]) -> dict:
    """The "Today" tally: see daily()."""
    return daily(inp, log).get(inp.now.date(), {"study_min": 0, "sessions": 0, "tasks_done": 0})
