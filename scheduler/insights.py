"""What the progress log says about the user, for the Stats page:

- pace: how long things really take, per subject and kind, from finished work;
- exam effort: hours put into everything that counted toward each exam;
- study times: when in the day and week the hours were studied.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import SLOT_MIN, Item, ScheduleInput

# A task marked done with less than this share of its estimate logged was covered
# elsewhere (e.g. during revision, or skipped), so it says nothing about pace.
COVERED_ELSEWHERE = 0.25
# The lecture estimate is only suggested with this many finished lectures...
MIN_LECTURES = 2
# ...and only when it differs from the current one by more than this.
CLOSE_ENOUGH_MIN = 15


def _kind(item: Item) -> str:
    return "lecture" if item.lecture_date else "revision" if item.is_revision else "task"


def _round_slot(minutes: float) -> int:
    return int(round(minutes / SLOT_MIN) * SLOT_MIN)


def pace(inp: ScheduleInput) -> dict:
    """Per work subject: lectures (planned vs actual average, and a suggested estimate) and
    the actual/estimate ratio for tasks and revision; plus the finished items left out."""
    subjects, left_out = [], []
    for area in inp.areas:
        if not area.kind.is_work:
            continue
        kinds: dict[str, list[Item]] = {"lecture": [], "task": [], "revision": []}
        for i in area.items:
            if not i.done or not i.total_min:
                continue
            if i.spent_min < COVERED_ELSEWHERE * i.total_min:
                left_out.append({"area": area.name, "title": i.title, "kind": _kind(i),
                                 "spent_min": i.spent_min, "estimate_min": i.total_min})
                continue
            kinds[_kind(i)].append(i)
        if not any(kinds.values()):
            continue
        row = {"area": area.name, "lecture": None, "task": None, "revision": None}
        lec = kinds["lecture"]
        if lec:
            actual = sum(i.spent_min for i in lec) / len(lec)
            planned = sum(i.total_min for i in lec) / len(lec)
            suggest = _round_slot(actual)
            row["lecture"] = {
                "n": len(lec), "planned_min": round(planned), "actual_min": round(actual),
                "current_min": area.lecture_estimate_min,
                "suggest_min": suggest if len(lec) >= MIN_LECTURES
                and abs(suggest - area.lecture_estimate_min) > CLOSE_ENOUGH_MIN else None,
            }
        for k in ("task", "revision"):
            if kinds[k]:
                est = sum(i.total_min for i in kinds[k])
                row[k] = {"n": len(kinds[k]), "ratio": round(sum(i.spent_min for i in kinds[k]) / est, 2)}
        subjects.append(row)
    return {"subjects": subjects, "left_out": left_out}


def exam_effort(inp: ScheduleInput) -> list[dict]:
    """Hours logged on everything that counts toward each exam, by kind, in exam order."""
    out = []
    for area in inp.areas:
        for m in area.milestones:
            split = {"lecture": 0, "task": 0, "revision": 0}
            for i in inp.items:
                if i.counts_toward is m:
                    split[_kind(i)] += i.spent_min
            if not sum(split.values()) and m.over < inp.now:
                continue  # a past exam with nothing logged (before tracking began)
            out.append({"id": m.id, "title": m.title, "area": area.name, "at": m.at.isoformat(),
                        "upcoming": m.over >= inp.now, "total_min": sum(split.values()),
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
