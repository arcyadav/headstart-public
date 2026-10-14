"""Data model for HeadStart (see spec.md, "Inputs")."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

SLOT_MIN = 10                  # engine time grid
DEFAULT_ESTIMATE_MIN = 90      # a work item with no estimate
TASK_TYPES = ("study", "assignment", "other")  # what kind of task ("type" in the setup file)
DEFAULT_SECTION_MIN = 90       # a section with no estimate
DEFAULT_REVISION_MIN = 180     # an exam milestone with no revision budget
DEFAULT_REVISION_DAYS = 7      # revision becomes available this many days before the exam
DEFAULT_FOCUS_HR = 24          # before an exam, only that subject's work is planned
MAX_SESSION_MIN = 90           # default max session; longer work is split
BREAK_MIN = 10                 # fixed break after each work session
BUFFER = timedelta(days=1)     # target finish = finish-by - buffer
MIN_HORIZON = timedelta(days=7)

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

PALETTE = ["#4e79a7", "#e15759", "#59a14f", "#f28e2b", "#b07aa1", "#76b7b2", "#edc948", "#9c755f",
           "#ff9da7", "#86bcb6", "#d4a6c8", "#8cd17d"]


def next_color(used: list[str]) -> str:
    """The first palette colour no area has yet (cycling once all are taken). An area keeps
    its colour, so deleting one never recolours the others."""
    free = [c for c in PALETTE if c not in used]
    return free[0] if free else PALETTE[len(used) % len(PALETTE)]


def weekday(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def display_title(title: str, area: str) -> str:
    """The title with its subject in front, unless it already names it ("Assignment 5" ->
    "DAA Assignment 5", but "RP lecture 8/9" and "Revise for CMO Midsem" stay). The catch-all
    "Other" area isn't put in front ("Renew passport", not "Other Renew passport")."""
    return title if area in title.split() or area.lower() == "other" else f"{area} {title}"


def round_up_to_slot(minutes: int) -> int:
    return -(-minutes // SLOT_MIN) * SLOT_MIN


class AreaKind(str, Enum):
    SUBJECT = "subject"
    LAB = "lab"
    HOBBY = "hobby"
    OTHER = "other"

    @property
    def is_work(self) -> bool:
        return self is not AreaKind.HOBBY


class Pace(str, Enum):
    ASAP = "asap"      # finish as early as the constraints allow
    STEADY = "steady"  # spread evenly until the target finish


@dataclass(frozen=True)
class Window:
    """A time span within a day. An end of 00:00 means midnight at the end of the day
    (written "24:00")."""
    start: time
    end: time

    @property
    def start_min(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_min(self) -> int:
        return self.end.hour * 60 + self.end.minute or 24 * 60

    @property
    def minutes(self) -> int:
        return self.end_min - self.start_min

    def on(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, self.start)
        return start, start + timedelta(minutes=self.minutes)


@dataclass
class Block:
    """Fixed, blocked time on a date: a class, a commitment or a fixed weekly activity."""
    title: str
    start: datetime
    end: datetime
    kind: str  # "class" | "exam" | "commitment" | "activity"
    is_work: bool = False  # counts toward the day's work max (e.g. ICPC practice)
    ref: int | None = None  # a commitment's position in the setup file


@dataclass
class Commitment:
    title: str
    window: Window
    days: list[str] = field(default_factory=list)  # recurring on these weekdays...
    date: date | None = None                       # ...or one-off on this date
    work: bool = False                             # counts toward the day's work max
    skip: set[date] = field(default_factory=set)   # dates a recurring one doesn't happen

    def on(self, day: date) -> bool:
        if self.date:
            return day == self.date
        return weekday(day) in self.days and day not in self.skip


@dataclass
class Milestone:
    id: str
    title: str
    area: str
    at: datetime                     # start (a bare date means 00:00 that day)
    revision_min: int
    revision_days: int = DEFAULT_REVISION_DAYS
    end: datetime | None = None      # set when the exam has a time: it blocks that slot
    syllabus_until: date | None = None  # lectures after this date count toward the next exam
    focus_hr: int = DEFAULT_FOCUS_HR    # focus window before the exam (0 = none)
    quiz: bool = False                  # a quiz rather than an exam ("type": "quiz"); just a label

    @property
    def over(self) -> datetime:
        return self.end or self.at


@dataclass
class Dependency:
    on: str           # id of the prerequisite item (same area)
    hard: bool = True


@dataclass
class Section:
    title: str
    estimate_min: int
    done: bool = False


@dataclass
class Item:
    id: str
    title: str
    area: str
    estimate_min: int                  # what is left to do
    is_work: bool = True
    due: datetime | None = None
    counts_toward: Milestone | None = None
    available_from: datetime | None = None
    depends_on: list[Dependency] = field(default_factory=list)
    pace: Pace = Pace.ASAP
    sections: list[Section] = field(default_factory=list)
    is_revision: bool = False
    done: bool = False                 # marked completed in the progress log
    sessions_logged: int = 0           # work sessions already done, from the progress log
    spent_min: int = 0                 # hours worked so far, from the progress log
    total_min: int = 0                 # the estimate from the setup file, before any progress
    lecture_date: date | None = None   # set on generated lecture items
    task_type: str = "other"           # study, assignment or other (lectures: study)

    @property
    def finish_by(self) -> datetime | None:
        dates = [d for d in (self.due, self.counts_toward and self.counts_toward.at) if d]
        return min(dates) if dates else None

    @property
    def target_finish(self) -> datetime | None:
        """Finish-by minus the 1-day buffer. Revision has no buffer: the evening before the
        exam is when it happens."""
        if self.finish_by is None:
            return None
        return self.finish_by if self.is_revision else self.finish_by - BUFFER


@dataclass
class WeeklyActivity:
    id: str
    title: str
    area: str
    is_work: bool
    sessions_per_week: int | None = None  # "3 x 30 min" form...
    session_min: int | None = None
    weekly_min: int | None = None         # ...or "3 hr a week" form
    min_session_min: int = 30
    preferred_days: list[str] = field(default_factory=list)
    fixed: list[tuple[str, Window]] = field(default_factory=list)  # blocks time if set

    @property
    def is_fixed(self) -> bool:
        return bool(self.fixed)


@dataclass
class Area:
    name: str
    kind: AreaKind
    weight: int = 1
    timetable: list[tuple[str, Window]] = field(default_factory=list)
    cancelled: set[date] = field(default_factory=set)
    extra: list[tuple[date, Window]] = field(default_factory=list)
    lecture_items: bool = False
    lecture_estimate_min: int = DEFAULT_ESTIMATE_MIN
    pending_lectures: list[date] = field(default_factory=list)
    # Per-lecture changes made after generation, by class date: estimate_hr, due,
    # counts_toward (null = not for any exam), deleted (true = no lecture item).
    lecture_overrides: dict[date, dict] = field(default_factory=dict)
    milestones: list[Milestone] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    weekly: list[WeeklyActivity] = field(default_factory=list)
    color: str | None = None

    def exams_on(self, day: date) -> list[Milestone]:
        return [m for m in self.milestones if m.end and m.at.date() == day]

    def classes_on(self, day: date) -> list[Window]:
        """This area's classes on a date, after one-time changes. An exam held in a class
        slot replaces that class."""
        out = [] if day in self.cancelled else [w for wd, w in self.timetable if wd == weekday(day)]
        out += [w for d, w in self.extra if d == day]
        exams = self.exams_on(day)
        out = [w for w in out if not any(w.on(day)[0] < m.end and m.at < w.on(day)[1] for m in exams)]
        return sorted(out, key=lambda w: w.start)


@dataclass
class DayRule:
    """A per-weekday or per-date override. None = not overridden. A date's bounds limit
    that day's study slots to within them."""
    bounds: Window | None = None
    max_work_min: int | None = None
    min_work_min: int | None = None


@dataclass
class Settings:
    max_work_min: int
    min_work_min: int = 0
    min_session_min: int = 30
    max_session_min: int = MAX_SESSION_MIN
    weekday_rules: dict[str, DayRule] = field(default_factory=dict)
    date_rules: dict[date, DayRule] = field(default_factory=dict)

    def rule(self, day: date, attr: str):
        """Date override, then weekday override, then None."""
        for r in (self.date_rules.get(day), self.weekday_rules.get(weekday(day))):
            if r is not None and getattr(r, attr) is not None:
                return getattr(r, attr)
        return None


@dataclass
class Semester:
    name: str
    start: date | None = None
    end: date | None = None

    def week_of(self, day: date) -> tuple[int, int] | None:
        """(this week's number, number of weeks), counting the start's week as week 1."""
        if not (self.start and self.end):
            return None
        first = week_start(self.start)
        return (week_start(day) - first).days // 7 + 1, (week_start(self.end) - first).days // 7 + 1


@dataclass
class ScheduleInput:
    now: datetime
    availability: dict[str, list[Window]]  # when the user can study, per weekday
    commitments: list[Commitment]
    areas: list[Area]
    settings: Settings
    tracking_since: datetime | None = None  # lecture items exist for classes after this
    semester: Semester | None = None
    # Weekly-activity sessions already done, from the progress log: (activity id, day, minutes).
    activity_done: list[tuple[str, date, int]] = field(default_factory=list)

    def activity_done_min(self, act_id: str, week: date) -> tuple[int, int]:
        """(sessions, minutes) of an activity logged in the week starting `week`."""
        rows = [m for a, d, m in self.activity_done if a == act_id and week_start(d) == week]
        return len(rows), sum(rows)

    @property
    def items(self) -> list[Item]:
        return [i for a in self.areas for i in a.items]

    @property
    def milestones(self) -> list[Milestone]:
        return [m for a in self.areas for m in a.milestones]

    @property
    def activities(self) -> list[WeeklyActivity]:
        return [w for a in self.areas for w in a.weekly]

    def area(self, name: str) -> Area:
        return next(a for a in self.areas if a.name == name)

    @property
    def horizon_end(self) -> datetime:
        """The latest milestone or due date, but at least 7 days ahead."""
        week_ahead = datetime.combine(self.now.date() + MIN_HORIZON, time.min)
        dates = [m.at for m in self.milestones] + [i.due for i in self.items if i.due]
        return max([week_ahead] + dates)

    def days(self) -> list[date]:
        """Every calendar day from today up to the horizon."""
        out, d = [], self.now.date()
        while datetime.combine(d, time.min) < self.horizon_end:
            out.append(d)
            d += timedelta(days=1)
        return out

    # ---- per-day rules

    def slots_on(self, day: date) -> list[Window]:
        """The user's study slots on a date: the weekday's slots, cut to the date's bounds
        if it has any."""
        slots = self.availability.get(weekday(day), [])
        bounds = self.settings.rule(day, "bounds")
        if bounds is None:
            return slots
        out = []
        for w in slots:
            s, e = max(w.start_min, bounds.start_min), min(w.end_min, bounds.end_min)
            if s < e:
                out.append(Window(time(s // 60, s % 60), time(e // 60 % 24, e % 60)))
        return out

    def max_work_on(self, day: date) -> int:
        r = self.settings.rule(day, "max_work_min")
        return self.settings.max_work_min if r is None else r

    def min_work_on(self, day: date) -> int:
        r = self.settings.rule(day, "min_work_min")
        return self.settings.min_work_min if r is None else r

    def focus_windows(self) -> list[tuple[datetime, datetime, str]]:
        """(start, end, area) for each exam's focus window: the `focus_hr` before it, but
        not reaching back past the end of an earlier exam on another day. Exams on the same
        day share the overlap, where both subjects are allowed."""
        out = []
        for m in self.milestones:
            if m.focus_hr <= 0:
                continue
            start = m.at - timedelta(hours=m.focus_hr)
            earlier = [o.over for o in self.milestones
                       if o is not m and o.over <= m.at and o.at.date() != m.at.date()]
            start = max([start] + earlier)
            out.append((start, m.at, m.area))
        return out

    # ---- blocked and free time

    def blocks_on(self, day: date) -> list[Block]:
        out = []
        for a in self.areas:
            for w in a.classes_on(day):
                out.append(Block(a.name, *w.on(day), "class"))
            for m in a.exams_on(day):
                out.append(Block(m.title, m.at, m.end, "exam"))
            for act in a.weekly:
                for wd, w in act.fixed:
                    if wd == weekday(day):
                        out.append(Block(act.title, *w.on(day), "activity", act.is_work))
        for n, c in enumerate(self.commitments):
            if c.on(day):
                out.append(Block(c.title, *c.window.on(day), "commitment", c.work, ref=n))
        return sorted(out, key=lambda b: b.start)

    def fixed_work_min_on(self, day: date) -> int:
        """Minutes of fixed work (work commitments, fixed work activities) still ahead on
        a day. They use up part of that day's work max."""
        return sum(int((b.end - max(b.start, self.now)).total_seconds() // 60)
                   for b in self.blocks_on(day) if b.is_work and b.end > self.now)

    def free_windows_on(self, day: date) -> list[tuple[datetime, datetime]]:
        """Study slots minus blocks (see spec.md, "Free time")."""
        free = [w.on(day) for w in self.slots_on(day)]
        for b in self.blocks_on(day):
            nxt = []
            for s, e in free:
                if b.end <= s or b.start >= e:
                    nxt.append((s, e))
                    continue
                if s < b.start:
                    nxt.append((s, b.start))
                if b.end < e:
                    nxt.append((b.end, e))
            free = nxt
        return free
