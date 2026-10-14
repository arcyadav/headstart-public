"""Read and validate a ScheduleInput from a JSON file, then generate the lecture and
revision items (see spec.md, "Generated lecture items" and "Milestones")."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .progress import apply as apply_progress, read_log
from .models import (
    next_color,
    DEFAULT_ESTIMATE_MIN, DEFAULT_FOCUS_HR, DEFAULT_REVISION_DAYS, DEFAULT_REVISION_MIN,
    DEFAULT_SECTION_MIN, MAX_SESSION_MIN,
    WEEKDAYS, Area, AreaKind, Commitment, DayRule, Dependency, Item, Milestone, Pace,
    ScheduleInput, Section, Semester, Settings, WeeklyActivity, Window, round_up_to_slot,
)

END_OF_DAY = time(23, 59)


class InputError(ValueError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _hours_to_min(value) -> int | None:
    return None if value is None else round_up_to_slot(round(float(value) * 60))


def _time(text: str) -> time:
    if text == "24:00":
        return time(0, 0)  # midnight at the end of the day, as a window's end
    try:
        return time.fromisoformat(text)
    except ValueError as e:
        raise InputError(f"bad time {text!r}, expected HH:MM") from e


def _window(a: str, b: str, where: str) -> Window:
    if a == "24:00":
        raise InputError(f"{where}: a window can't start at 24:00")
    w = Window(_time(a), _time(b))
    if w.minutes <= 0:
        raise InputError(f"{where}: {a}-{b} ends before it starts")
    return w


def _availability(raw: dict) -> dict[str, list[Window]]:
    """Study slots per weekday. Older files give one span per day as day_bounds."""
    if "availability" in raw:
        out = {}
        for k, spans in raw["availability"].items():
            where = f"availability.{k}"
            slots = sorted((_window(a, b, where) for a, b in spans), key=lambda w: w.start_min)
            for prev, w in zip(slots, slots[1:]):
                if w.start_min < prev.end_min:
                    raise InputError(f"{where}: slots overlap")
            out[_weekday(k, "availability")] = slots
        return out
    if "day_bounds" in raw:
        return {_weekday(k, "day_bounds"): [_window(*v, f"day_bounds.{k}")]
                for k, v in raw["day_bounds"].items()}
    raise InputError("give availability: when you can study on each weekday")


def _date(text: str, where: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise InputError(f"{where}: bad date {text!r}, expected YYYY-MM-DD") from e


def _when(text: str, date_only: time, where: str) -> datetime:
    """A date or date-time. A bare date gets the time `date_only` (see spec.md, "Dates")."""
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), date_only)
        return datetime.fromisoformat(text)
    except ValueError as e:
        raise InputError(f"{where}: bad date {text!r}") from e


def _weekday(text: str, where: str) -> str:
    if text not in WEEKDAYS:
        raise InputError(f"{where}: unknown weekday {text!r}, use one of {WEEKDAYS}")
    return text


def _days(raw, where: str) -> list[str]:
    if raw == "all":
        return list(WEEKDAYS)
    return [_weekday(d, where) for d in raw]


# --------------------------------------------------------------------------- settings


def _day_rule(raw: dict, where: str) -> DayRule:
    return DayRule(
        bounds=_window(*raw["bounds"], where) if raw.get("bounds") else None,
        max_work_min=_hours_to_min(raw.get("max_work_hr")),
        min_work_min=_hours_to_min(raw.get("min_work_hr")),
    )


def _parse_settings(raw: dict) -> Settings:
    if raw.get("max_work_hr") is None:
        raise InputError("settings: max_work_hr is required")
    return Settings(
        max_work_min=_hours_to_min(raw["max_work_hr"]),
        min_work_min=_hours_to_min(raw.get("min_work_hr", 0)),
        min_session_min=round_up_to_slot(int(raw.get("min_session_min", 30))),
        max_session_min=round_up_to_slot(int(raw.get("max_session_min", MAX_SESSION_MIN))),
        weekday_rules={_weekday(k, "settings.weekday"): _day_rule(v, f"settings.weekday.{k}")
                       for k, v in raw.get("weekday", {}).items()},
        date_rules={_date(k, "settings.dates"): _day_rule(v, f"settings.dates.{k}")
                    for k, v in raw.get("dates", {}).items()},
    )


def _parse_semester(raw: dict | None) -> Semester | None:
    if not raw:
        return None
    sem = Semester(
        name=raw.get("name") or "Semester",
        start=_date(raw["start"], "semester start") if raw.get("start") else None,
        end=_date(raw["end"], "semester end") if raw.get("end") else None,
    )
    if sem.start and sem.end and sem.end <= sem.start:
        raise InputError("semester: the end must be after the start")
    return sem


def _parse_commitment(raw: dict) -> Commitment:
    where = f"commitment {raw.get('title')!r}"
    w = _window(*raw["time"], where)
    work = bool(raw.get("work", False))
    if raw.get("date"):
        return Commitment(raw["title"], w, date=_date(raw["date"], where), work=work)
    return Commitment(raw["title"], w, days=_days(raw.get("days", "all"), where), work=work,
                      skip={_date(d, where) for d in raw.get("skip", [])})


# --------------------------------------------------------------------------- areas


def _parse_timetable_changes(area: Area, changes: list[dict]) -> None:
    for c in changes:
        where = f"{area.name}: timetable change {c}"
        if "cancel" in c:
            area.cancelled.add(_date(c["cancel"], where))
        elif "extra" in c:
            d, a, b = c["extra"]
            area.extra.append((_date(d, where), _window(a, b, where)))
        elif "move" in c:
            area.cancelled.add(_date(c["move"], where))
            d, a, b = c["to"]
            area.extra.append((_date(d, where), _window(a, b, where)))
        else:
            raise InputError(f"{where}: expected cancel, extra or move")


def _parse_item(raw: dict, area: Area, milestones: dict[str, Milestone]) -> Item:
    title = raw["title"]
    where = f"{area.name} / {title}"
    sections = [Section(s["title"], _hours_to_min(s.get("estimate_hr")) or DEFAULT_SECTION_MIN,
                        bool(s.get("done", False))) for s in raw.get("sections", [])]
    if sections:
        estimate = sum(s.estimate_min for s in sections if not s.done)
    else:
        estimate = _hours_to_min(raw.get("estimate_hr")) or DEFAULT_ESTIMATE_MIN
    toward = None
    if raw.get("counts_toward"):
        toward = milestones.get(raw["counts_toward"])
        if toward is None:
            raise InputError(f"{where}: no milestone {raw['counts_toward']!r} in {area.name}")
    deps = []
    for d in raw.get("depends_on", []):
        on, soft = (d, False) if isinstance(d, str) else (d["on"], bool(d.get("soft", False)))
        deps.append(Dependency(on=on, hard=not soft))  # resolved to ids once all items exist
    return Item(
        id=raw.get("id") or f"{_slug(area.name)}/{_slug(title)}",
        title=title,
        area=area.name,
        estimate_min=estimate,
        is_work=area.kind.is_work,
        due=_when(raw["due"], END_OF_DAY, where) if raw.get("due") else None,
        counts_toward=toward,
        available_from=_when(raw["available_from"], time.min, where) if raw.get("available_from") else None,
        depends_on=deps,
        pace=Pace(raw.get("pace", "asap")),
        sections=sections,
    )


def _parse_weekly(raw: dict, area: Area) -> WeeklyActivity:
    title = raw["title"]
    where = f"{area.name} / {title}"
    act = WeeklyActivity(
        id=raw.get("id") or f"{_slug(area.name)}/{_slug(title)}",
        title=title,
        area=area.name,
        is_work=area.kind.is_work,
        sessions_per_week=raw.get("sessions_per_week"),
        session_min=_hours_to_min(raw.get("session_hr")),
        weekly_min=_hours_to_min(raw.get("weekly_hr")),
        min_session_min=round_up_to_slot(int(raw.get("min_session_min", 30))),
        preferred_days=_days(raw.get("preferred_days", []), where),
        fixed=[(_weekday(wd, where), _window(a, b, where)) for wd, a, b in raw.get("fixed", [])],
    )
    if not act.is_fixed and not ((act.sessions_per_week and act.session_min) or act.weekly_min):
        raise InputError(f"{where}: give sessions_per_week + session_hr, weekly_hr, or fixed times")
    return act


def _parse_area(raw: dict) -> Area:
    name = raw["name"]
    try:
        kind = AreaKind(raw["kind"])
    except ValueError as e:
        raise InputError(f"{name}: unknown kind {raw['kind']!r}") from e
    area = Area(
        name=name,
        kind=kind,
        color=raw.get("color"),
        weight=int(raw.get("weight", 1)),
        timetable=[(_weekday(wd, name), _window(a, b, f"{name} timetable"))
                   for wd, a, b in raw.get("timetable", [])],
        lecture_items=bool(raw.get("lecture_items", False)),
        lecture_estimate_min=_hours_to_min(raw.get("lecture_estimate_hr")) or DEFAULT_ESTIMATE_MIN,
        pending_lectures=[_date(d, f"{name} pending_lectures") for d in raw.get("pending_lectures", [])],
        lecture_overrides={_date(d, f"{name} lecture_overrides"): o
                           for d, o in raw.get("lecture_overrides", {}).items()},
    )
    _parse_timetable_changes(area, raw.get("timetable_changes", []))
    for m in raw.get("milestones", []):
        where = f"{name} / {m['title']}"
        rev = m.get("revision_hr")
        at, end = _when(m["date"], time.min, where), None
        if m.get("time"):  # an exam with a time blocks that slot
            w = _window(*m["time"], where)
            at, end = w.on(_date(m["date"], where))
        area.milestones.append(Milestone(
            id=m.get("id") or f"{_slug(name)}/{_slug(m['title'])}",
            title=m["title"],
            area=name,
            at=at,
            end=end,
            revision_min=DEFAULT_REVISION_MIN if rev is None else _hours_to_min(rev),
            revision_days=int(m.get("revision_days", DEFAULT_REVISION_DAYS)),
            syllabus_until=_date(m["syllabus_until"], where) if m.get("syllabus_until") else None,
            focus_hr=int(m.get("focus_hr", DEFAULT_FOCUS_HR)),
        ))
    by_id = {m.id: m for m in area.milestones}
    area.items = [_parse_item(i, area, by_id) for i in raw.get("items", [])]
    area.weekly = [_parse_weekly(w, area) for w in raw.get("weekly", [])]
    return area


# --------------------------------------------------------------------------- generation


def next_milestone(area: Area, day: date, after: datetime) -> Milestone | None:
    """The first exam after a lecture whose syllabus includes that lecture's date."""
    ok = [m for m in area.milestones
          if m.at > after and (m.syllabus_until is None or day <= m.syllabus_until)]
    return min(ok, key=lambda m: m.at, default=None)


def _lecture_item(area: Area, day: date, ends: datetime | None) -> Item:
    where = f"{area.name} lecture {day}"
    override = area.lecture_overrides.get(day, {})
    toward = next_milestone(area, day, ends or datetime.combine(day, END_OF_DAY))
    if "counts_toward" in override:
        mid = override["counts_toward"]
        toward = None if mid is None else next((m for m in area.milestones if m.id == mid), None)
        if mid is not None and toward is None:
            raise InputError(f"{where}: no milestone {mid!r} in {area.name}")
    return Item(
        id=f"{_slug(area.name)}/lecture-{day:%m%d}",
        title=f"{area.name} lecture {day.day}/{day.month}",
        area=area.name,
        estimate_min=_hours_to_min(override.get("estimate_hr")) or area.lecture_estimate_min,
        is_work=area.kind.is_work,
        due=_when(override["due"], END_OF_DAY, where) if override.get("due") else None,
        counts_toward=toward,
        available_from=ends,
        lecture_date=day,
    )


def _generate(inp: ScheduleInput) -> None:
    """Lecture items for opted-in subjects, then one revision item per exam milestone."""
    horizon = inp.horizon_end
    for area in inp.areas:
        if not area.lecture_items:
            continue
        # Every class since tracking started gets an item, past ones included: a lecture
        # only disappears once it is marked done. Older ones come from pending_lectures.
        since = inp.tracking_since or inp.now
        lectures = [(d, _lecture_item(area, d, None)) for d in area.pending_lectures]
        day = since.date()
        while datetime.combine(day, time.min) < horizon:
            for w in area.classes_on(day):
                start, end = w.on(day)
                if end > since and end <= horizon:
                    lectures.append((day, _lecture_item(area, day, end)))
            day += timedelta(days=1)
        # Deleted lectures are dropped; the rest are studied in date order: each depends
        # on the previous one.
        lectures = [(d, i) for d, i in lectures if not area.lecture_overrides.get(d, {}).get("deleted")]
        ordered = [item for _, item in sorted(lectures, key=lambda x: x[0])]
        for prev, item in zip(ordered, ordered[1:]):
            item.depends_on.append(Dependency(on=prev.id))
        area.items = ordered + area.items

    for area in inp.areas:
        for m in area.milestones:
            if m.revision_min <= 0:
                continue
            feeds = [i for i in area.items if i.counts_toward is m]
            area.items.append(Item(
                id=f"{m.id}/revision",
                title=f"Revise for {m.title}",
                area=area.name,
                estimate_min=m.revision_min,
                is_work=area.kind.is_work,
                counts_toward=m,
                available_from=m.at - timedelta(days=m.revision_days),
                depends_on=[Dependency(on=i.id, hard=False) for i in feeds],
                is_revision=True,
            ))


def _resolve_dependencies(inp: ScheduleInput) -> None:
    """Dependencies may name an item by id or title, within the same area. Rejects cycles."""
    for area in inp.areas:
        ids = {i.id for i in area.items}
        by_title = {i.title: i.id for i in area.items}
        for item in area.items:
            for dep in item.depends_on:
                if dep.on not in ids:
                    if dep.on not in by_title:
                        raise InputError(f"{area.name} / {item.title}: depends on unknown item {dep.on!r}")
                    dep.on = by_title[dep.on]

        graph = {i.id: [d.on for d in i.depends_on] for i in area.items}
        state: dict[str, int] = {}  # 1 = visiting, 2 = done

        def visit(node: str, path: list[str]) -> None:
            if state.get(node) == 2:
                return
            if state.get(node) == 1:
                raise InputError(f"{area.name}: dependency cycle {' -> '.join(path + [node])}")
            state[node] = 1
            for nxt in graph[node]:
                visit(nxt, path + [node])
            state[node] = 2

        for node in graph:
            visit(node, [])


def _chain_revisions(inp: ScheduleInput) -> None:
    """Exams are revised in exam order: each revision softly depends on the one for the
    previous exam, across subjects."""
    revisions = sorted((i for i in inp.items if i.is_revision), key=lambda i: i.counts_toward.at)
    for prev, item in zip(revisions, revisions[1:]):
        item.depends_on.append(Dependency(on=prev.id, hard=False))


def load_input(path: str | Path, now: datetime | None = None,
               progress: str | Path | None = None) -> ScheduleInput:
    """`now` defaults to the input's "now" if it has one, else the real clock. `progress` is
    the progress log to apply (see scheduler/progress.py)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    names = [a["name"] for a in raw.get("areas", [])]
    if len(names) != len(set(names)):
        raise InputError("area names must be unique")
    if now is None:
        now = datetime.fromisoformat(raw["now"]) if raw.get("now") else datetime.now()
    now = now.replace(second=0, microsecond=0)
    inp = ScheduleInput(
        now=now,
        tracking_since=datetime.fromisoformat(raw["tracking_since"]) if raw.get("tracking_since") else None,
        semester=_parse_semester(raw.get("semester")),
        availability=_availability(raw),
        commitments=[_parse_commitment(c) for c in raw.get("commitments", [])],
        areas=[_parse_area(a) for a in raw.get("areas", [])],
        settings=_parse_settings(raw["settings"]),
    )
    for area in inp.areas:  # same rule as setup_file.write, which saves them
        if not area.color:
            area.color = next_color([a.color for a in inp.areas if a.color])
    _generate(inp)
    _resolve_dependencies(inp)
    _chain_revisions(inp)
    ids = [i.id for i in inp.items] + [w.id for w in inp.activities]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise InputError(f"duplicate ids {sorted(dupes)}; give the items an explicit id")
    if progress is not None:
        for warning in apply_progress(inp, read_log(progress)):
            print(f"warning: {warning}")
    return inp
