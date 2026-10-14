"""Turn a Plan into the text printout and JSON output (see spec.md, "Output")."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .engine import Plan, Session, build_flex
from .models import Item, Milestone, ScheduleInput, display_title, week_start


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def _fmt(dt: datetime) -> str:
    return f"{dt:%a %d %b %H:%M}"


def next_session(plan: Plan, now: datetime, inp: ScheduleInput | None = None) -> Session | None:
    """The next planned session, or fixed study time (like ICPC practice) if that comes
    first. Fixed blocks show as kind "fixed": there is nothing to log for them."""
    planned = next((s for s in plan.sessions if s.end > now), None)
    if inp is None:
        return planned
    fixed = [Session("fixed", "", b.title, "", b.start, b.end, True)
             for d in inp.days() for b in inp.blocks_on(d) if b.is_work and b.end > now]
    return min([s for s in [planned] + fixed if s], key=lambda s: s.start, default=None)


def _item(inp: ScheduleInput, item_id: str) -> Item:
    return next(i for i in inp.items if i.id == item_id)


def _reason(inp: ScheduleInput, s: Session) -> str:
    if s.kind == "fixed":
        return "fixed in your schedule"
    if s.kind == "activity":
        return "your weekly target"
    item = _item(inp, s.ref_id)
    if item.finish_by is None:
        return "no deadline yet, so you get ahead"
    days = (item.finish_by.date() - s.start.date()).days
    what = item.counts_toward.title if item.counts_toward and item.finish_by == item.counts_toward.at \
        else f"{display_title(item.title, item.area)} is due"
    return f"{what} in {days} day{'s' if days != 1 else ''}"


def _planned(plan: Plan, item_id: str) -> tuple[int, datetime | None]:
    mine = [s for s in plan.sessions if s.ref_id == item_id]
    return sum(s.minutes for s in mine), max((s.end for s in mine), default=None)


def deadline_status(inp: ScheduleInput, plan: Plan) -> list[dict]:
    """One row per milestone, plus one per item that has its own due date."""
    groups: list[tuple[str, str, str, datetime, list[Item]]] = []
    for m in sorted(inp.milestones, key=lambda m: m.at):
        groups.append(("exam", m.title, m.area, m.at, [i for i in inp.items if i.counts_toward is m]))
    for i in inp.items:
        if i.due and not (i.counts_toward and i.counts_toward.at <= i.due):
            groups.append(("due", display_title(i.title, i.area), i.area, i.due, [i]))
    rows = []
    for kind, title, area, at, items in sorted(groups, key=lambda g: g[3]):
        if at <= inp.now:  # already happened
            continue
        needed = sum(i.estimate_min for i in items)
        planned, finish = 0, None
        for i in items:
            mins, end = _planned(plan, i.id)
            planned += mins
            finish = max(filter(None, [finish, end]), default=None)
        lead = (at - finish) if finish else None
        rows.append({
            "kind": kind,
            "title": title,
            "area": area,
            "date": at.isoformat(),
            "items": len(items),
            "items_done": sum(i.done for i in items),
            "needed_min": needed,
            "planned_min": planned,
            "planned_finish": finish.isoformat() if finish else None,
            "lead_hr": round(lead.total_seconds() / 3600, 1) if lead is not None else None,
        })
    return rows


def weekly_status(inp: ScheduleInput, plan: Plan) -> list[dict]:
    rows = []
    for f in build_flex(inp):
        for wk, left in sorted(f.targets.items()):
            got = sum(s.minutes for s in plan.sessions
                      if s.ref_id == f.act.id and week_start(s.start.date()) == wk)
            _, done = inp.activity_done_min(f.act.id, wk)
            rows.append({"id": f.act.id, "activity": f.act.title, "week": wk.isoformat(), "done_min": done,
                         "planned_min": got, "target_min": left * 10 + done})
    return rows


def read_previous(plan_json: str | Path) -> list[tuple[str, datetime, datetime]] | None:
    """The sessions of the last saved plan (task id, start, end), which a re-plan keeps
    close to. None if there is no saved plan."""
    p = Path(plan_json)
    if not p.exists():
        return None
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))["sessions"]
        return [(r["id"], datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]
    except (ValueError, KeyError):
        return None


def problems(inp: ScheduleInput, plan: Plan) -> list[str]:
    titles = {i.id: display_title(i.title, i.area) for i in inp.items}
    no_deadline = {i.id for i in inp.items if i.finish_by is None}
    out = []
    for iid, mins in plan.unscheduled_min.items():
        if iid in no_deadline:  # it only ran past the end of the plan; it gets planned later
            continue
        out.append(f"{titles.get(iid, iid)}: {hm(mins)} doesn't fit before its deadline. "
                   f"Options: raise the day's max, move a commitment, or reduce the work.")
    for pre, dep in plan.broken_soft:
        out.append(f"{titles[dep]} starts before {titles[pre]} is finished, to keep deadlines.")
    for (aid, wk), mins in plan.short_weekly_min.items():
        act = next(a for a in inp.activities if a.id == aid)
        out.append(f"{act.title}: {hm(mins)} short of the target in the week of {wk:%d %b}.")
    # A day short of its work minimum isn't listed: the plan already fills the minimum wherever
    # it can, so a short day just means nothing more is available yet (e.g. you're ahead).
    return out


def to_text(inp: ScheduleInput, plan: Plan) -> str:
    lines = [f"Solver: {plan.status}", ""]

    nxt = next_session(plan, inp.now, inp)
    if nxt:
        when = "Now" if nxt.start <= inp.now else f"Next ({nxt.start:%a %H:%M})"
        lines += [f"{when}: {nxt.title}, {nxt.start:%H:%M}-{nxt.end:%H:%M}. Why: {_reason(inp, nxt)}.", ""]

    by_day: dict[date, list[Session]] = defaultdict(list)
    for s in plan.sessions:
        by_day[s.start.date()].append(s)
    for d in inp.days():
        shown = [b for b in inp.blocks_on(d)
                 if (b.kind in ("class", "exam") or b.is_work) and b.end > inp.now]
        if d not in by_day and not any(b.kind == "exam" or b.is_work for b in shown):
            continue
        rows = [(s.start, s.end, s.title) for s in by_day[d]]
        rows += [(b.start, b.end, f"[{b.title} class]" if b.kind == "class" else f"[{b.title}]")
                 for b in shown]
        lines.append(f"{d:%a %d %b}")
        for start, end, title in sorted(rows):
            lines.append(f"  {start:%H:%M}-{end:%H:%M}  {title}")
        work = sum(s.minutes for s in by_day[d] if s.is_work) + inp.fixed_work_min_on(d)
        other = sum(s.minutes for s in by_day[d] if not s.is_work)
        lines.append(f"  = work {hm(work)} (max {hm(inp.max_work_on(d))}), hobby {hm(other)}")
    lines.append("")

    lines.append("Deadlines")
    for r in deadline_status(inp, plan):
        finish = _fmt(datetime.fromisoformat(r["planned_finish"])) if r["planned_finish"] else "-"
        lead = f"{r['lead_hr']} hr ahead" if r["lead_hr"] is not None else ""
        lines.append(f"  {r['title']:<22} {datetime.fromisoformat(r['date']):%a %d %b}: "
                     f"{r['items_done']}/{r['items']} done, {hm(r['planned_min'])} / "
                     f"{hm(r['needed_min'])} left planned, ready by {finish}, {lead}")
    lines.append("")

    lines.append("Weekly")
    for r in weekly_status(inp, plan):
        done = f"{hm(r['done_min'])} done + " if r["done_min"] else ""
        lines.append(f"  {r['activity']:<12} week of {date.fromisoformat(r['week']):%d %b}: "
                     f"{done}{hm(r['planned_min'])} planned / {hm(r['target_min'])}")
    lines.append("")

    probs = problems(inp, plan)
    lines.append("Problems" if probs else "Problems: none, everything fits.")
    lines += [f"  - {p}" for p in probs]
    return "\n".join(lines)


def to_json(inp: ScheduleInput, plan: Plan) -> dict:
    nxt = next_session(plan, inp.now, inp)
    return {
        "status": plan.status,
        "generated_for": inp.now.isoformat(),
        "next": {"title": nxt.title, "start": nxt.start.isoformat(), "end": nxt.end.isoformat(),
                 "reason": _reason(inp, nxt)} if nxt else None,
        "sessions": [{"kind": s.kind, "id": s.ref_id, "title": s.title, "area": s.area,
                      "start": s.start.isoformat(), "end": s.end.isoformat(), "work": s.is_work}
                     for s in plan.sessions],
        "deadlines": deadline_status(inp, plan),
        "weekly": weekly_status(inp, plan),
        "problems": problems(inp, plan),
    }
