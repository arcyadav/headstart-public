"""What the progress log says about the user, for the Stats page:

- pace: how long things really take, per subject and kind of task (study, which takes
  in the lectures made from classes, assignment, other, revision), from finished work;
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


# The pace and effort columns. Lectures from classes count as study.
KINDS = ("study", "assignment", "other", "revision")
# A usual time is offered for new tasks of a type once this many are finished.
MIN_USUAL = 3


def _round_slot(minutes: float) -> int:
    return int(round(minutes / SLOT_MIN) * SLOT_MIN)


def _counted(area) -> tuple[dict[str, list[Item]], list[Item]]:
    """A subject's finished items by kind, and the ones left out (covered elsewhere)."""
    kinds: dict[str, list[Item]] = {k: [] for k in KINDS}
    left_out = []
    for i in area.items:
        if not i.done or not i.total_min:
            continue
        if i.spent_min < COVERED_ELSEWHERE * i.total_min:
            left_out.append(i)
        else:
            kinds[i.task_type].append(i)
    return kinds, left_out


def pace(inp: ScheduleInput) -> dict:
    """Per work subject: the actual/estimate ratio for each kind of task, and for the
    lectures made from classes, planned vs actual average and a suggested estimate; plus
    the finished items left out. Also each kind's usual time (average actual time), once
    MIN_USUAL are finished, to pre-fill new tasks."""
    subjects, left_out = [], []
    for area in inp.areas:
        if not area.kind.is_work:
            continue
        kinds, out = _counted(area)
        left_out += [{"area": area.name, "title": i.title, "kind": i.task_type,
                      "spent_min": i.spent_min, "estimate_min": i.total_min} for i in out]
        if not any(kinds.values()):
            continue
        row = {"area": area.name, "lecture": None, "usual": {}}
        for k in KINDS:
            done = kinds[k]
            est = sum(i.total_min for i in done)
            row[k] = {"n": len(done), "ratio": round(sum(i.spent_min for i in done) / est, 2)} if done else None
            if k != "revision" and len(done) >= MIN_USUAL:
                row["usual"][k] = {"n": len(done), "min": _round_slot(sum(i.spent_min for i in done) / len(done))}
        lec = [i for i in kinds["study"] if i.lecture_date]
        if lec:
            actual = sum(i.spent_min for i in lec) / len(lec)
            suggest = _round_slot(actual)
            row["lecture"] = {
                "n": len(lec), "actual_min": round(actual), "current_min": area.lecture_estimate_min,
                "suggest_min": suggest if len(lec) >= MIN_LECTURES
                and abs(suggest - area.lecture_estimate_min) > CLOSE_ENOUGH_MIN else None,
            }
        subjects.append(row)
    return {"subjects": subjects, "left_out": left_out}


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
