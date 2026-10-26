"""What the progress log says about the user, for the Stats page:

- exam effort: hours put into everything that counted toward each exam, by type of task
  (study, which takes in the lectures made from classes, assignment, other, revision);
- study times: when in the day and week the hours were studied.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import ScheduleInput

# The effort columns. Lectures from classes count as study.
KINDS = ("study", "assignment", "other", "revision")


def exam_effort(inp: ScheduleInput) -> list[dict]:
    """Minutes logged on everything that counts toward each exam, by kind, in exam order."""
    out = []
    for area in inp.areas:
        for m in area.milestones:
            split = dict.fromkeys(KINDS, 0)
            for i in inp.items:
                if i.counts_toward is m:
                    split[i.task_type] += i.spent_min
            if not sum(split.values()) and m.over < inp.now:
                continue  # a past exam with nothing logged (before tracking began)
            out.append({"id": m.id, "title": m.title, "area": area.name, "at": m.at.isoformat(),
                        "quiz": m.quiz, "upcoming": m.over >= inp.now, "total_min": sum(split.values()),
                        **{f"{k}_min": v for k, v in split.items()}})
    return sorted(out, key=lambda e: e["at"])


def study_times(inp: ScheduleInput, log: list[dict]) -> dict:
    """Minutes studied per hour of the day (0-23) and per weekday (Mon-Sun). A logged
    entry is saved when the session ends, so it is taken to have started `spent_hr`
    earlier; its minutes are spread over the hours it covered."""
    targets = {i.id: i for i in inp.items}
    targets.update({a.id: a for a in inp.activities})
    hours, weekdays = [0] * 24, [0] * 7
    for e in log:
        spent = e.get("spent_hr")
        target = targets.get(e["id"])
        if e["status"] not in ("session", "done") or not spent or target is None:
            continue
        if not inp.area(target.area).kind.is_work:
            continue
        end = datetime.fromisoformat(e["at"])
        if end > inp.now:
            continue
        t, left = end - timedelta(hours=float(spent)), round(float(spent) * 60)
        while left > 0:
            step = min(left, 60 - t.minute)
            hours[t.hour] += step
            weekdays[t.weekday()] += step
            t, left = t + timedelta(minutes=step), left - step
    return {"hours": hours, "weekdays": weekdays, "best": best_hours(hours)}


def best_hours(hours: list[int], width: int = 3) -> str | None:
    """The `width`-hour stretch (it may run past midnight) with the most study, e.g.
    "22:00-01:00", or None without enough data."""
    if sum(hours) < 120:
        return None
    start = max(range(24), key=lambda h: sum(hours[(h + k) % 24] for k in range(width)))
    return f"{start:02d}:00-{(start + width) % 24:02d}:00"
