# Smart Balanced Scheduler — Spec (v0.2)

**Author:** Archana · **Date:** 2026-09-30 · **Course:** UMC301

## What changed from v0.1

- **Built for students.** Work is organised by **area**: subjects, labs, hobbies and other tasks. A flat list of typed tasks is gone.
- **Exams are milestones, not tasks.** An exam is a date (the UI refuses a new exam dated in the past, usually a mistyped year). An exam's name, date, time and syllabus end can be edited on its subject page; it keeps its id (written into the setup file if it had none), so tasks that count toward it, its revision and its logged progress stay with it. The work that prepares for it (studying lectures, assignments, revision) is made of separate items that point to it.
- **Dependencies form a graph within an area**, not a fixed subtask order. The v0.1 prep/core idea becomes **soft** vs **hard** dependencies.
- **As soon as possible, not evenly spread.** New lectures and assignments keep arriving, so time left free today is time needed tomorrow. Front-loading also builds a lead that absorbs missed sessions.
- **Timetable in, work out.** The user enters a weekly class timetable and when they can study. Free time is worked out from those, and every lecture automatically creates a "study this lecture" item.
- **Weekly activities** (hobbies, or regular study like LAA 1.5 hr/week) are recurring targets, not tasks that finish. They can be flexible or fixed to exact times.

## Problem Statement

Students want to study regularly but often fail to. They either:

- don't know how much time to give to each task,
- waste time making schedules instead of following them, or
- give up when they miss a task, because the plan falls apart.

They also tend to either overwork or ignore rest and hobbies. And a semester's work never stops arriving: a new lecture every few days, and assignments and quizzes on top.

## Goal

Build a scheduler that:

- takes the user's timetable, study slots, subjects and hobbies,
- generates lecture-study work from the timetable by itself,
- builds a plan that finishes work as early as the user's limits allow,
- re-plans everything when something is missed or added, and
- always tells the user the **next task**.

## Inputs

### Semester (set once, editable)

A name and a start and end date, e.g. Sem 5, 3 Aug – 4 Dec. The header shows the current week ("Sem 5 · week 9 of 18"), counting the start's week as week 1. For now the dates are only shown; planning doesn't use them yet.

### Study slots (set once, editable)

When the user can study, per weekday, as any number of slots anywhere in the day, e.g. Mon 10:00–13:00 and 16:00–24:00, Sat 00:00–02:00 and 14:00–20:00. Users differ (morning people, night owls, irregular meals), so the app assumes nothing: meals, sleep and everything else are simply the gaps. They are painted on a weekly grid in Settings. Classes inside a slot are still subtracted, so a slot can be painted over a class. A session never crosses midnight; a slot to 24:00 and one from 00:00 the next day are two windows, and each counts toward its own calendar day's max.

Older setup files give one span per day (`day_bounds`); it becomes that day's slot on the first save from Settings. Their events are kept as events (a weekly one may be real, like frisbee), and any that are only meals can be deleted from the week view.

### Timetable (set once per semester, editable)

Weekly classes, each with a subject, a weekday and a time:

```
RP       Tue 10:00–11:00, Thu 10:00–11:00
CMO      Mon 11:00–12:00, Wed 11:00–12:00
DAA Lab  Fri 14:00–17:00
```

- It holds every week until the timetable is changed (the semester dates don't limit it yet).
- **One-time changes** don't touch the weekly pattern:
  - **Cancel:** one class on a date (holiday, prof absent). It blocks no time and creates no lecture item.
  - **Extra:** a one-off class on a date and time (makeup lecture). It blocks that time and creates a lecture item like any other class.
  - **Move:** a cancel plus an extra, e.g. Tue 22/9 → Sat 26/9.
  - Done from the UI: click a class on the week view to cancel or move it; **+ Extra class** on the subject page adds one. The subject page lists every change with an undo. Cancelling an extra class removes it; cancelling a moved class leaves its old date cancelled; moving an extra or moved class changes its time. A cancel applies to the subject's classes on that whole date.

- **Weekly classes from the UI:** **+ Add subject** takes the subject's weekly classes (and whether each class gets a lecture item); a subject's page adds or removes a weekly class. A class may not overlap another class of any subject. Removing a weekly class removes the lectures of its past classes that aren't done, since lectures are made from the current timetable.

### Fixed-time events (optional, editable)

Things with set times and nothing to plan: a meeting, gym, a club, a shift. In the setup file they are **commitments**. Meals and sleep don't need them; they are the gaps between study slots. Each event is either:

- **weekly:** days and a time, e.g. Gym Mon/Wed/Fri 07:00–08:00, with optional **skipped dates** for weeks it doesn't happen, or
- **one-off:** a date and a time, e.g. club meeting on 3 Oct 18:00–19:00.

Both block their time like a class. They are added from **+ Add → Fixed-time event**, shown on the week view, and clicking one edits it, skips that one day (a weekly event), or deletes it. Any change triggers a re-plan, so study planned in that slot moves elsewhere.

An event marked **work** ("counts as study time", e.g. ICPC practice 22:00–23:30) also counts toward that day's work max, so the rest of the day's study shrinks by its length. Fixed weekly activities in a subject, lab or other area count the same way.

**Free time = study slots − classes − exams − fixed-time events − fixed weekly activities.** Everything the plan contains (study, hobbies and breaks) goes inside free time.

### Areas

Each area has a name and a kind:

| Kind | Examples | Holds |
|---|---|---|
| **subject** | RP, CMO, DAA | work items, milestones, timetable classes, weekly activities |
| **lab** | DAA Lab | work items (lab record, viva prep), milestones (viva), timetable sessions |
| **hobby** | Workout, Guitar | weekly activities |
| **other** | Errands, club work | work items |

A subject or lab also has a **weight** (default: its credits). The weight breaks ties when two items are equally urgent.

Every area has a **colour**, saved in the setup file. A new area gets the first colour no other area has, so adding or deleting an area never recolours the rest.

### Work items (inside a subject, lab or other area)

- **Title**
- **Type** (`type`): `study` (a chapter, topic, lecture or notes), `assignment` (problem set, lab, homework) or `other` (a project or anything else). Chosen when the task is added; a task without one counts as `other` (the app never guesses from the title). Generated lectures are study. Used by the Stats insights (pace by type, usual time).
- **Estimate:** optional. If not given, it is the area's learned average for that kind of item. Before any data exists, it defaults to 1 hr per lecture hour for lecture study and 1.5 hr for anything else.
  - Estimates are learned **per area**. An RP lecture and a CMO lecture can take very different times, but two RP lectures are comparable.
- **Due:** optional, the item's own deadline (e.g. assignment submission).
- **Counts toward:** optional, a milestone in the same area.
- **Available from:** optional. The item can't be worked on before this time (e.g. a lecture item before its class ends).
- **Pace:** `asap` (default) or `steady`.
  - **asap:** finish as early as the constraints allow (see Rules).
  - **steady:** spread evenly over the days until the target finish. This is for work that can't run ahead of the class, like textbook reading that follows whatever the professor covers.
- **Sections:** optional, an **unordered** checklist (e.g. Axler 5A, 5B, Meyer 7.1). The item's estimate is the sum of its sections' estimates (default 1.5 hr each). Sessions are for the item as a whole ("LAA reading"). After each session the user ticks the sections they actually covered, and the remaining estimate is the sum of the unticked ones. The plan never needs to know the order.
- **Depends on:** other items in the same area, each marked:
  - **hard:** this item can't start until that one is done.
  - **soft:** that one should come first, but in a time crunch it may be pushed to after this item's finish-by date. This is the v0.1 "prep" rule.

An item's **finish-by** is the earliest of its own due date and the date of the milestone it counts toward. With neither, it has no deadline.

**Editing and deleting.** After it is added, an item's title, hours still needed and deadline (a due date, an exam it counts toward, or none) can be changed. A renamed item keeps its id, so its logged progress stays with it. New hours go into the setup file while the item has no progress yet, and into the progress log (`adjust`) after that. **Deleting** is not the same as finishing: a deleted item was never real work (added by mistake, a cancelled assignment). It leaves the setup file, any dependency on it is dropped, and its progress entries are removed. Revision items are changed through their milestone's revision budget instead.

### Milestones (inside a subject or lab)

A dated event with no work of its own: quiz, midsem, endsem, viva, project demo. **+ Add exam / quiz** asks which it is: a quiz (`"type": "quiz"`) is planned exactly like an exam, only its revision defaults to 1 hr instead of 6 hr in the form, and it is labelled "quiz" in Exam effort.

- **Time:** optional, e.g. CMO midsem 8 Oct 11:30–13:00. Exams usually take a class slot. A timed exam blocks its time, and a class of the same subject that overlaps it doesn't happen, so it creates no lecture item. Without a time, the milestone is at 00:00 that day.
- **Syllabus until:** optional date. Lectures after it don't count toward this exam; they count toward the next one. By default, every lecture before the exam counts.
- **Focus window:** `focus_hr` (default 24). See Rules.
- **Revision budget** (default 3 hr). It becomes a "Revise for <milestone>" item that counts toward the milestone and softly depends on every other item that does, so revision comes after all the lectures. It is available from 7 days before the exam (`revision_days`) and has no 1-day buffer, since the evening before the exam is when revision happens. Editing the revision item in the UI changes only its hours: before any progress they replace the milestone's `revision_hr`, after that they go in the progress log like any task's. The add-exam form suggests 6 hr.

### Generated lecture items

Lecture items are **opt-in per subject** (`lecture_items: true`). Subjects studied another way, e.g. from textbook sections with a steady pace, or that have no lecture study at all, leave it off. The subject page has a checkbox for it: turning it off drops every lecture of that subject, old ones included (the classes still block their time); turning it back on brings back the lectures since `tracking_since` that aren't done or deleted.

For each class of an opted-in subject (not cancelled), the app creates:

```
<subject> lecture <dd/mm>
  available from: end of that class
  counts toward:  the subject's next exam after the class whose syllabus includes it
  depends on:     the subject's previous lecture (hard: lectures are studied in date order)
  estimate:       the subject's lecture-study time (given, later learned)
```

- Lectures are named by **date**, not number, since numbers are easy to lose track of.
- Only classes from **now** on are generated. Past lectures still to study are listed by date as the subject's **pending lectures** and become the same kind of item, available immediately.
- Future classes inside the planning horizon are generated **ahead of time**, so the plan reserves room for them. Otherwise front-loading would fill every free hour, and Thursday's lecture would find no space.
- The user can edit, delete or re-link a generated lecture like any other item. Since lectures aren't written in the setup file, the change is kept as a **lecture override** on the subject, by class date: its hours, a due date, the exam it counts toward (or none), or `deleted`. An override that matches the defaults again is removed. A deleted lecture is skipped, and the next one depends on the one before it.

### Weekly activities

Recurring time that never "finishes": a hobby (Workout 3 × 30 min/week), or regular study in a subject (LAA 1.5 hr/week). Any area can have them. In a hobby area they are self time. In a subject, lab or other area they are work and count toward the daily work cap.

- **Sessions per week** and **session length**, e.g. 3 × 30 min. Alternatively a **weekly total**, e.g. 3 hr, with a minimum session length (default 30 min).
- **Preferred days:** optional, e.g. Mon/Wed/Fri
- **Fixed schedule:** optional, exact days and times, e.g. Mon/Wed/Fri 07:00–07:30. A fixed activity blocks its time like a class, and the engine doesn't place it. It still counts toward the weekly total in the output.

A flexible activity gets at most one session per day, so it is spread over the week.

An activity can be renamed, switched between the two forms, or deleted. Deleting it drops it from every week, and an area left with nothing in it (e.g. a hobby area) goes too.

### Balance settings

- **Work time per day, max and min:**
  - **Max:** required, a hard cap. Front-loading needs one, or "as soon as possible" means "everything today".
  - **Min:** optional, a soft target (default 0). It only matters when you'd rather keep a routine going. A day that falls short because no work is left isn't reported.
  - Both are set **per weekday** in Settings, under each day of the study-slot grid, e.g. Sun max 0 for no work on any Sunday. In the file, the most used max is the default and the other days override it.
- **Date overrides:** for one particular date, limit its study slots to bounds, change its work max/min, or both, e.g. `2026-10-04: max 0` (only that Sunday off) or `2026-10-11: bounds 10:00–14:00`. A date override beats the weekday setting, which beats the default. A max of 0 stops work but still leaves room for hobby activities; changing the bounds limits everything.
- Minimum session length (default 30 min)
- Maximum session length (default 90 min), e.g. 120 for someone who can sit for 2 hr. Longer work is split into sessions.

Work time counts subject, lab and other items and weekly activities. Hobby activities are not work.

### Session status update (after each scheduled session)

The plan numbers each task's sessions, continuing from the ones already logged ("AIDS Project 2 - session 2"); a task done in one session gets no number. After a session, the user records it:

- **session:** a session of that task is done. The user may give the **hours still needed** (`--left`), which becomes the time left, so a wrong estimate corrects itself; `--left 0` means the task is finished. Without it, time left = previous time left − the session. The hours worked default to the length of that planned session (`--spent` if different), and the session number is assigned automatically.
- **done:** the task is finished. A done lecture is the only way a lecture item disappears.
- **missed:** logged only (for later statistics). Time moving on already moves the work.
- **reopen:** a task marked done isn't finished after all; its hours still needed are given.
- **adjust:** the task was edited and its hours still needed changed.
- **session** or **done** on a weekly activity counts one session toward this week's target.

A logged action can be undone right after (it is taken back out of the log).

If the sessions use up the whole estimate without the task being finished, every plan warns the user to mark it done or log the next session with `--left`.

Each entry keeps its date, session number and hours worked, so time per day and per task can be read off the log for learning estimates later. (Automatic timing with start/stop comes with the UI.)

Entries go to a **progress log** (`data/progress.json`), separate from the setup file, and every plan applies it. From the command line:

```
python status.py session "project 2" --left 4
python status.py done "rp 8/9"
python status.py missed "ps 6"
python status.py list [query]
```

Names match loosely: every word must appear in the title or in its initials ("ps 6" finds "RP Problem Set 6"). If several things match, the user is asked to be more specific.

### Time and tracking

- **Now** is the real clock. `--now` plans as if at another time, for testing.
- **Tracking since:** the date the user started with the app. Every class after it gets a lecture item, including past ones, until it is marked done. Lectures from before it come from each subject's pending list.

### The online site: demo and published planners

`app.py --hosted` serves the site for trying HeadStart. `/` is a home page with the demo and the steps to run it on your own computer, which is the recommended way to use it for real (the planner stays on your device). Planners are folders under the planners directory (`setup.json`, `progress.json`, `plan.json`, `plan.txt`), reached at `/p/<id>/`; a thin layer in front of the app turns `/p/<id>/api/...` into `/api/...` for that planner's files, so every feature works per planner. There are two kinds: the **demo** (`demo/`, at `/p/demo/`), one shared planner made blank on first use, never saved anywhere, wiped by **Reset demo** and blank again after a restart; and **published** planners (`kept/<id>/`), copies of someone's own planner sent by `publish.py` to show it online, at a private 12-character id that is the only key (no login). Visitors can't create planners. Only what a planner needs is stored (setup, progress log, last plan): no account, name, email, cookies or analytics, and the app logs no visits. A blank planner has default study slots (08:00-13:00, 14:00-19:00, 20:00-23:00 daily, max 6 h a day, sessions 45-120 min) and no semester; while it has no semester the page shows a first screen asking for the semester's name and dates, then a getting-started guide. Without `--hosted` the app is the single planner in `data/`, as before (made blank, starting on the first screen, if `data/` has no setup file).

Online it runs on Render's free plan (Docker, India time zone, waitress), built from the public repo. Render's free server loses its files when it restarts or sleeps, so with `HEADSTART_DATASET` set the published planners (`kept/`, never the demo) are restored from that private Hugging Face dataset at start and changed files are pushed back every 2 minutes (`scheduler/sync.py`): at most the last 2 minutes can be lost. `POST /api/publish` (only with the `PUBLISH_TOKEN` secret in the `X-Publish-Token` header) replaces a published planner's data with a copy sent by `publish.py`, which is how the owner's laptop planner is shown online; it can't overwrite the demo.

### Insights from the progress log (Stats page)

`scheduler/insights.py`, shown on the Stats page below the daily chart, all from everything logged since tracking began:

- **Pace:** per work subject, from finished items, by **type of task**: study (generated lectures count here), assignment, other, and revision: the actual/estimate ratio for each. An item marked done with under 25% of its estimate logged is left out as covered elsewhere (e.g. tasks studied during revision, or skipped while ill); it says nothing about pace. For generated lectures it also gives average planned vs actual time; with 2+ finished whose average differs from the subject's lecture estimate by more than 15 min, the page offers that average (rounded to 10 min) as the new estimate. It applies only to lectures of classes still to come: the lectures of classes already held are pinned to the time they were planned with (a lecture override), so the current plan doesn't jump. Ratios for tasks are only shown. Each type's **usual time** (average actual time, rounded to 10 min) is given once 3+ of that type are finished in that subject, and pre-fills *Time needed* when adding a task of that type.
- **Exam effort:** minutes logged on every item that counts toward each exam or quiz, split by type (study, assignment, other, revision); past ones with nothing logged (before tracking) are left out.
- **Study times:** minutes studied per hour of day and per weekday, counting hours, not sessions. A log entry is written when a session ends, so it is taken to start `spent_hr` earlier and its minutes are spread over the hours it covered. Only work areas count (as in the Today tally). The best stretch is the 3-hour window (wrapping past midnight) with the most minutes, shown once there are 2 h of data.

## Re-planning triggers

The plan is re-built whenever:

- an item, milestone, weekly activity or fixed-time event is added, changed or deleted,
- progress is recorded (session, done or missed), or
- the timetable, the study slots or the daily limits change, including a one-time change (cancel, extra or moved class).

A class ending needs no re-plan, because its lecture item is already in the plan.

## Output

- **Plan:** a day-by-day list of sessions, as in v0.1 (sessions as long as their work, starts on a 10-min grid), with classes shown as fixed blocks.
- **Next task:** what to do now, or next, with a one-line reason (e.g. "RP quiz on Thu; Lecture 7 is needed for it").
- **Area view:** for each subject, progress toward each milestone (e.g. "RP endsem: 9 of 14 items done, on track, 2 days of lead").
- **Other this week:** a side panel, for the week shown, with everything that isn't a subject: tasks in non-subject areas (hours left, due date, time planned that week), fixed-time events, and hobby targets (done + planned vs. target). Subjects are covered by the deadlines panel.
- **Today tally:** next to the next task, hours studied today and tasks finished today, from the progress log. Hours count logged sessions in work areas, plus any unlogged hours given when a task is marked done on its subject page (e.g. a task the plan couldn't fit) (a hobby like a workout doesn't count; a weekly activity logged without hours counts its usual session length); a task counts if it was finished today and is still done, so undo/reopen take it back off. Each hobby session logged today also counts as a task done (but not as study hours).
- **Stats page:** for a chosen week or calendar month, hours studied per day (bar chart, with each day's minimum study as a dashed mark and a ✓ on days that reached it), plus total and daily average, sessions, tasks done, the current and best streak (days in a row with some study; a streak survives a today with nothing logged yet) and days on target (days at or above their minimum, counting only days that have a minimum). Each day is counted with the same rules as the Today tally, from the first logged day to today; a task counts on the day it was last finished.
- **Weekly study:** a subject's own weekly activities (e.g. LAA study 1.5 hr/week) are shown on that subject's page, with this week's time vs. the target.
- **Change summary** and **infeasibility report:** as in v0.1, with milestone wording, e.g. "RP endsem needs 18 hr before Oct 20 but only 12 hr fit under your 5 hr/day cap".
- **Format:** JSON plus a readable text printout, and the local web UI (week and month views, subject pages, Settings).
- **Typing durations:** every time box in the UI accepts minutes or hours (`50m`, `1h 30m`, `1h30`, `1:30`, or plain hours like `1.5`) and is pre-filled the same way (e.g. `1h 15m`). The UI converts to hours before sending, so the API and files still use hours.

## Rules

- **Dates:** a due date given without a time means 23:59 that day. A milestone given without a time means the start of that day, since the exam happens during the day.
- **Steady items** are spread evenly over the days until their target finish. This is the v0.1 spread rule, now applied only to `pace: steady`.
- **As soon as possible:** every other item is scheduled as early as its constraints allow: available-from, hard dependencies, the daily work cap, weekly activities and free time.
- **Deadlines:** every item finishes by its finish-by date. The target is **1 day before** it. If there isn't a full day, the buffer shrinks to whatever fits.
- **Urgency order:** when items compete for the same time, the one with the nearest finish-by goes first. Area weight breaks ties.
- **Hard dependencies** are always kept. **Soft dependencies** are kept unless that breaks a deadline. Then the order is dropped: the dependent item may start first, but the prerequisite still has to meet its own finish-by. The problems list says so.
- **Focus window:** in the 24 hr before an exam (`focus_hr`, per exam; 0 turns it off), only that subject's work is planned. Hobbies are still fine. The window never reaches back past the end of an earlier exam, so two exams close together each get their own stretch.
- **Revision in exam order:** each exam's revision softly depends on the revision for the previous exam, across subjects, so exams are revised one at a time.
- **A heavy day on one subject before its exam is fine.** There is deliberately no per-subject daily cap: sometimes one subject genuinely needs most of a day.
- **Weekly activities:** each weekly target is reserved before other work fills the days, and never exceeded. The current week's target is the full target minus the sessions already logged; a partial last week gets a prorated target, rounded up.
- **Breaks:** a fixed 10-min break between consecutive sessions
- **Splitting:** sessions of at most the maximum session length
- **Within a day,** earlier slots are preferred.
- **Stability:** a re-plan starts from the last saved plan (`out/plan.json`) and keeps every session where it was unless something is gained. Moving a task to or from a day costs 1 per slot in stage 1, so freed time is filled with urgent work but low-urgency work isn't shuffled for nothing; moving a session within a day costs 20 per slot in stage 2, more than starting earlier saves. Re-planning with nothing changed moves nothing; a done task, a new task or a cancelled class changes only what it has to.
- **No overload:** the daily work cap is never exceeded. If work doesn't fit, it is left out and reported, never silently squeezed in. Work with no deadline that runs past the end of the plan (the horizon) isn't reported: nothing is late, and it is planned once the horizon moves on.

## Engine

The same two-stage CP-SAT design as v0.1.

### Time grid

The horizon runs from now until the latest milestone or due date, and always at least 7 days ahead. Free slots come from the study slots minus classes, exams, fixed-time events and fixed weekly activities, on a 10-min grid. Free windows too short to hold any session (e.g. the 15 min between two classes) are left out.

### Stage 1: allocate (minutes per item per day)

Per unit `u` (a work item) and day `d`: `a[u,d]`, `n[u,d]`. Also `broken[e]` for each soft edge `e`, and minutes `h[k,d]` per flexible weekly activity `k` (fixed ones are already removed from free time).

| Rule | Linear form | vs. v0.1 |
|---|---|---|
| Work time | `Σ_d a[u,d] + unscheduled[u] = need[u]` | same |
| Deadline | `a[u,d]` only counts slots before finish-by | finish-by is derived |
| Available from | `a[u,d] = 0` for days before it; slots before it on that day don't count | new |
| Hard dependency u→v | `v` runs on day `d` only if `u` is done by the end of `d` | was the subtask chain; now any edge |
| Soft dependency u→v | same as hard, unless `broken[e] = 1` | was prep/core |
| Session length | `min_len · n ≤ a ≤ min(max_len, longest window it may use) · n` | max is a setting; a session can't outgrow its window |
| Sessions per window | `Σ n + Σ held ≤ Σ_windows ⌊(len + break) / (shortest session + break)⌋` | new: a 1.5 hr window holds one 50-min session |
| Part-day room | for every part of a day that some items or weekly activities are confined to (available from mid-day, due mid-day, or kept out by an exam's focus window), their `a + breaks` fit in its slots | new |
| Day capacity | `Σ a + Σ n (breaks) + Σ_k h[k,d] ≤ free[d] + 1` | weekly activities instead of self time |
| Work cap | `Σ_u a[u,d] ≤ max_work[d]` (date override → weekday → default) | now required, per day |
| Work minimum | `Σ_u a[u,d] + short_work[d] ≥ min_work[d]` (a soft target: a short day is not listed as a problem, since it only happens when no more work is available, e.g. when ahead) | per day |
| Weekly target | `Σ_{d ∈ week} h[k,d] + short[k,week] ≥ target[k]`; `h[k,d] ∈ {0} ∪ [min session, max session]`; work activities also count toward the work cap | replaces min self per day |

Stage 1 stops once its plan is proven within 1% of the best possible (`ALLOCATE_GAP`); proving the last 1% took 3–4× as long and only moved work by minutes.

Objective (minimize, most important first):

1. Unscheduled work (10000 per slot), which feeds the infeasibility report
2. Weekly-activity shortfall (1000)
3. Soft dependency broken (500)
4. Work inside the 1-day buffer (50)
5. Under the daily work minimum (20)
6. **Uneven spread** of steady items: `|load[u,d] − average|` over the days up to the target finish (5)
7. **Earliness** of asap items: each slot of `u` on day `d` costs `(d − earliest day of u) · w`, where `w` is higher for a nearer finish-by and a heavier area (1–5). This replaces v0.1's "no-deadline tasks late" term.

### Stage 2: place

Per day, place the allocation into slots, with sessions between the minimum and maximum length, a break after at most the maximum length of work, breaks between units and same-day dependency order. Each weekly-activity session is placed as one block. Among equal layouts, fewer sessions and earlier slots win. Days are independent, so they are solved in parallel. The solver starts from a quick greedy layout (pieces in dependency order, packed into the earliest slots they may use, a break after each session), so a full day is found within its 2 s.

If part of an item doesn't fit on a day, stage 1 runs again with that item capped on that day at what did fit, so the rest moves to another day (up to 5 rounds; each round's search starts from the last round's answer). If a day's search runs out of time, the day keeps a quick greedy layout (dependency order, breaks, session lengths all kept) or the solver's answer if it placed more, never an empty day: a timed-out search must not cap the day's work at zero. Since stage 1 knows about windows, focus windows and sessions per window, this is rare: a re-plan usually takes one round and well under 15 s.

### Always a plan

As in v0.1, every goal that can fail has a slack variable, and the non-zero slacks are the infeasibility report.

## Scope (v0.2)

- **In:** the data model (areas, items, milestones, dependencies, weekly activities), timetable → free time and lecture items, the as-soon-as-possible objective, JSON + text output
- **Built since:** session status updates (progress log, `status.py`), real clock, tracking since, numbered sessions, undo/reopen, and a local web UI (`app.py`): week and month views, log a session, add tasks, exams, subjects and fixed-time events, edit and delete tasks, lectures and weekly activities, subject pages, a Today tally (hours studied, tasks finished), **+ Add** that first asks what kind of thing (study task, fixed-time event, or a flexible hobby / self time, e.g. Guitar 3 x 1 hr a week, which gets a hobby area of its own), one-time class changes (cancel, move, extra class), stable re-plans, and Settings (semester, study-slot grid, daily max/min, session lengths), a Stats page (with pace, exam effort and study-time insights), a per-subject lectures on/off switch, editable revision hours, editable exams, + Add subject with weekly classes, and an online mode (`--hosted`, live on Render) with a home page, a shared demo with Reset, published planners (publish.py), a first screen and a getting-started guide. Areas keep their colours. A Desktop shortcut (`headstart.vbs`) (re)starts the server in the background and opens the browser, with no terminal; a server already running is stopped first, so the latest code always runs.
- **Carried over, still not built:** the change summary after a re-plan, learning estimates from actual times
- **Later:** a "taking a break" button that re-plans from now, editing the weekly timetable and date overrides from the UI, semester dates bounding the plan, a first-run setup, rewards and levels, morning brief, importing the timetable from the college portal
