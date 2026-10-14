"""Two-stage CP-SAT scheduler (see spec.md, "Engine").

Stage 1 (allocate): decide how many minutes each work item and each flexible weekly
activity gets on each day. All the day-level goals live here: deadlines, the buffer,
dependencies, the daily work cap and minimum, weekly targets, and finishing as early as possible (or spreading steady items evenly).

Stage 2 (place): for each day, place that day's minutes into exact 10-min slots, with
sessions between the minimum and maximum length, a 10-min break after each
work session, and same-day dependency order. If part of an item doesn't fit on a day,
stage 1 runs again with that item capped on that day at what did fit.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil

from ortools.sat.python import cp_model

from .models import (
    BREAK_MIN, SLOT_MIN, Item, Pace, ScheduleInput, display_title,
    WeeklyActivity, weekday, week_start,
)

SLOT = timedelta(minutes=SLOT_MIN)
BREAK = BREAK_MIN // SLOT_MIN

# Stage 1 objective weights, per 10-min slot, in order of importance.
W_UNSCHEDULED = 10_000
W_SHORT_WEEKLY = 1_000
W_SOFT_BROKEN = 500     # per slot of the prerequisite
W_IN_BUFFER = 50
W_SHORT_WORK = 20
W_UNEVEN = 5
W_NOT_PREFERRED = 2
W_EARLY = 1             # per slot, per day of delay, times urgency (1-5) and area weight
# Stability: a re-plan keeps the previous plan unless something is gained. Stage 1 pays per
# slot of a task moved to or from a day, so only urgent work is pulled a day earlier into
# freed time; stage 2 pays per slot a task moves within the day, more than starting it
# earlier saves.
W_STABLE = 1
W_STAY = 20

# Stage 1 stops once its plan is within 1% of the best possible: proving the last 1% took
# 3-4x as long and moved work by minutes, not days.
ALLOCATE_GAP = 0.01
DAY_THREADS = 8  # stage 2 days solved at once...
DAY_WORKERS = 2  # ...each with this many CP-SAT workers
DAY_TIME_S = 2.0    # search time per day; enough for almost every day...
DAY_RETRY_S = 10.0  # ...and a longer second try when a day isn't solved in time


@dataclass
class Slot:
    start: datetime
    day: date
    next: int | None = None  # index of the directly following slot in the same window
    prev: int | None = None
    focus: frozenset[str] = frozenset()  # inside an exam's focus window: only its subject's work
    window_len: int = 0  # slots in this slot's free window

    @property
    def end(self) -> datetime:
        return self.start + SLOT


@dataclass
class Unit:
    """One work item, as the engine sees it."""
    item: Item
    slots_needed: int
    min_session: int  # in slots
    weight: int
    urgency: int      # 1-5, higher = nearer finish-by


@dataclass
class Flex:
    """A flexible weekly activity: at most one session a day, a target per week."""
    act: WeeklyActivity
    fixed_len: int | None        # slots per session ("3 x 30 min"), or None ("3 hr a week")
    min_len: int
    max_len: int
    targets: dict[date, int]     # week start -> slots


@dataclass
class Session:
    kind: str       # "item" | "activity"
    ref_id: str     # item or activity id
    title: str
    area: str
    start: datetime
    end: datetime
    is_work: bool
    number: int | None = None  # session number within its task, when it has several

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Plan:
    status: str
    sessions: list[Session]
    unscheduled_min: dict[str, int]              # item id -> minutes that don't fit
    broken_soft: list[tuple[str, str]]           # (prerequisite id, dependent id)
    short_work_min: dict[date, int]
    short_weekly_min: dict[tuple[str, date], int]  # (activity id, week start) -> minutes
    units: list[Unit] = field(default_factory=list)


def _ceil_to_slot(t: datetime) -> datetime:
    over = (t.minute % SLOT_MIN) * 60 + t.second + t.microsecond / 1e6
    return t if over == 0 else t + timedelta(seconds=SLOT_MIN * 60 - over)


def _shortest_session_min(inp: ScheduleInput) -> int:
    lengths = [inp.settings.min_session_min]
    for act in inp.activities:
        lengths.append(act.session_min if act.sessions_per_week else act.min_session_min)
    return min(lengths)


def build_slots(inp: ScheduleInput) -> list[Slot]:
    """Free slots from now to the horizon. Windows too short to hold any session (e.g. the
    15 min between two classes) are left out, so stage 1 doesn't count them as room."""
    shortest = timedelta(minutes=_shortest_session_min(inp))
    windows = inp.focus_windows()
    slots: list[Slot] = []
    for day in inp.days():
        for start, end in inp.free_windows_on(day):
            start, end = max(start, _ceil_to_slot(inp.now)), min(end, inp.horizon_end)
            if end - start < shortest:
                continue
            t, prev_idx, first = start, None, len(slots)
            while t + SLOT <= end:
                if t >= inp.now and t + SLOT <= inp.horizon_end:
                    idx = len(slots)
                    focus = frozenset(a for s, e, a in windows if s <= t < e)
                    slots.append(Slot(start=t, day=day, prev=prev_idx, focus=focus))
                    if prev_idx is not None:
                        slots[prev_idx].next = idx
                    prev_idx = idx
                else:
                    prev_idx = None
                t += SLOT
            for sl in slots[first:]:
                sl.window_len = len(slots) - first
    return slots


def _urgency(item: Item, now: datetime) -> int:
    if item.finish_by is None:
        return 1
    days = (item.finish_by - now).days
    return 5 if days <= 3 else 4 if days <= 7 else 3 if days <= 14 else 2 if days <= 28 else 1


def build_units(inp: ScheduleInput) -> list[Unit]:
    min_len = inp.settings.min_session_min // SLOT_MIN
    units = []
    for item in inp.items:
        need = item.estimate_min // SLOT_MIN
        if need <= 0:
            continue
        units.append(Unit(item=item, slots_needed=need, min_session=min(min_len, need),
                          weight=inp.area(item.area).weight, urgency=_urgency(item, inp.now)))
    return units


def build_flex(inp: ScheduleInput) -> list[Flex]:
    """What is left of each flexible activity's weekly target. The current week gets the
    full target minus the sessions logged so far; a partial last week gets a prorated
    target, rounded up."""
    this_week = week_start(inp.now.date())
    days_in_week: dict[date, int] = {}
    for d in inp.days():
        days_in_week[week_start(d)] = days_in_week.get(week_start(d), 0) + 1
    out = []
    for act in inp.activities:
        if act.is_fixed:
            continue
        targets = {}
        for wk, n in days_in_week.items():
            share = 1 if wk == this_week else n / 7
            done_sessions, done_min = inp.activity_done_min(act.id, wk)
            if act.sessions_per_week:
                length = act.session_min // SLOT_MIN
                targets[wk] = max(0, ceil(act.sessions_per_week * share) - done_sessions) * length
            else:
                targets[wk] = max(0, ceil(act.weekly_min * share / SLOT_MIN) - done_min // SLOT_MIN)
        if act.sessions_per_week:
            length = act.session_min // SLOT_MIN
            out.append(Flex(act, length, length, length, targets))
        else:
            lo = act.min_session_min // SLOT_MIN
            out.append(Flex(act, None, lo, max(lo, inp.settings.max_session_min // SLOT_MIN), targets))
    return out


def dependency_edges(units: list[Unit]) -> list[tuple[int, int, bool]]:
    """(prerequisite unit, dependent unit, hard) for every dependency between units."""
    index = {u.item.id: i for i, u in enumerate(units)}
    return [(index[d.on], vi, d.hard) for vi, u in enumerate(units)
            for d in u.item.depends_on if d.on in index]


def _chain(slots: list[Slot], s: int, length: int) -> list[int] | None:
    """`length` directly consecutive slots starting at s, or None if the window ends first."""
    out = [s]
    while len(out) < length:
        nxt = slots[out[-1]].next
        if nxt is None:
            return None
        out.append(nxt)
    return out


def _new_solver(time_limit_s: float, workers: int = 8, gap: float = 0.0) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = workers
    solver.parameters.relative_gap_limit = gap
    return solver


def _allowed(slot: Slot, area: str, is_work: bool) -> bool:
    """Inside an exam's focus window, work from other subjects is kept out (see spec.md,
    "Rules")."""
    return not is_work or not slot.focus or area in slot.focus


def _fits(slot: Slot, item: Item) -> bool:
    if not _allowed(slot, item.area, item.is_work):
        return False
    if item.available_from and slot.start < item.available_from:
        return False
    return not (item.finish_by and slot.end > item.finish_by)


# --------------------------------------------------------------------------- stage 1


@dataclass
class Allocation:
    status: str
    amount: dict[tuple[int, date], int]       # (unit, day) -> slots
    flex_amount: dict[tuple[int, date], int]  # (flex, day) -> slots
    unscheduled: dict[int, int]
    broken: set[int]                          # indices into the edge list
    short_work: dict[date, int]
    short_weekly: dict[tuple[int, date], int]


def allocate(inp: ScheduleInput, units: list[Unit], flex: list[Flex], edges, slots: list[Slot],
             limit: dict[tuple[str, int, date], int], time_limit_s: float,
             before: dict[tuple[str, date], int] | None = None,
             start: Allocation | None = None) -> Allocation:
    """`limit` caps a unit ("u", index, day) or flexible activity ("f", index, day) on a
    day, after stage 2 found that only that much of it fits there. `before` holds the
    previous plan's slots per (task id, day), which a re-plan keeps where it can. `start`
    is the previous round's allocation: the search starts from it, within the new caps."""

    def stay_close(var, ref: str, d: date, top: int, name: str) -> None:
        if before is None:
            return
        was = before.get((ref, d), 0)
        if start is None:
            m.AddHint(var, min(was, top))  # start the search from the previous plan
        dev = m.NewIntVar(0, max(was, top), name)
        m.Add(dev >= var - was)
        m.Add(dev >= was - var)
        cost.append(W_STABLE * dev)

    max_len = inp.settings.max_session_min // SLOT_MIN
    days = sorted({s.day for s in slots})
    by_day = {d: [s for s in slots if s.day == d] for d in days}
    m = cp_model.CpModel()
    cost = []

    # Work items.
    a, sessions, used, unscheduled = {}, {}, {}, {}
    for ui, u in enumerate(units):
        item = u.item
        first_day = max(inp.now.date(), item.available_from.date() if item.available_from else date.min)
        for d in days:
            # Windows shorter than a session can't hold any of this item.
            room = sum(1 for s in by_day[d] if _fits(s, item) and s.window_len >= u.min_session)
            if room == 0:
                continue
            v = m.NewIntVar(0, min(room, u.slots_needed), f"a_{ui}_{d}")
            n = m.NewIntVar(0, room, f"n_{ui}_{d}")
            z = m.NewBoolVar(f"z_{ui}_{d}")
            m.Add(v <= u.slots_needed * z)
            m.Add(n >= z)
            # Sessions of at most the max length, and no longer than the window they sit in...
            longest = max(s.window_len for s in by_day[d] if _fits(s, item))
            m.Add(min(max_len, longest) * n >= v)
            m.Add(u.min_session * n <= v)  # ...and at least the min session length
            a[ui, d], sessions[ui, d], used[ui, d] = v, n, z
            if ("u", ui, d) in limit:
                m.Add(v <= limit["u", ui, d])
            if item.target_finish and datetime.combine(d, time.min) >= item.target_finish:
                cost.append(W_IN_BUFFER * v)
            if item.pace is Pace.ASAP:
                cost.append(W_EARLY * u.urgency * u.weight * (d - first_day).days * v)
            stay_close(v, item.id, d, u.slots_needed, f"moved_{ui}_{d}")
        unscheduled[ui] = m.NewIntVar(0, u.slots_needed, f"unsched_{ui}")
        m.Add(sum(v for (uj, _), v in a.items() if uj == ui) + unscheduled[ui] == u.slots_needed)
        cost.append(W_UNSCHEDULED * unscheduled[ui])

    # Steady items: spread evenly over the days up to the target finish.
    for ui, u in enumerate(units):
        if u.item.pace is not Pace.STEADY:
            continue
        mine = [d for d in days if (ui, d) in a and
                (u.item.target_finish is None or datetime.combine(d, time.min) < u.item.target_finish)]
        if len(mine) < 2:
            continue
        avg = u.slots_needed // len(mine)
        for d in mine:
            dev = m.NewIntVar(0, u.slots_needed, f"dev_{ui}_{d}")
            m.Add(dev >= a[ui, d] - avg)
            m.Add(dev >= avg - a[ui, d])
            cost.append(W_UNEVEN * dev)

    # Dependencies: a unit may run on day d only once its prerequisite is finished by the
    # end of day d (same-day order is handled in stage 2). A soft edge may be broken.
    broken = {}
    for ei, (ui, vi, hard) in enumerate(edges):
        if not hard:
            broken[ei] = m.NewBoolVar(f"broken_{ei}")
            cost.append(W_SOFT_BROKEN * units[ui].slots_needed * broken[ei])
        for d in days:
            if (vi, d) not in a:
                continue
            done = sum(a[ui, e] for e in days if e <= d and (ui, e) in a)
            enforce = [used[vi, d]] + ([broken[ei].Not()] if ei in broken else [])
            m.Add(done + unscheduled[ui] >= units[ui].slots_needed).OnlyEnforceIf(enforce)

    # Flexible weekly activities.
    h, held = {}, {}
    for k, f in enumerate(flex):
        preferred = f.act.preferred_days
        done_on = {day for a, day, _ in inp.activity_done if a == f.act.id}
        for d in days:
            if d in done_on:  # at most one session a day, and today's is done
                continue
            room = sum(1 for s in by_day[d] if _allowed(s, f.act.area, f.act.is_work))
            longest = max((s.window_len for s in by_day[d] if _allowed(s, f.act.area, f.act.is_work)), default=0)
            if room < f.min_len or longest < f.min_len:
                continue
            b = m.NewBoolVar(f"held_{k}_{d}")
            if f.fixed_len:
                hv = m.NewIntVar(0, f.fixed_len, f"h_{k}_{d}")
                m.Add(hv == f.fixed_len * b)
            else:
                hv = m.NewIntVar(0, min(room, f.max_len, longest), f"h_{k}_{d}")
                m.Add(hv >= f.min_len * b)
                m.Add(hv <= f.max_len * b)
            h[k, d], held[k, d] = hv, b
            stay_close(hv, f.act.id, d, f.max_len, f"moved_f_{k}_{d}")
            if ("f", k, d) in limit:
                m.Add(hv <= limit["f", k, d])
            if preferred and weekday(d) not in preferred:
                cost.append(W_NOT_PREFERRED * hv)
    short_weekly = {}
    for k, f in enumerate(flex):
        for wk, target in f.targets.items():
            got = [h[k, d] for d in days if week_start(d) == wk and (k, d) in h]
            short_weekly[k, wk] = m.NewIntVar(0, target, f"short_w_{k}_{wk}")
            m.Add(sum(got) + short_weekly[k, wk] == target)  # the target, no more
            cost.append(W_SHORT_WEEKLY * short_weekly[k, wk])

    # Per-day capacity and balance.
    short_work = {}
    for d in days:
        today = [ui for ui in range(len(units)) if (ui, d) in a]
        flex_today = [k for k in range(len(flex)) if (k, d) in h]
        work = (sum(a[ui, d] for ui in today if units[ui].item.is_work)
                + sum(h[k, d] for k in flex_today if flex[k].act.is_work))
        n_work = (sum(sessions[ui, d] for ui in today if units[ui].item.is_work)
                  + sum(held[k, d] for k in flex_today if flex[k].act.is_work))
        other = (sum(a[ui, d] for ui in today if not units[ui].item.is_work)
                 + sum(h[k, d] for k in flex_today if not flex[k].act.is_work))
        cap = len(by_day[d])
        # Every work session is followed by a break (the last one may fall at a window end).
        m.Add(work + BREAK * n_work + other <= cap + BREAK)
        # Work only fits in windows long enough for a work session; shorter gaps (e.g. 30 min
        # between dinner and a commitment) are left to hobbies.
        shortest_work = min([units[ui].min_session for ui in today if units[ui].item.is_work]
                            + [flex[k].min_len for k in flex_today if flex[k].act.is_work]
                            + [inp.settings.min_session_min // SLOT_MIN])
        long_room = sum(1 for s in by_day[d] if s.window_len >= shortest_work)
        m.Add(work + BREAK * n_work <= long_room + BREAK)
        # Each window holds only so many sessions: a session and its break take at least
        # the shortest session plus a break (a 1.5 hr window holds one 50-min session).
        shortest_any = min([units[ui].min_session for ui in today] + [flex[k].min_len for k in flex_today]
                           + [inp.settings.min_session_min // SLOT_MIN])
        room_for = sum((s.window_len + BREAK) // (shortest_any + BREAK) for s in by_day[d] if s.prev is None)
        m.Add(sum(sessions[ui, d] for ui in today) + sum(held[k, d] for k in flex_today) <= room_for)
        m.Add(work <= max(0, inp.max_work_on(d) - inp.fixed_work_min_on(d)) // SLOT_MIN)
        min_work = inp.min_work_on(d) // SLOT_MIN
        if min_work:
            short_work[d] = m.NewIntVar(0, min_work, f"short_work_{d}")
            m.Add(work + short_work[d] >= min_work)
            cost.append(W_SHORT_WORK * short_work[d])
        # Items and weekly activities that may only use part of the day (available from
        # mid-day, due mid-day, or kept out by an exam's focus window) must fit into that
        # part. For every such part, what is confined to it can't take more than its slots.
        span_of, need = {}, {}
        for ui in today:
            ok = [i for i, s in enumerate(by_day[d]) if _fits(s, units[ui].item)]
            span_of["u", ui] = (ok[0], ok[-1])
            need["u", ui] = a[ui, d] + BREAK * sessions[ui, d]
        for k in flex_today:
            ok = [i for i, s in enumerate(by_day[d]) if _allowed(s, flex[k].act.area, flex[k].act.is_work)]
            span_of["f", k] = (ok[0], ok[-1])
            need["f", k] = h[k, d] + BREAK * held[k, d]
        whole = (0, len(by_day[d]) - 1)
        for lo in {lo for lo, _ in span_of.values()}:
            for hi in {hi for _, hi in span_of.values()}:
                inside = [key for key, (l, r) in span_of.items() if lo <= l and r <= hi]
                if lo > hi or (lo, hi) == whole or not inside:
                    continue
                m.Add(sum(need[key] for key in inside) <= hi - lo + 1 + BREAK)

    if start is not None:  # a later round: start from the last one, cut to the new caps
        for (ui, d), v in a.items():
            m.AddHint(v, min(start.amount.get((ui, d), 0), limit.get(("u", ui, d), 10**9)))
        for (k, d), v in h.items():
            m.AddHint(v, min(start.flex_amount.get((k, d), 0), limit.get(("f", k, d), 10**9)))

    m.Minimize(sum(cost))
    solver = _new_solver(time_limit_s, gap=ALLOCATE_GAP)
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Allocation(solver.StatusName(status), {}, {}, {}, set(), {}, {})
    val = solver.Value
    return Allocation(
        status=solver.StatusName(status),
        amount={k: val(v) for k, v in a.items() if val(v)},
        flex_amount={k: val(v) for k, v in h.items() if val(v)},
        unscheduled={ui: val(v) for ui, v in unscheduled.items() if val(v)},
        broken={ei for ei, v in broken.items() if val(v)},
        short_work={d: val(v) for d, v in short_work.items() if val(v)},
        short_weekly={k: val(v) for k, v in short_weekly.items() if val(v)},
    )


# --------------------------------------------------------------------------- stage 2


@dataclass
class Piece:
    """Something to place on one day: part of a work item, or a weekly activity session."""
    key: tuple[str, int]  # ("u", unit index) or ("f", flex index)
    want: int
    min_len: int          # a single session covers the whole piece when min_len == want
    is_work: bool
    area: str
    item: Item | None = None
    ref: str = ""         # the task or activity id


def _greedy_day(pieces: list[Piece], day_slots: list[Slot], order: list[tuple[int, int]],
                max_len: int) -> dict[int, int]:
    """A quick layout for a day (slot index -> piece index): the solver's starting point,
    and what is used if the solver finds nothing in time. Pieces in dependency order, each
    after its prerequisites, packed into the earliest slots they may use, in sessions
    between their minimum and the maximum length, with a break between two work sessions.
    It keeps every stage 2 rule, but may leave some of a piece out."""
    before = {j: {i for i, k in order if k == j} for j in range(len(pieces))}
    todo, seq = set(range(len(pieces))), []
    while todo:  # dependency order, else the order given
        ready = [q for q in todo if not before[q] & todo]
        p = min(ready or todo)
        seq.append(p)
        todo.discard(p)
    owner: dict[int, int] = {}

    def ok(p: int, s: int) -> bool:
        pc, sl = pieces[p], day_slots[s]
        return s not in owner and (_fits(sl, pc.item) if pc.item else _allowed(sl, pc.area, pc.is_work))

    def other_work(p: int, s: int | None) -> bool:
        """Slot s holds a different work piece (p is work: it needs a break next to it)."""
        q = owner.get(s) if s is not None else None
        return pieces[p].is_work and q is not None and q != p and pieces[q].is_work

    def free_run(p: int, s: int) -> int:
        n = 0
        while s is not None and ok(p, s) and n < max_len:
            n, s = n + 1, day_slots[s].next
        return n

    for p in seq:
        left, shortest = pieces[p].want, min(pieces[p].min_len, pieces[p].want)
        # All of a prerequisite comes first.
        s = max((t + 1 for t, q in owner.items() if q in before[p]), default=0)
        while left > 0 and s < len(day_slots):
            if other_work(p, day_slots[s].prev):
                s += 1
                continue
            run = free_run(p, s)
            # The slot after the session can't start another work piece.
            while run and other_work(p, _nth(day_slots, s, run)):
                run -= 1
            chunk = min(left, run)
            if 0 < left - chunk < shortest:  # don't leave a remainder too short for a session
                chunk = left - shortest
            if chunk < shortest:
                s += 1
                continue
            t = s
            for _ in range(chunk):
                owner[t] = p
                t = day_slots[t].next
            left -= chunk
            s = s + chunk + 1  # a break after every session
    return owner


def _nth(day_slots: list[Slot], s: int, k: int) -> int | None:
    """The slot k steps after s in the same window, or None if the window ends first."""
    for _ in range(k):
        if s is None:
            return None
        s = day_slots[s].next
    return s


def place_day(pieces: list[Piece], day_slots: list[Slot], order: list[tuple[int, int]],
              max_len: int, time_limit_s: float,
              before: dict[datetime, str] | None = None) -> tuple[dict[int, int], dict[int, int], bool]:
    """Place one day's allocation into slots. `order` holds (i, j) piece pairs where all of
    i comes before j. `before` maps slot starts to the task the previous plan had there;
    pieces stay in those slots where they can. Returns (slot index -> piece index, piece index -> slots that
    couldn't be placed, whether that is proven: the solver finished rather than ran out of
    time)."""
    m = cp_model.CpModel()
    n = len(day_slots)
    P = range(len(pieces))
    x = {(p, s): m.NewBoolVar(f"x_{p}_{s}") for p in P for s in range(n)}
    for (p, s), var in x.items():  # available-from, finish-by and exam mornings
        pc, sl = pieces[p], day_slots[s]
        if not (_fits(sl, pc.item) if pc.item else _allowed(sl, pc.area, pc.is_work)):
            m.Add(var == 0)
    miss = {p: m.NewIntVar(0, pieces[p].want, f"miss_{p}") for p in P}

    def get(var_of, s):
        return var_of(s) if s is not None else 0

    for s in range(n):
        m.Add(sum(x[p, s] for p in P) <= 1)
    for p in P:
        m.Add(sum(x[p, s] for s in range(n)) + miss[p] == pieces[p].want)

    for p in P:  # every session is at least the piece's minimum length
        length = min(pieces[p].min_len, pieces[p].want)
        if length <= 1:
            continue
        for s in range(n):
            starts = x[p, s] - get(lambda t: x[p, t], day_slots[s].prev)
            chain = _chain(day_slots, s, length)
            if chain is None:
                m.Add(starts <= 0)
            else:
                for t in chain[1:]:
                    m.Add(x[p, t] >= starts)

    work = [p for p in P if pieces[p].is_work]
    span = max_len + BREAK
    for s in range(n):
        chain = _chain(day_slots, s, span)
        if chain:  # a break after at most max_len of work
            m.Add(sum(x[p, t] for p in work for t in chain) <= span - 1)
        nxt = day_slots[s].next
        if nxt is not None:  # a break between two different work pieces
            for p in work:
                m.Add(x[p, s] + sum(x[q, nxt] for q in work if q != p) <= 1)

    for i, j in order:  # all of i before any of j
        last_i = m.NewIntVar(0, n, f"last_{i}_{j}")
        for s in range(n):
            m.Add(last_i >= s + 1).OnlyEnforceIf(x[i, s])
            m.Add(last_i <= s).OnlyEnforceIf(x[j, s])

    starts = []  # fewer, longer sessions: penalise each session start
    for p in P:
        for s in range(n):
            st = m.NewBoolVar(f"st_{p}_{s}")
            m.Add(st >= x[p, s] - get(lambda t: x[p, t], day_slots[s].prev))
            starts.append(st)
    early = sum(s * x[p, s] for p in P for s in range(n))  # within the day, earlier is better
    moved = 0
    if before:
        moved = sum(var for (p, s), var in x.items() if before.get(day_slots[s].start) != pieces[p].ref)
    m.Minimize(100_000 * sum(miss.values()) + 100 * sum(starts) + early + W_STAY * moved)
    # Start from the previous layout if it still holds all of the day's work, else greedy.
    first, got = {}, {}
    for s, sl in enumerate(day_slots):
        p = next((q for q in P if before and before.get(sl.start) == pieces[q].ref), None)
        if p is not None and got.get(p, 0) < pieces[p].want:
            first[s], got[p] = p, got.get(p, 0) + 1
    greedy = _greedy_day(pieces, day_slots, order, max_len)
    if any(got.get(p, 0) < pieces[p].want for p in P):
        first = greedy
    for (p, s), var in x.items():
        m.AddHint(var, first.get(s) == p)

    solver = _new_solver(time_limit_s, workers=DAY_WORKERS)
    status = solver.Solve(m)

    def missed_in(owner: dict[int, int]) -> dict[int, int]:
        placed = {p: 0 for p in P}
        for p in owner.values():
            placed[p] += 1
        return {p: pieces[p].want - placed[p] for p in P if placed[p] < pieces[p].want}

    # Out of time with nothing (or less) placed: keep the quick layout rather than drop
    # the day, which would cap all of its work at zero in the next round.
    fallback = (greedy, missed_in(greedy))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return *fallback, False
    owner = {s: p for (p, s), v in x.items() if solver.Value(v)}
    missed = {p: solver.Value(v) for p, v in miss.items() if solver.Value(v)}
    if status != cp_model.OPTIMAL and sum(fallback[1].values()) < sum(missed.values()):
        return *fallback, False
    return owner, missed, status == cp_model.OPTIMAL


# --------------------------------------------------------------------------- driver


def _number_sessions(sessions: list[Session], units: list[Unit]) -> None:
    """Planned sessions of a task are numbered on from the sessions already logged
    ("AIDS Project 2 - session 2"). A task done in a single session gets no number."""
    items = {u.item.id: u.item for u in units}
    planned: dict[str, list[Session]] = {}
    for s in sessions:
        if s.kind == "item":
            planned.setdefault(s.ref_id, []).append(s)
    for item_id, mine in planned.items():
        done = items[item_id].sessions_logged
        if done + len(mine) < 2:
            continue
        for n, s in enumerate(sorted(mine, key=lambda s: s.start), start=done + 1):
            s.number = n
            s.title = f"{s.title} - session {n}"


def _day_slots(slots: list[Slot], d: date) -> list[Slot]:
    idx = [i for i, s in enumerate(slots) if s.day == d]
    remap = {g: k for k, g in enumerate(idx)}
    return [Slot(slots[g].start, d, next=remap.get(slots[g].next), prev=remap.get(slots[g].prev),
                 focus=slots[g].focus, window_len=slots[g].window_len) for g in idx]


def _before(previous: list[tuple[str, datetime, datetime]] | None, now: datetime):
    """The previous plan from now on: slot start -> task id, and slots per (task id, day)."""
    if not previous:
        return None, None
    at: dict[datetime, str] = {}
    for ref, start, end in previous:
        t = start
        while t + SLOT <= end:
            if t >= now:
                at[t] = ref
            t += SLOT
    per_day: dict[tuple[str, date], int] = {}
    for t, ref in at.items():
        per_day[ref, t.date()] = per_day.get((ref, t.date()), 0) + 1
    return at, per_day


def solve(inp: ScheduleInput, time_limit_s: float = 30.0, max_rounds: int = 5,
          previous: list[tuple[str, datetime, datetime]] | None = None) -> Plan:
    """`previous` is the last plan's sessions (task id, start, end): a re-plan stays close
    to it, so nothing moves without a reason."""
    before_at, before_day = _before(previous, inp.now)
    slots = build_slots(inp)
    units = build_units(inp)
    flex = build_flex(inp)
    edges = dependency_edges(units)
    days = sorted({s.day for s in slots})
    max_len = inp.settings.max_session_min // SLOT_MIN
    limit: dict[tuple[str, int, date], int] = {}

    alloc = None
    for _ in range(max_rounds):
        alloc = allocate(inp, units, flex, edges, slots, limit, time_limit_s, before_day, alloc)
        if alloc.status not in ("OPTIMAL", "FEASIBLE"):
            return Plan(alloc.status, [], {}, [], {}, {}, units)
        kept = [(ui, vi) for ei, (ui, vi, _) in enumerate(edges) if ei not in alloc.broken]

        def place(d: date):
            pieces = [Piece(("u", ui), amt, units[ui].min_session, units[ui].item.is_work,
                            units[ui].item.area, units[ui].item, units[ui].item.id)
                      for (ui, e), amt in alloc.amount.items() if e == d]
            pieces += [Piece(("f", k), amt, amt, flex[k].act.is_work, flex[k].act.area, ref=flex[k].act.id)
                       for (k, e), amt in alloc.flex_amount.items() if e == d]
            pos = {p.key: i for i, p in enumerate(pieces)}
            order = [(pos["u", ui], pos["u", vi]) for ui, vi in kept
                     if ("u", ui) in pos and ("u", vi) in pos]
            day_slots = _day_slots(slots, d)
            owner, missed, proven = place_day(pieces, day_slots, order, max_len, DAY_TIME_S, before_at)
            if missed and not proven:  # out of time, not out of room: try again, longer
                owner, missed, _ = place_day(pieces, day_slots, order, max_len, DAY_RETRY_S, before_at)
            return d, day_slots, pieces, owner, missed

        # Days are independent in stage 2, so they are placed in parallel.
        placed, overflow = {}, {}
        with ThreadPoolExecutor(max_workers=DAY_THREADS) as pool:
            results = list(pool.map(place, days))
        for d, day_slots, pieces, owner, missed in results:
            placed[d] = (day_slots, pieces, owner)
            for p, lost in missed.items():  # next round: only what fitted stays on this day
                kind, i = pieces[p].key
                limit[kind, i, d] = pieces[p].want - lost
                overflow[d] = overflow.get(d, 0) + lost
        if not overflow:
            break

    sessions: list[Session] = []
    for d in days:
        day_slots, pieces, owner = placed[d]
        for s, sl in enumerate(day_slots):
            p = owner.get(s)
            if p is None:
                continue
            if sl.prev is not None and owner.get(sl.prev) == p:
                sessions[-1].end = sl.end
                continue
            kind, i = pieces[p].key
            if kind == "u":
                item = units[i].item
                sessions.append(Session("item", item.id, display_title(item.title, item.area), item.area,
                                        sl.start, sl.end, item.is_work))
            else:
                act = flex[i].act
                sessions.append(Session("activity", act.id, display_title(act.title, act.area), act.area,
                                        sl.start, sl.end, act.is_work))

    _number_sessions(sessions, units)

    unscheduled = {units[ui].item.id: amt * SLOT_MIN for ui, amt in alloc.unscheduled.items()}
    for d, missed in overflow.items():  # still didn't fit after all rounds
        unscheduled[f"(unplaced on {d})"] = missed * SLOT_MIN

    return Plan(
        status=alloc.status,
        sessions=sessions,
        unscheduled_min=unscheduled,
        broken_soft=[(units[edges[ei][0]].item.id, units[edges[ei][1]].item.id) for ei in alloc.broken],
        short_work_min={d: v * SLOT_MIN for d, v in alloc.short_work.items()},
        short_weekly_min={(flex[k].act.id, wk): v * SLOT_MIN for (k, wk), v in alloc.short_weekly.items()},
        units=units,
    )
