"""Changes to the setup file (data/sem5.json) made from the UI, written back in the same
compact style as the hand-written file: anything short stays on one line."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import next_color

WIDTH = 100


def dumps(obj, indent: int = 0) -> str:
    flat = json.dumps(obj, ensure_ascii=False)
    if indent + len(flat) <= WIDTH or not isinstance(obj, (dict, list)) or not obj:
        return flat
    pad, inner = " " * indent, " " * (indent + 2)
    if isinstance(obj, dict):
        rows = [f"{inner}{json.dumps(k)}: {dumps(v, indent + 2).lstrip()}" for k, v in obj.items()]
        return "{\n" + ",\n".join(rows) + f"\n{pad}}}"
    rows = [inner + dumps(v, indent + 2) for v in obj]
    return "[\n" + ",\n".join(rows) + f"\n{pad}]"


def read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: str | Path, data: dict) -> None:
    """Save the setup. Every area gets a colour kept in the file, so it never changes."""
    for a in data.get("areas", []):
        if not a.get("color"):
            a["color"] = next_color([x["color"] for x in data["areas"] if x.get("color")])
    Path(path).write_text(dumps(data) + "\n", encoding="utf-8")


KINDS = ("subject", "lab", "other")


def add_area(data: dict, name: str, kind: str, timetable: list | None = None,
             lectures: bool = False) -> None:
    """A new subject, lab or 'other' area, with its weekly classes ([day, start, end]) and,
    if `lectures`, a lecture to study after each class. Exams and tasks are added later."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if any(a["name"].lower() == name.lower() for a in data["areas"]):
        raise ValueError(f"{name!r} already exists; pick it from the list")
    data["areas"].append({"name": name, "kind": kind, "items": []})
    for day, start, end in timetable or []:
        add_weekly_class(data, name, day, start, end)
    if lectures and timetable:
        data["areas"][-1]["lecture_items"] = True


def add_hobby(data: dict, activity: dict) -> None:
    """A flexible hobby (e.g. Guitar, 3 x 1 hr a week): a hobby area of its own, named
    after it, holding one weekly activity. The plan fits its sessions into free time."""
    name = activity["title"]
    if any(a["name"].lower() == name.lower() for a in data["areas"]):
        raise ValueError(f"{name!r} already exists; edit it from the week view instead")
    data["areas"].append({"name": name, "kind": "hobby", "weekly": [activity]})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def add_milestone(data: dict, area: str, milestone: dict) -> str:
    """An exam in a subject. Gets a readable unique id (e.g. "rp-endsem"), which tasks
    use in counts_toward. Returns the id."""
    for a in data["areas"]:
        if a["name"] != area:
            continue
        taken = {m.get("id") for x in data["areas"] for m in x.get("milestones", [])}
        title = _slug(milestone["title"])
        base = title if title.startswith(_slug(area)) else f"{_slug(area)}-{title}"
        mid, n = base, 2
        while mid in taken:
            mid, n = f"{base}-{n}", n + 1
        a.setdefault("milestones", []).append({"id": mid, **milestone})
        return mid
    raise ValueError(f"no subject {area!r}")


def add_item(data: dict, area: str, item: dict) -> None:
    for a in data["areas"]:
        if a["name"] == area:
            a.setdefault("items", []).append(item)
            return
    raise ValueError(f"no subject {area!r}")


def edit_item(data: dict, area: str, item_id: str, changes: dict) -> None:
    """Change a hand-written task in place. A None value removes that key. A renamed task
    keeps its old id, so its logged progress stays with it, and tasks that depend on it by
    title follow the new title."""
    for a in data["areas"]:
        if a["name"] != area:
            continue
        items = a.get("items", [])
        for n, raw in enumerate(items):
            if (raw.get("id") or f"{_slug(area)}/{_slug(raw['title'])}") != item_id:
                continue
            old, new = raw["title"], changes.get("title")
            if new and new != old:
                if "id" not in raw:
                    raw = items[n] = {"id": item_id, **raw}
                for other in items:
                    other_deps = other.get("depends_on", [])
                    for k, d in enumerate(other_deps):
                        if d == old:
                            other_deps[k] = new
                        elif isinstance(d, dict) and d.get("on") == old:
                            d["on"] = new
            for key, value in changes.items():
                if value is None:
                    raw.pop(key, None)
                elif key == "due" and str(raw.get("due", ""))[:10] == value:
                    continue  # same day: keep a hand-written time
                else:
                    raw[key] = value
            return
    raise ValueError(f"no task {item_id!r} in {area!r}")


def lecture_override(data: dict, area: str, day: str) -> dict:
    """The override for one generated lecture (by class date), to change in place. Call
    tidy_overrides() afterwards to drop empty ones."""
    for a in data["areas"]:
        if a["name"] == area:
            return a.setdefault("lecture_overrides", {}).setdefault(day, {})
    raise ValueError(f"no subject {area!r}")


def tidy_overrides(data: dict) -> None:
    for a in data["areas"]:
        overrides = a.get("lecture_overrides")
        if overrides is None:
            continue
        for day in [d for d, o in overrides.items() if not o]:
            del overrides[day]
        if not overrides:
            del a["lecture_overrides"]


def delete_item(data: dict, area: str, item_id: str) -> None:
    """Remove a hand-written task, and any dependency on it."""
    for a in data["areas"]:
        if a["name"] != area:
            continue
        items = a.get("items", [])
        for raw in items:
            if (raw.get("id") or f"{_slug(area)}/{_slug(raw['title'])}") != item_id:
                continue
            items.remove(raw)
            names = {item_id, raw["title"]}
            for other in items:
                deps = [d for d in other.get("depends_on", [])
                        if (d if isinstance(d, str) else d.get("on")) not in names]
                if "depends_on" in other:
                    other["depends_on"] = deps
                    if not deps:
                        del other["depends_on"]
            return
    raise ValueError(f"no task {item_id!r} in {area!r}")


def _weekly(data: dict, area: str, act_id: str) -> tuple[dict, list, int]:
    """(area, its weekly list, index) of a weekly activity."""
    for a in data["areas"]:
        if a["name"] != area:
            continue
        for n, raw in enumerate(a.get("weekly", [])):
            if (raw.get("id") or f"{_slug(area)}/{_slug(raw['title'])}") == act_id:
                return a, a["weekly"], n
    raise ValueError(f"no weekly activity {act_id!r} in {area!r}")


def edit_weekly(data: dict, area: str, act_id: str, changes: dict) -> None:
    """Change a weekly activity in place. A None value removes that key. A renamed
    activity keeps its old id, so its logged sessions stay with it."""
    _, weekly, n = _weekly(data, area, act_id)
    raw = weekly[n]
    if changes.get("title") and changes["title"] != raw["title"] and "id" not in raw:
        raw = weekly[n] = {"id": act_id, **raw}
    for key, value in changes.items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value


def delete_weekly(data: dict, area: str, act_id: str) -> None:
    """Remove a weekly activity. An area left with nothing in it (e.g. Workout) goes too."""
    a, weekly, n = _weekly(data, area, act_id)
    del weekly[n]
    if not weekly:
        del a["weekly"]
    if not any(v for k, v in a.items() if k not in ("name", "kind", "weight")):
        data["areas"].remove(a)


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def availability(data: dict) -> dict[str, list[list[str]]]:
    """Study slots per weekday. An older file gives one span per day (day_bounds); its
    events stay events, since a weekly one may be a real event (frisbee), not a meal."""
    if "availability" in data:
        return {d: data["availability"].get(d, []) for d in DAYS}
    rules = data["settings"].get("weekday", {})
    out = {}
    for d in DAYS:
        b = rules.get(d, {}).get("bounds") or data.get("day_bounds", {}).get(d)
        spans = [(_mins(b[0]), _mins(b[1]))] if b else []
        out[d] = [[_hhmm(s), _hhmm(e)] for s, e in spans]
    return out


def get_settings(data: dict) -> dict:
    """The settings page: semester, study slots and each weekday's study max/min, session
    lengths, and the classes per weekday (shown on the grid)."""
    s = data["settings"]
    rules = s.get("weekday", {})
    week = []
    for d in DAYS:
        mx, mn = rules.get(d, {}).get("max_work_hr"), rules.get(d, {}).get("min_work_hr")
        week.append({"day": d, "max_work_hr": s["max_work_hr"] if mx is None else mx,
                     "min_work_hr": s.get("min_work_hr", 0) if mn is None else mn})
    classes = {d: [] for d in DAYS}
    for a in data["areas"]:
        for wd, start, end in a.get("timetable", []):
            classes[wd].append({"title": a["name"], "start": start, "end": end})
    return {"semester": data.get("semester") or {}, "availability": availability(data), "week": week,
            "classes": classes,
            "min_session_min": s.get("min_session_min", 30), "max_session_min": s.get("max_session_min", 90)}


def _per_day(s: dict, rules: dict, week: list[dict], key: str, fallback: float) -> None:
    """Each day's value for `key` (max_work_hr or min_work_hr): the current default stays
    while some day still uses it, else the most common value becomes the default; other
    days override it."""
    values = [float(r[key]) for r in week]
    default = float(s.get(key, fallback))
    if default not in values:
        default = max(sorted(set(values)), key=values.count)
    if default or key == "max_work_hr":
        s[key] = _num(default)
    else:
        s.pop(key, None)
    for r, v in zip(week, values):
        rule = rules.setdefault(r["day"], {})
        if v == default:
            rule.pop(key, None)
        else:
            rule[key] = _num(v)


def set_settings(data: dict, new: dict) -> None:
    """Write the settings page back. Study slots replace day_bounds and recurring breaks
    (an older file is converted on its first save). Other per-weekday rules are kept."""
    sem = {k: v for k, v in (new.get("semester") or {}).items() if v}
    data.pop("day_bounds", None)  # an older file: the slots replace it
    data["availability"] = {d: [list(x) for x in new["availability"].get(d, [])] for d in DAYS}
    s = data["settings"]
    rules = s.setdefault("weekday", {})
    _per_day(s, rules, new["week"], "max_work_hr", 0)
    _per_day(s, rules, new["week"], "min_work_hr", 0)
    for d in DAYS:
        rule = rules.get(d)
        if rule is not None:
            rule.pop("bounds", None)  # the day's slots say when
            if not rule:
                del rules[d]
    if rules:
        s["weekday"] = {d: rules[d] for d in DAYS if d in rules}
    else:
        del s["weekday"]
    s["min_session_min"] = int(new["min_session_min"])
    s["max_session_min"] = int(new["max_session_min"])
    # Semester and study slots at the top of the file, the rest as it was.
    rest = [(k, v) for k, v in data.items() if k not in ("semester", "tracking_since", "availability")]
    head = [(k, data[k]) for k in ("tracking_since", "availability") if k in data]
    data.clear()
    if sem:
        data["semester"] = sem
    data.update(head + rest)


def _num(x: float):
    return int(x) if x == int(x) else x


def _changes(data: dict, area: str) -> tuple[dict, list]:
    for a in data["areas"]:
        if a["name"] == area:
            return a, a.setdefault("timetable_changes", [])
    raise ValueError(f"no subject {area!r}")


def _tidy_changes(a: dict) -> None:
    if not a.get("timetable_changes"):
        a.pop("timetable_changes", None)


def _origin(changes: list, day: str, start: str) -> int | None:
    """The change that puts a class on `day` at `start` (an extra, or a move's new time),
    or None for a class from the weekly timetable."""
    for n, c in enumerate(changes):
        if "extra" in c and c["extra"][:2] == [day, start]:
            return n
        if "move" in c and c["to"][:2] == [day, start]:
            return n
    return None


def cancel_class(data: dict, area: str, day: str, start: str) -> None:
    """No class that day: a timetable class is cancelled; an extra class is removed; a
    moved class stays cancelled on its old date."""
    a, changes = _changes(data, area)
    n = _origin(changes, day, start)
    if n is None:
        changes.append({"cancel": day})
    elif "extra" in changes[n]:
        del changes[n]
    else:
        changes[n] = {"cancel": changes[n]["move"]}
    _tidy_changes(a)


def move_class(data: dict, area: str, day: str, start: str, to: list[str]) -> None:
    """The class on `day` at `start` happens at `to` ([date, start, end]) instead."""
    a, changes = _changes(data, area)
    n = _origin(changes, day, start)
    if n is None:
        changes.append({"move": day, "to": to})
    elif "extra" in changes[n]:
        changes[n] = {"extra": to}
    else:
        changes[n]["to"] = to
    _tidy_changes(a)


def add_extra_class(data: dict, area: str, extra: list[str]) -> None:
    a, changes = _changes(data, area)
    changes.append({"extra": extra})


def undo_class_change(data: dict, area: str, index: int) -> None:
    a, changes = _changes(data, area)
    del changes[index]
    _tidy_changes(a)


def set_lectures(data: dict, area: str, on: bool) -> None:
    """Turn a subject's lecture items on or off. Off drops every lecture, old ones included;
    the classes still block their time."""
    a, _ = _changes(data, area)
    _tidy_changes(a)
    if on:
        a["lecture_items"] = True
    else:
        a.pop("lecture_items", None)


def set_revision(data: dict, area: str, milestone_id: str, hours: float) -> None:
    """Change how much revision an exam gets."""
    milestone(data, area, milestone_id)["revision_hr"] = _num(hours)


def milestone(data: dict, area: str, milestone_id: str) -> dict:
    """An exam, to change in place. An exam without a written id gets its current one
    written in, so renaming it doesn't change its id and its tasks stay with it."""
    a, _ = _changes(data, area)
    _tidy_changes(a)
    ms = a.get("milestones", [])
    for n, m in enumerate(ms):
        if (m.get("id") or f"{_slug(area)}/{_slug(m['title'])}") == milestone_id:
            if "id" not in m:
                m = ms[n] = {"id": milestone_id, **m}
            return m
    raise ValueError(f"no exam {milestone_id!r} in {area!r}")


def _clash(data: dict, day: str, start: str, end: str, skip: tuple[str, int] | None = None) -> None:
    """Refuse a weekly class that overlaps another one (in any subject) on the same day."""
    for a in data["areas"]:
        for n, (d, s, e) in enumerate(a.get("timetable", [])):
            if (a["name"], n) != skip and d == day and s < end and start < e:
                raise ValueError(f"it clashes with {a['name']} on {day.title()} {s}-{e}")


def add_weekly_class(data: dict, area: str, day: str, start: str, end: str) -> None:
    """A class every week: day (mon..sun), start and end (HH:MM)."""
    if day not in DAYS:
        raise ValueError(f"unknown day {day!r}")
    if not ("00:00" <= start < end <= "24:00"):
        raise ValueError("give a start and an end time, the end after the start")
    a, _ = _changes(data, area)
    _tidy_changes(a)
    _clash(data, day, start, end)
    a.setdefault("timetable", []).append([day, start, end])
    a["timetable"].sort(key=lambda c: (DAYS.index(c[0]), c[1]))


def remove_weekly_class(data: dict, area: str, day: str, start: str) -> None:
    a, _ = _changes(data, area)
    _tidy_changes(a)
    tt = a.get("timetable", [])
    for n, (d, s, _e) in enumerate(tt):
        if d == day and s == start:
            del tt[n]
            if not tt:
                del a["timetable"]
            return
    raise ValueError(f"no {area} class on {day.title()} at {start}")


def delete_milestone(data: dict, area: str, milestone_id: str) -> None:
    """Remove an exam. Tasks that counted toward it keep everything but that link (a task
    without its own due date then has no deadline); lecture overrides pointing to it go,
    so those lectures count toward the next exam like any other. Its revision goes with
    it; logged revision sessions stay in the log, unused."""
    milestone(data, area, milestone_id)  # it exists (and has its id written in)
    a, _ = _changes(data, area)
    _tidy_changes(a)
    a["milestones"] = [m for m in a["milestones"] if m.get("id") != milestone_id]
    if not a["milestones"]:
        del a["milestones"]
    for item in a.get("items", []):
        if item.get("counts_toward") == milestone_id:
            del item["counts_toward"]
    for o in a.get("lecture_overrides", {}).values():
        if o.get("counts_toward") == milestone_id:
            del o["counts_toward"]
    tidy_overrides(data)
