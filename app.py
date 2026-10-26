"""HeadStart web UI: python app.py, then open http://localhost:5000

A small Flask server around the scheduler. The page (static/index.html) asks for the plan,
logs sessions, marks tasks done and adds tasks; every change re-plans and returns the new
plan. Everything runs locally.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, has_request_context, jsonify, request, send_from_directory

from plan import DEFAULT_INPUT, DEFAULT_OUTPUT, DEFAULT_PROGRESS
from scheduler import InputError, load_input
from scheduler import insights, planners, setup_file
from scheduler.engine import Plan, solve
from scheduler.load import END_OF_DAY, next_milestone
from scheduler.models import TASK_TYPES, Item, ScheduleInput, display_title, round_up_to_slot
from scheduler.progress import append, daily, drop, entry, planned_session_min, read_log, take_back, today
from scheduler.report import _reason, read_previous, deadline_status, next_session, problems, to_json, to_text, weekly_status

app = Flask(__name__, static_folder="static")
# hosted: the online site, with a home page, the demo at /p/demo/ and published planners (see
# scheduler/planners.py); otherwise the single planner in data/ on this computer.
CONFIG = {"input": DEFAULT_INPUT, "progress": DEFAULT_PROGRESS, "now": None, "lan": False, "port": 5000,
          "hosted": False, "planners": "planners"}
LOCK = threading.Lock()  # one solve at a time
CACHE: dict = {}  # setup file -> last plan


def _now() -> datetime | None:
    return CONFIG["now"]


def _planner() -> str | None:
    """The hosted planner this request is for, if any."""
    return getattr(g, "planner", None) if has_request_context() else None


def _path(kind: str) -> str:
    """The setup ("input"), progress log or saved plan ("output") of the current planner."""
    if _planner():
        return g.paths[kind]
    return {"input": CONFIG["input"], "progress": CONFIG["progress"], "output": DEFAULT_OUTPUT}[kind]


def _load() -> ScheduleInput:
    return load_input(_path("input"), now=_now(), progress=_path("progress"))


def _key() -> tuple:
    return tuple(Path(p).stat().st_mtime if Path(p).exists() else 0
                 for p in (_path("input"), _path("progress")))


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _payload(inp: ScheduleInput, plan: Plan) -> dict:
    """Everything the page needs to draw the plan."""
    days = inp.days()
    blocks = [{"title": b.title, "kind": b.kind, "start": b.start.isoformat(), "end": b.end.isoformat(),
               "work": b.is_work, "ref": b.ref}
              for d in days for b in inp.blocks_on(d)]
    # The week view spans every slot and fixed block, e.g. 07:00-24:00 for a night owl.
    spans = [(w.start_min, w.end_min) for d in days for w in inp.slots_on(d)]
    for d in days:
        for b in inp.blocks_on(d):
            if b.kind != "commitment" or b.is_work:
                s = b.start.hour * 60 + b.start.minute
                spans.append((s, s + int((b.end - b.start).total_seconds() // 60)))
    day_rows = []
    for d in days:
        mine = [s for s in plan.sessions if s.start.date() == d]
        day_rows.append({"date": d.isoformat(),
                         "work_min": sum(s.minutes for s in mine if s.is_work) + inp.fixed_work_min_on(d),
                         "max_work_min": inp.max_work_on(d)})
    nxt = next_session(plan, inp.now, inp)
    sem = inp.semester
    weeks = sem.week_of(inp.now.date()) if sem else None
    return {
        "now": inp.now.isoformat(),
        "semester": {"name": sem.name, "week": weeks[0] if weeks else None,
                     "weeks": weeks[1] if weeks else None} if sem else None,
        "status": plan.status,
        "day_start": _hhmm(min((s for s, _ in spans), default=8 * 60)),
        "day_end": _hhmm(max((e for _, e in spans), default=23 * 60 + 30)),
        "areas": [{"name": a.name, "kind": a.kind.value, "color": a.color} for a in inp.areas],
        "days": day_rows,
        "sessions": [{"kind": s.kind, "id": s.ref_id, "title": s.title, "area": s.area,
                      "start": s.start.isoformat(), "end": s.end.isoformat(), "work": s.is_work,
                      "number": s.number} for s in plan.sessions],
        "blocks": blocks,
        "events": [{"ref": n, "title": c.title, "date": c.date.isoformat() if c.date else None,
                    "days": c.days, "start": c.window.start.strftime("%H:%M"),
                    "end": "24:00" if c.window.end_min == 24 * 60 else c.window.end.strftime("%H:%M"),
                    "work": c.work} for n, c in enumerate(inp.commitments)],
        "focus": [{"area": a, "start": s.isoformat(), "end": e.isoformat()} for s, e, a in inp.focus_windows()],
        "next": {"id": nxt.ref_id, "kind": nxt.kind, "title": nxt.title, "start": nxt.start.isoformat(),
                 "end": nxt.end.isoformat(), "reason": _reason(inp, nxt)} if nxt else None,
        "activities": {a.id: {"title": a.title, "area": a.area, "fixed": a.is_fixed,
                              "sessions_per_week": a.sessions_per_week,
                              "session_hr": a.session_min / 60 if a.session_min else None,
                              "weekly_hr": a.weekly_min / 60 if a.weekly_min else None}
                       for a in inp.activities},
        "items": {i.id: {"title": display_title(i.title, i.area), "area": i.area, "left_min": i.estimate_min,
                         "done": i.done, "sessions_logged": i.sessions_logged,
                         "finish_by": i.finish_by.isoformat() if i.finish_by else None,
                         "editable": True} for i in inp.items},
        "deadlines": deadline_status(inp, plan),
        "weekly": weekly_status(inp, plan),
        "problems": problems(inp, plan),
        "today": today(inp, read_log(_path("progress"))),
        # A planner without a semester shows the first screen; the demo has a Reset button.
        "needs_setup": sem is None,
        "hosted": CONFIG["hosted"],
        "demo": _planner() == planners.DEMO,
    }


def _replan(force: bool = False) -> dict:
    """Solve (or reuse the last plan if nothing changed in the last 10 minutes)."""
    with LOCK:
        key, cache = _key(), CACHE.setdefault(_path("input"), {})
        fresh = cache.get("key") == key and (datetime.now() - cache["at"]).total_seconds() < 600
        if fresh and not force and _now() is None:
            return cache["payload"]
        inp = _load()
        plan = solve(inp, previous=read_previous(_path("output")))
        # Keep out/plan.json and out/plan.txt in step, as status.py does.
        out = Path(_path("output"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(to_json(inp, plan), indent=2), encoding="utf-8")
        out.with_suffix(".txt").write_text(to_text(inp, plan) + "\n", encoding="utf-8")
        payload = _payload(inp, plan)
        cache.update(key=_key(), at=datetime.now(), payload=payload)
        return payload


def _target(inp: ScheduleInput, target_id: str):
    for t in inp.items + inp.activities:
        if t.id == target_id:
            return t
    raise KeyError(target_id)


def _error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# --------------------------------------------------------------------------- planners


class PlannerPaths:
    """On the hosted site, /p/<id>/... is that planner's copy of the app: the request goes
    on as /... with the planner id kept aside, so every route works on its files."""

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if CONFIG["hosted"] and path.startswith("/p/"):
            pid, _, rest = path[3:].partition("/")
            if not _:  # /p/<id> -> /p/<id>/, so the page's relative links work
                start_response("301 Moved Permanently", [("Location", f"/p/{pid}/")])
                return [b""]
            environ["headstart.planner"] = pid
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + f"/p/{pid}"
            environ["PATH_INFO"] = "/" + rest
        return self.wsgi(environ, start_response)


app.wsgi_app = PlannerPaths(app.wsgi_app)


@app.before_request
def pick_planner():
    if not CONFIG["hosted"]:
        return None
    pid = request.environ.get("headstart.planner")
    if pid is None:  # the home page, and publish.py's route
        if request.path in ("/", "/api/publish"):
            return None
        return _error("not found", 404)
    d = planners.folder(CONFIG["planners"], pid)
    if d is None:
        return _error("no planner at this link; try the demo from the home page", 404)
    g.planner, g.paths = pid, planners.paths(d)
    return None


@app.post("/api/publish")
def publish():
    """Copy a planner from someone's computer (publish.py) to the site, to show it online:
    {id, setup, progress}, with the site's publish token in X-Publish-Token. The token is
    the PUBLISH_TOKEN secret; without it, publishing is off."""
    token = os.environ.get("PUBLISH_TOKEN", "")
    if not (CONFIG["hosted"] and token and hmac.compare_digest(request.headers.get("X-Publish-Token", ""), token)):
        return _error("not allowed", 403)
    body = request.get_json()
    pid = body.get("id", "")
    if not planners.ID.match(pid) or pid == planners.DEMO:
        return _error("bad planner id")
    with LOCK:
        d = planners.publish(CONFIG["planners"], pid, body["setup"], body["progress"])
        CACHE.pop(planners.paths(d)["input"], None)
    return jsonify({"url": f"/p/{pid}/"})


@app.post("/api/reset")
def reset_demo():
    """The demo only: wipe it back to the blank first screen."""
    if _planner() != planners.DEMO:
        return _error("only the demo can be reset")
    with LOCK:
        planners.reset(CONFIG["planners"], _now())
        CACHE.pop(_path("input"), None)
    return jsonify(_replan(force=True))


@app.post("/api/semester")
def set_semester():
    """The first screen: {name, start, end}."""
    body = request.get_json()
    name, start, end = (body.get("name") or "").strip(), body.get("start"), body.get("end")
    if not (start and end and start < end):
        return _error("give the semester's start and end dates, the end after the start")

    def change(data):
        data["semester"] = {"name": name, "start": start, "end": end} if name else {"start": start, "end": end}
    return _change_setup(change)


# --------------------------------------------------------------------------- routes


@app.get("/")
def index():
    if CONFIG["hosted"] and not _planner():
        return send_from_directory(app.static_folder, "home.html")
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/plan")
def get_plan():
    return jsonify(_replan(force=request.args.get("force") == "1"))


@app.post("/api/session")
def log_session():
    """A session is done: {id, spent_hr?, left_hr?}. left_hr 0 finishes the task."""
    body = request.get_json()
    inp = _load()
    try:
        target = _target(inp, body["id"])
    except KeyError:
        return _error("unknown task")
    spent = body.get("spent_hr")
    if spent is None and isinstance(target, Item):
        planned = planned_session_min(_path("output"), target.id)
        spent = planned / 60 if planned else None
    left = body.get("left_hr")
    e = entry(inp.now, target, "session", spent, None if left is None else float(left))
    append(_path("progress"), e)
    return jsonify({**_replan(force=True), "logged": [e]})


@app.post("/api/done")
def mark_done():
    """Tasks finished (e.g. lectures ticked on a subject page): {ids: [...], spent_hr?: {id: hr}}.
    spent_hr is the time put in that wasn't logged as a session, so it counts toward today."""
    body = request.get_json()
    inp = _load()
    spent = body.get("spent_hr") or {}
    try:
        logged = [entry(inp.now, _target(inp, t), "done", float(spent[t]) if spent.get(t) else None)
                  for t in body["ids"]]
    except KeyError as e:
        return _error(f"unknown task {e}")
    for e in logged:
        append(_path("progress"), e)
    return jsonify({**_replan(force=True), "logged": logged})


@app.post("/api/undo")
def undo():
    """Take back entries that were just logged: {entries: [...]} as returned by the action."""
    if not take_back(_path("progress"), request.get_json()["entries"]):
        return _error("nothing to undo (already undone?)")
    return jsonify(_replan(force=True))


@app.post("/api/reopen")
def reopen():
    """A finished task isn't finished after all: {id, left_hr}."""
    body = request.get_json()
    inp = _load()
    try:
        target = _target(inp, body["id"])
    except KeyError:
        return _error("unknown task")
    e = entry(inp.now, target, "reopen", left_hr=float(body["left_hr"]))
    append(_path("progress"), e)
    return jsonify({**_replan(force=True), "logged": [e]})


@app.post("/api/tasks")
def add_task():
    """A new task: {area, title, type (study|assignment|other), estimate_hr, due?,
    counts_toward?, new_area?: {name, kind}}.
    With new_area, that subject/lab/other area is created first."""
    body = request.get_json()
    title = (body.get("title") or "").strip()
    if not title:
        return _error("give the task a title")
    item = {"title": title, "type": body.get("type") or "other", "estimate_hr": float(body["estimate_hr"])}
    if item["type"] not in TASK_TYPES:
        return _error("pick a type: study, assignment or other")
    if body.get("due"):
        item["due"] = body["due"]
    if body.get("counts_toward"):
        item["counts_toward"] = body["counts_toward"]
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        new = body.get("new_area")
        if new:
            name = (new.get("name") or "").strip()
            if not name:
                raise ValueError("give the new subject a name")
            setup_file.add_area(data, name, new.get("kind", "subject"))
            body["area"] = name
        setup_file.add_item(data, body["area"], item)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    return jsonify(_replan(force=True))


def _exam(body: dict, old_date: str | None = None) -> dict:
    """An exam's title, date, time and syllabus end from the page's form. A date already
    past is refused (usually a mistyped year), unless it is the exam's current date."""
    title = (body.get("title") or "").strip()
    if not title or not body.get("date"):
        raise ValueError("give the exam a title and a date")
    if body["date"] != old_date and body["date"] < (_now() or datetime.now()).date().isoformat():
        raise ValueError(f"{body['date']} is already past; check the year")
    exam = {"title": title, "date": body["date"]}
    if body.get("start") or body.get("end"):
        if not (body.get("start") and body.get("end") and body["start"] < body["end"]):
            raise ValueError("give both a start and an end time, the end after the start, or neither")
        exam["time"] = [body["start"], body["end"]]
    exam["syllabus_until"] = body.get("syllabus_until") or None
    return exam


@app.post("/api/exams")
def add_exam():
    """A new exam or quiz: {area, title, date, start?, end?, revision_hr?, syllabus_until?, quiz?}."""
    body = request.get_json()
    try:
        exam = _exam(body)
    except ValueError as e:
        return _error(str(e))
    if not exam["syllabus_until"]:
        del exam["syllabus_until"]
    exam["revision_hr"] = float(body.get("revision_hr") or 0)
    if body.get("quiz"):
        exam["type"] = "quiz"
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        setup_file.add_milestone(data, body["area"], exam)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    return jsonify(_replan(force=True))


@app.post("/api/exams/edit")
def edit_exam():
    """Change an exam: {area, id, title, date, start?, end?, syllabus_until?}. It keeps its
    id, so the tasks for it stay with it; revision hours are changed on its revision task."""
    body = request.get_json()

    def change(data):
        m = setup_file.milestone(data, body["area"], body["id"])
        new = _exam(body, old_date=str(m["date"])[:10])
        m.pop("time", None)
        m.update(new)
        if not m["syllabus_until"]:
            del m["syllabus_until"]
    return _change_setup(change)


@app.post("/api/edit")
def edit_task():
    """Change a task: {id, title?, left_hr?, deadline: "due"|"exam"|"none", due?,
    counts_toward?}. A lecture keeps its title; its changes are saved as a lecture override
    in the setup file. A revision item only changes its hours (the exam's revision_hr).
    New hours go into the setup file while the task has no progress yet, else into the
    progress log."""
    body = request.get_json()
    inp = _load()
    item = next((i for i in inp.items if i.id == body.get("id")), None)
    if item is None:
        return _error("that task can't be edited here")
    deadline = body.get("deadline")
    if item.is_revision:  # it stays tied to its exam
        deadline = "exam"
        body = {**body, "counts_toward": item.counts_toward.id, "title": None}
    due = body.get("due") if deadline == "due" else None
    toward = body.get("counts_toward") if deadline == "exam" else None
    if deadline == "due" and not due:
        return _error("pick a due date")
    if deadline == "exam" and not toward:
        return _error("pick an exam")
    left_min = None
    if body.get("left_hr") is not None and not item.done:
        left_min = round_up_to_slot(round(float(body["left_hr"]) * 60))
        if left_min <= 0:
            return _error("hours needed must be more than 0 (mark the task done instead)")
    hours_changed = left_min is not None and left_min != item.estimate_min
    untouched = not (item.sessions_logged or item.spent_min or item.sections
                     or item.estimate_min != item.total_min)
    hours_in_setup = hours_changed and untouched

    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        if item.is_revision:
            if hours_in_setup:
                setup_file.set_revision(data, item.area, item.counts_toward.id, round(left_min / 60, 2))
        elif item.lecture_date:
            area = inp.area(item.area)
            ends = item.available_from or datetime.combine(item.lecture_date, END_OF_DAY)
            default = next_milestone(area, item.lecture_date, ends)
            o = setup_file.lecture_override(data, item.area, item.lecture_date.isoformat())
            o.pop("due", None)
            if due:
                o["due"] = due
            if toward == (default.id if default else None):
                o.pop("counts_toward", None)
            else:
                o["counts_toward"] = toward
            if hours_in_setup:
                if left_min == area.lecture_estimate_min:
                    o.pop("estimate_hr", None)
                else:
                    o["estimate_hr"] = round(left_min / 60, 2)
            setup_file.tidy_overrides(data)
        else:
            changes = {"due": due, "counts_toward": toward}
            if body.get("type") in TASK_TYPES:
                changes["type"] = body["type"]
            title = (body.get("title") or "").strip()
            if title:
                changes["title"] = title
            if hours_in_setup:
                changes["estimate_hr"] = round(left_min / 60, 2)
            setup_file.edit_item(data, item.area, item.id, changes)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    if hours_changed and not hours_in_setup:
        append(_path("progress"), entry(inp.now, item, "adjust", left_hr=round(left_min / 60, 2)))
    return jsonify(_replan(force=True))


def _amount(body: dict) -> dict | None:
    """How much of a weekly activity, from the page's form: sessions_per_week + session_hr,
    or weekly_hr. A None value clears the other way. None if it isn't valid."""
    try:
        if body.get("weekly_hr") is not None:
            out = {"weekly_hr": float(body["weekly_hr"]), "sessions_per_week": None, "session_hr": None}
            ok = out["weekly_hr"] > 0
        else:
            out = {"sessions_per_week": int(body["sessions_per_week"]),
                   "session_hr": float(body["session_hr"]), "weekly_hr": None}
            ok = out["sessions_per_week"] > 0 and out["session_hr"] > 0
    except (KeyError, TypeError, ValueError):
        return None
    return out if ok else None


@app.post("/api/hobbies")
def add_hobby():
    """A new flexible hobby: {title, sessions_per_week + session_hr, or weekly_hr}."""
    body = request.get_json()
    title = (body.get("title") or "").strip()
    if not title:
        return _error("give the hobby a name")
    amount = _amount(body)
    if amount is None:
        return _error("give how many sessions and how long, or hours a week (more than 0)")
    activity = {"title": title, **{k: v for k, v in amount.items() if v is not None}}
    return _change_setup(lambda data: setup_file.add_hobby(data, activity))


@app.post("/api/activity")
def edit_activity():
    """Change a weekly activity: {id, title, sessions_per_week + session_hr, or weekly_hr}."""
    body = request.get_json()
    inp = _load()
    act = next((a for a in inp.activities if a.id == body.get("id")), None)
    if act is None:
        return _error("unknown activity")
    title = (body.get("title") or "").strip()
    if not title:
        return _error("give the activity a title")
    changes = {"title": title}
    if not act.is_fixed:
        amount = _amount(body)
        if amount is None:
            return _error("give how many sessions and how long, or hours a week (more than 0)")
        changes.update(amount)
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        setup_file.edit_weekly(data, act.area, act.id, changes)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    return jsonify(_replan(force=True))


@app.post("/api/delete")
def delete_task():
    """Remove a task or weekly activity that shouldn't be there (not one that was done):
    {id}. A lecture is marked deleted in its lecture override. Its progress entries go too."""
    inp = _load()
    target_id = request.get_json().get("id")
    item = next((i for i in inp.items + inp.activities if i.id == target_id), None)
    if item is None or getattr(item, "is_revision", False):
        return _error("that task can't be deleted here")
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        if not isinstance(item, Item):
            setup_file.delete_weekly(data, item.area, item.id)
        elif item.lecture_date:
            setup_file.lecture_override(data, item.area, item.lecture_date.isoformat())["deleted"] = True
        else:
            setup_file.delete_item(data, item.area, item.id)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    drop(_path("progress"), item.id)
    return jsonify(_replan(force=True))


@app.get("/api/settings")
def get_settings():
    return jsonify(setup_file.get_settings(setup_file.read(_path("input"))))


@app.post("/api/settings")
def save_settings():
    """The settings page: {semester: {name, start, end}, availability: {mon: [[start, end],
    ...], ...}, week: [{day, max_work_hr, min_work_hr}] x 7, min_session_min,
    max_session_min}. Times are HH:MM; an end of 24:00 is midnight."""
    body = request.get_json()
    try:
        week = body["week"]
        if [r["day"] for r in week] != list(setup_file.DAYS):
            raise ValueError("expected all seven days")
        for r in week:
            mx, mn = float(r["max_work_hr"]), float(r["min_work_hr"])
            if not 0 <= mn <= mx <= 24:
                raise ValueError(f"{r['day']}: study hours must be 0-24, with the minimum not above the maximum")
        for day, spans in body["availability"].items():
            if day not in setup_file.DAYS:
                raise ValueError(f"unknown day {day!r}")
            for a, b in spans:
                if not ("00:00" <= a < b <= "24:00"):
                    raise ValueError(f"{day}: bad slot {a}-{b}")
        lo, hi = int(body["min_session_min"]), int(body["max_session_min"])
        if not 10 <= lo <= hi:
            raise ValueError("the shortest session must be at least 10 min and not longer than the longest")
    except (KeyError, TypeError, ValueError) as e:
        return _error(str(e) if isinstance(e, ValueError) else "incomplete settings")
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        setup_file.set_settings(data, body)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    return jsonify(_replan(force=True))


def _change_setup(change):
    """Apply `change(data)` to the setup file, check it loads, and re-plan. On a problem
    the file is put back and the error returned."""
    path = _path("input")
    before = Path(path).read_text(encoding="utf-8")
    data = setup_file.read(path)
    try:
        change(data)
        setup_file.write(path, data)
        _load()  # validate before planning
    except (ValueError, InputError, KeyError, IndexError) as e:
        Path(path).write_text(before, encoding="utf-8")  # undo
        return _error(str(e))
    return jsonify(_replan(force=True))


def _event(body: dict) -> dict:
    """A fixed-time event (a commitment in the setup file) from the page's form."""
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("give the event a title")
    start, end = body.get("start") or "", body.get("end") or ""
    if not (start and end and start < end):
        raise ValueError("give a start and an end time, the end after the start")
    ev = {"title": title}
    if body.get("date"):
        ev["date"] = body["date"]
    elif body.get("days"):
        ev["days"] = "all" if len(body["days"]) == 7 else [d for d in setup_file.DAYS if d in body["days"]]
    else:
        raise ValueError("pick a date, or the days it repeats on")
    ev["time"] = [start, end]
    if body.get("work"):
        ev["work"] = True
    return ev


@app.post("/api/events")
def add_event():
    """A fixed-time event: {title, date | days, start, end, work?}. Nothing is planned for
    it; it just blocks its time (and with work, counts toward that day's study hours)."""
    body = request.get_json()
    try:
        ev = _event(body)
    except ValueError as e:
        return _error(str(e))
    return _change_setup(lambda data: data.setdefault("commitments", []).append(ev))


@app.post("/api/events/edit")
def edit_event():
    """Change an event: {ref, title, date | days, start, end, work?}. A repeating event keeps
    its skipped dates."""
    body = request.get_json()
    try:
        ev = _event(body)
    except ValueError as e:
        return _error(str(e))

    def change(data):
        old = data["commitments"][int(body["ref"])]
        if old.get("skip") and "days" in ev:
            ev["skip"] = old["skip"]
        data["commitments"][int(body["ref"])] = ev
    return _change_setup(change)


@app.post("/api/events/delete")
def delete_event():
    """Remove an event: {ref, only?}. With only (a date), a repeating event just skips that
    day."""
    body = request.get_json()

    def change(data):
        evs = data["commitments"]
        ev = evs[int(body["ref"])]
        if body.get("only") and not ev.get("date"):
            ev["skip"] = sorted(set(ev.get("skip", [])) | {body["only"]})
        else:
            del evs[int(body["ref"])]
            if not evs:
                del data["commitments"]
    return _change_setup(change)


@app.post("/api/classes")
def class_change():
    """A one-time timetable change: {area, action, ...}
    - cancel {date, start}: no class that day
    - move {date, start, to: [date, start, end]}: it happens at another time
    - extra {to: [date, start, end]}: a one-off makeup class
    - undo {index}: take back a change (position in the subject's timetable_changes)"""
    body = request.get_json()
    action, area = body.get("action"), body.get("area")
    to = body.get("to")
    if action in ("move", "extra") and not (to and len(to) == 3 and all(to) and to[1] < to[2]):
        return _error("give a date and a start and end time, the end after the start")

    def change(data):
        if action == "cancel":
            setup_file.cancel_class(data, area, body["date"], body["start"])
        elif action == "move":
            setup_file.move_class(data, area, body["date"], body["start"], to)
        elif action == "extra":
            setup_file.add_extra_class(data, area, to)
        elif action == "undo":
            setup_file.undo_class_change(data, area, int(body["index"]))
        else:
            raise ValueError(f"unknown action {action!r}")
    return _change_setup(change)


@app.post("/api/areas")
def add_subject():
    """A new subject: {name, kind: subject|lab|other, classes: [[day, start, end], ...],
    lectures: bool}."""
    body = request.get_json()
    name = (body.get("name") or "").strip()
    if not name:
        return _error("give the subject a name")
    return _change_setup(lambda data: setup_file.add_area(
        data, name, body.get("kind", "subject"), body.get("classes") or [], bool(body.get("lectures"))))


@app.post("/api/timetable")
def weekly_class():
    """Add or remove a class that happens every week: {area, action: add|remove, day,
    start, end?}."""
    body = request.get_json()

    def change(data):
        if body.get("action") == "add":
            setup_file.add_weekly_class(data, body["area"], body["day"], body["start"], body["end"])
        elif body.get("action") == "remove":
            setup_file.remove_weekly_class(data, body["area"], body["day"], body["start"])
        else:
            raise ValueError(f"unknown action {body.get('action')!r}")
    return _change_setup(change)


@app.post("/api/lectures")
def lectures():
    """Turn a subject's lecture items on or off: {area, on}."""
    body = request.get_json()
    return _change_setup(lambda data: setup_file.set_lectures(data, body.get("area"), bool(body.get("on"))))


@app.get("/api/subjects")
def subjects():
    """Every subject with its exams, its weekly study and all its tasks, done ones included.
    Hobby areas are left out."""
    inp = _load()
    raw = {a["name"]: a for a in setup_file.read(_path("input"))["areas"]}
    out = []
    for a in inp.areas:
        if a.kind.value == "hobby":
            continue
        out.append({
            "name": a.name, "kind": a.kind.value,
            "timetable": [{"day": wd, "start": w.start.strftime("%H:%M"), "end": w.end.strftime("%H:%M")}
                          for wd, w in a.timetable],
            "class_changes": raw[a.name].get("timetable_changes", []),
            "lecture_items": a.lecture_items,
            "weekly": [{"id": w.id, "title": w.title, "fixed": w.is_fixed,
                        "sessions_per_week": w.sessions_per_week, "session_min": w.session_min,
                        "weekly_min": w.weekly_min} for w in a.weekly],
            "milestones": [{"id": m.id, "title": m.title, "at": m.at.isoformat(), "quiz": m.quiz,
                            "start": m.end and m.at.strftime("%H:%M"),
                            "end": m.end and m.end.strftime("%H:%M"),
                            "syllabus_until": m.syllabus_until and m.syllabus_until.isoformat()}
                           for m in a.milestones],
            "items": [{"id": i.id, "title": display_title(i.title, i.area), "raw_title": i.title,
                       "left_min": i.estimate_min,
                       "done": i.done, "sessions_logged": i.sessions_logged,
                       "spent_min": i.spent_min, "total_min": i.total_min,
                       "lecture": i.lecture_date is not None, "revision": i.is_revision,
                       "finish_by": i.finish_by.isoformat() if i.finish_by else None,
                       "due": i.due.date().isoformat() if i.due else None,
                       "toward": i.counts_toward.title if i.counts_toward else None,
                       "toward_id": i.counts_toward.id if i.counts_toward else None,
                       "type": i.task_type}
                      for i in a.items],
        })
    return jsonify(out)


@app.get("/api/insights")
def get_insights():
    """For the Stats page: the effort put into each exam, and when you study
    (see scheduler/insights.py)."""
    inp = _load()
    return jsonify({"exams": insights.exam_effort(inp),
                    "times": insights.study_times(inp, read_log(_path("progress")))})


def _lan_ip() -> str | None:
    """This computer's address on its Wi-Fi or wired network, e.g. 192.168.1.5. Nothing
    is sent: connecting a UDP socket only picks the outgoing interface."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            ip = sk.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


@app.get("/api/phone")
def phone():
    """The link (and its QR code, as SVG) to open this planner on a phone on the same
    network. Only when the app runs with --lan."""
    ip = _lan_ip() if CONFIG["lan"] and not CONFIG["hosted"] else None
    if not ip:
        return jsonify({"url": None, "lan": CONFIG["lan"]})
    import io
    import qrcode
    import qrcode.image.svg
    url = f"http://{ip}:{CONFIG['port']}/"
    buf = io.BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2).save(buf)
    return jsonify({"url": url, "lan": True, "qr": buf.getvalue().decode()})


@app.get("/api/stats")
def stats():
    """Each day from the first logged one up to today: minutes studied, sessions, tasks done
    and that day's minimum study (0 = no target), plus the current and best study streaks
    (days in a row with some study; a streak still counts while today has none yet)."""
    inp = _load()
    done = daily(inp, read_log(_path("progress")))
    today_ = inp.now.date()
    first = min(done, default=today_)
    days, run, best = [], 0, 0
    for n in range((today_ - first).days + 1):
        day = first + timedelta(days=n)
        d = done.get(day, {"study_min": 0, "sessions": 0, "tasks_done": 0})
        days.append({"date": day.isoformat(), **d, "min_min": inp.min_work_on(day)})
        run = run + 1 if d["study_min"] else 0
        best = max(best, run)
    current = 0  # if today has nothing yet, the streak up to yesterday is still alive
    for d in reversed(days if days[-1]["study_min"] else days[:-1]):
        if not d["study_min"]:
            break
        current += 1
    return jsonify({"days": days, "streak": current, "best_streak": best})


def main() -> None:
    ap = argparse.ArgumentParser(description="HeadStart web UI")
    ap.add_argument("--now", type=datetime.fromisoformat, help="pretend it is this time (demo/testing)")
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--progress", default=DEFAULT_PROGRESS)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    ap.add_argument("--hosted", action="store_true", default=bool(os.environ.get("HEADSTART_HOSTED")),
                    help="the online site: home page and separate planners under /p/<id>/")
    ap.add_argument("--lan", action="store_true",
                    help="also serve on this computer's network, to open it on a phone on the same Wi-Fi")
    ap.add_argument("--planners", default=os.environ.get("HEADSTART_PLANNERS", "planners"),
                    help="folder holding the hosted planners")
    args = ap.parse_args()
    CONFIG.update(input=args.input, progress=args.progress, now=args.now,
                  hosted=args.hosted, planners=args.planners, lan=args.lan, port=args.port)
    if args.hosted:
        Path(args.planners).mkdir(parents=True, exist_ok=True)
        dataset = os.environ.get("HEADSTART_DATASET")
        if dataset:  # keep published planners (only those) in a private dataset
            from scheduler import sync
            kept = Path(args.planners) / planners.KEPT
            kept.mkdir(parents=True, exist_ok=True)
            sync.restore(kept, dataset)
            sync.keep(kept, dataset)
            print(f"HeadStart: published planners kept in dataset {dataset}")
        print(f"HeadStart (hosted): open http://localhost:{args.port}")
        from waitress import serve
        serve(app, host="0.0.0.0", port=args.port, threads=8)
        return
    if not Path(args.input).exists():  # a fresh download: start on the first screen
        Path(args.input).parent.mkdir(parents=True, exist_ok=True)
        setup_file.write(args.input, planners.starter(args.now))
        Path(args.progress).write_text("[]\n", encoding="utf-8")
    threading.Thread(target=_replan, daemon=True).start()  # warm up the first plan
    print(f"HeadStart: open http://localhost:{args.port}")
    if args.lan:
        ip = _lan_ip()
        print(f"HeadStart: on your phone (same Wi-Fi): http://{ip}:{args.port}" if ip
              else "HeadStart: no network found for --lan; only this computer can open it")
    app.run(host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
