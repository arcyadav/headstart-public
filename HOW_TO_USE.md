# HeadStart: how to use it

Run everything from the project folder in PowerShell, with the virtual environment active:

```
.venv\Scripts\Activate.ps1
```

(Type the commands as shown below. Don't put `!` in front; that only works inside Claude Code.)

## The app (easiest)

**No terminal:** double-click **HeadStart** on the Desktop (or `headstart.vbs` in the project folder). It starts the server in the background and opens the browser. If the server is already running it is restarted first, so clicking it after an update always gives you the new version. The server keeps running until you log out or shut down; its output goes to `out\server.log`. To stop it early, end the `python.exe` process in Task Manager.

Or from the terminal:

```
python app.py
```

Then open **http://localhost:5000**. The first plan takes a few seconds.

- **Week view:** your sessions coloured by subject; classes, exams and ICPC in grey/red/striped; shaded bands are exam focus windows. Arrows switch weeks.
- **Today** (top card, right): hours you've studied today and tasks you've finished today. It counts what you log, so log each session as you finish it. A hobby session counts as a task done, not as study hours; hover the hours to see how many study sessions.
- **Typing time:** every time box on the page takes minutes or hours: `50m`, `1h 30m`, `1h30`, `1:30`, or plain hours like `1.5`.
- **Click a session** when you've done it: fill in time worked and time still needed, then
  - **Save, task continues:** the task has more to do; the rest is re-planned.
  - **Save and finish task:** the task is completely done.
  - **Edit task:** change its title, hours still needed, and due date / exam it's for / no deadline. For a lecture you can change its hours and whether it counts toward an exam (its name stays). Also on each row of **Subjects**. For a revision item you can change only its hours (new exams start at 6h). **Delete task** (in the same dialog) removes a task that shouldn't be there, which is different from marking it done.
  - **Edit activity** (on a Workout / LAA study session, under **Weekly study** on the subject's page, or **Edit** next to a hobby in the *Other this week* panel): rename it, change sessions per week and hours per session (or hours a week), or **Delete activity** to drop it from every week.
- **Undo:** after every save, a bar at the bottom offers **Undo** for 15 seconds.
- **+ Add** first asks what you're adding (you can switch at the top of each form):
  - **Study:** subject, **type** (*Study*: a chapter, topic, lecture or notes; *Assignment*: problem set, lab, homework; *Other*: a project or anything else), title, hours, and a due date or the exam it's for. **Edit task** can change the type; each task's type shows on its subject page.
  - **Hobby / self time:** guitar, workout, reading. Say how often (e.g. 3 sessions of 1 h a week, or 3 h a week) and the plan fits the sessions into your free time. Edit or delete it from a session on the week view or the *Other this week* panel.
  - **Fixed-time event** for things with set times and nothing to plan: a meeting, gym, a club. Once on a date, or every week on chosen days. Tick **Counts as study time** for things like ICPC practice. Click an event on the week grid to edit it, **Skip this day** (a repeating one), or **Delete** it.
- **Stats:** how much you studied per day, for a week or a calendar month (arrows go back in time). Tiles show total hours (and the daily average), sessions, tasks done, your streak (days in a row with some study) and how many days you reached that day's minimum study hours from Settings. In the chart the dashed mark is each day's minimum and a ✓ means you reached it; hover a bar for details. It only counts sessions you log. Below the chart, from everything you've logged since you started:
  - **Exam effort:** hours logged on everything that counts toward each exam or quiz, split into lectures & study, assignments, other and revision ("so far" for upcoming ones).
  - **When you study:** hours studied by hour of day and by weekday, and the 3-hour stretch you study most. A session is taken to start "time spent" before you logged it, so it's approximate.
- **Subjects:** every lecture and task per subject. **+ Add subject** (next to the subject tabs) adds a subject, lab or other area with its weekly classes, and whether to add a lecture to study after each class. On a subject's page, **+ Weekly class** adds a class that happens every week and **Remove** takes one away (its lectures that aren't done go too); two classes can't overlap. **Edit** next to an exam changes its name, date, time or syllabus end; its tasks and revision stay with it. **Delete exam** (in the same dialog) removes it and its revision: lectures that counted toward it count toward the subject's next exam, and tasks linked to it keep their own due date (or have no deadline). Tick several and **Mark done** (handy for old lectures, or a task the plan couldn't fit); it asks how many hours you spent that you haven't logged yet, so they count in today's hours; **Reopen** a task marked done by mistake.
- **Settings:** semester name and dates (the header then shows "week N of M"); **when you can study**, painted on a weekly grid (drag to mark or unmark half hours, any time of day or night; classes are skipped automatically; copy a day to Mon-Fri, Sat-Sun or all days); max and min study hours for each day; and shortest/longest session.
- **Click a class** on the week view to **cancel** it (frees the time, its lecture goes too) or **move** it to another date and time. **+ Extra class** on a subject's page adds a makeup class. The subject page lists these changes, each with **Undo**. Untick **Add a lecture to study after each class** there to stop lectures for that subject (all its lectures go, old ones too; the classes still block their time); tick it to turn them back on.
- **Other this week** (side panel): tasks that aren't for a subject, your fixed-time events and hobbies, for the week shown in the grid. Click one to edit it.
- **Guide:** a short getting-started card (add your subjects, set when you can study, add your work). It shows on a new online planner until **Got it**; the **Guide** button brings it back.
- **Re-plan:** rebuilds the plan from the current time. Sessions stay where they were unless something changed (a task done, added or moved, a class cancelled), so the plan you saw last night is the plan you get in the morning.

Stop the app with Ctrl+C in its terminal. After changing the code, restart it.

### On your phone

The **HeadStart** desktop shortcut starts the app with `--lan` (from a terminal: `python app.py --lan`), so a phone on the **same Wi-Fi** can open it too. **Settings → Use it on your phone** shows the link and a QR code: scan it with the phone's camera, then choose **Add to Home screen** in the browser menu for a HeadStart icon. It is the same planner, so everything you do on the phone is saved on the computer; it works while the computer is on and HeadStart is running. On a phone the week view shows one day at a time (← → to move, **Today** to come back) and the top buttons scroll sideways. Anyone on the same Wi-Fi with the link can open it, so use it on your home Wi-Fi. It works on any network both are on: home Wi-Fi, college Wi-Fi, or the phone's own hotspot with the laptop connected to it (the most private, and the planner traffic stays local). The computer's address differs per network, so after switching networks scan the new QR code. HeadStart uses plain `http` (a computer on your own network has no HTTPS certificate), so Chrome warns that the connection isn't secure: tap **Continue to site**. If Chrome shows **ERR_SSL_PROTOCOL_ERROR**, it switched to `https` on its own: type the address starting with `http://`, or turn off **Settings → Privacy and security → Security → Always use secure connections**. If the phone still can't connect, check that no VPN or ad-blocker app is on, and allow Python through Windows Firewall (Windows asks the first time).

### The online site (`--hosted`)

```
python app.py --hosted --planners planners
```

serves the online version, which is for trying HeadStart: a home page at `/` with **Open the demo** and the steps to run it on your own computer (recommended for real use: your planner stays on your device). The demo (`/p/demo/`) is one shared planner that starts on the first screen (semester name and dates; study slots 08:00-13:00, 14:00-19:00 and 20:00-23:00 every day, at most 6 h a day, all changeable in Settings). It is never saved anywhere: **Reset demo** wipes it, and it starts blank again whenever the server restarts. Nobody can keep a planner of their own on the site.

**Putting it online** (Render's free plan): the site builds from the public repo (github.com/arcyadav/headstart-public) with the `Dockerfile`. Its environment variables: `HEADSTART_DATASET` (a private Hugging Face dataset, e.g. `Arcyadav/headstart-planners`, that keeps published planners, since a free Render server forgets its files when it restarts; changes are saved there every 2 minutes; the demo is never saved), `HF_TOKEN` (a Hugging Face token that can write to it) and `PUBLISH_TOKEN` (any long secret, also kept in `.publish.json` for publish.py). A free Render server sleeps after 15 minutes without visitors; the next visit takes about a minute to wake it.

**Your own planner online:** `python publish.py` copies `data/sem5.json` and `data/progress.json` to your private link on the site and prints it. Your laptop copy stays the real one; run it again to update the online copy. If you start on a fresh download with no `data/` files, the app makes a blank planner and starts on the first screen.

## Your plan from the terminal

```
python plan.py
```

This plans from the current time and saves the plan to **`out/plan.txt`** (open it in VS Code). It shows:

- **Now / Next:** what to do now, and why.
- **Day by day:** your sessions, plus classes, exams and ICPC blocks.
- **Deadlines:** for each exam and task, how much is done and how far ahead you are.
- **Weekly:** workout and LAA study against their weekly targets.
- **Problems:** anything that doesn't fit. If there are none, it says "everything fits".

You don't need to run `plan.py` after logging: every `status.py` command re-plans by itself.

## Logging your work

Tasks that take several sittings are split into numbered sessions in the plan, e.g. `AIDS Project 2 - session 2`. After you finish one, log it:

| You did... | Command |
|---|---|
| A session, and you know roughly how much is left | `python status.py session "project 2" --left 4` |
| A session, and it went as planned | `python status.py session "project 2"` |
| The last session: the task is finished | `python status.py session "project 2" --left 0` |
| A task in one go (e.g. a lecture) | `python status.py done "rp 8/9"` |
| A workout | `python status.py session workout` |
| Skipped a session | nothing needed; the plan moves it by itself |

What the app does with it:

- **Session number:** assigned automatically. You never type it.
- **Hours worked:** taken from how long that session was in the plan. If you worked a different amount, add `--spent`, e.g. `python status.py session "project 2" --left 4 --spent 2`.
- **Time left:** `--left` sets it. Without `--left`, the app subtracts the session from what was left.
- **Reply:** it confirms, e.g. `Recorded: AIDS Project 2 session 2 done (1h00). 4h00 left.`, then shows what's next and any problems.

### Naming things

You don't need the exact title. Every word you type just has to appear in it, or in its initials:

| You type | It finds |
|---|---|
| `"rp 8/9"` | RP lecture 8/9 |
| `"ps 6"` | RP Problem Set 6 |
| `"project 2"` | AIDS Project 2 |
| `"daa assignment 5"` | DAA Assignment 5 |
| `"revise cmo"` | Revise for CMO Midsem |

If a name matches several things, the app lists them and asks you to be more specific. To see what's still open:

```
python status.py list            # everything
python status.py list rp         # just RP
```

### Lectures

Every class of a subject with lectures on (the checkbox on its subject page) creates a lecture item, e.g. `RP lecture 1/10`. It stays in the plan until you mark it done, even if the class was days ago:

```
python status.py done "rp 1/10"
```

## Changing your setup (`data/sem5.json`)

Edit the file, then run `python plan.py`.

| Change | Where, and an example |
|---|---|
| New task | the subject's `"items"`: `{"title": "Assignment 7", "estimate_hr": 3, "due": "2026-10-20"}` |
| Task that counts toward an exam | add `"counts_toward": "daa-midsem"` |
| Exam | the subject's `"milestones"`: `{"id": "rp-endsem", "title": "RP Endsem", "date": "2026-11-20", "time": ["10:00", "12:00"], "revision_hr": 6}` |
| Exam syllabus stops early | add `"syllabus_until": "2026-10-01"` to the exam |
| One-off event (contest, meeting) | `"commitments"`: `{"title": "ICPC contest", "date": "2026-10-03", "time": ["13:30", "16:30"], "work": true}` (`"work": true` counts it as study) |
| Study limit for a weekday | `"settings"` → `"weekday"`: `"sun": {"max_work_hr": 4}` |
| Study limit for one date | `"settings"` → `"dates"`: `"2026-10-04": {"max_work_hr": 0}` (day off) |
| Class cancelled / makeup | the subject's `"timetable_changes"`: `{"cancel": "2026-10-13"}` or `{"extra": ["2026-10-17", "10:00", "11:30"]}` |

## Quick fixes

- **A deadline doesn't fit** (listed under Problems): raise the max for a day or two before it (see above), lower an estimate, or move a commitment.
- **"Sessions add up to the whole estimate":** if the task is finished, run `done`; if not, log your next session with `--left`.
- **Logged something by mistake:** click **Undo** in the app, or run `python status.py undo` (takes back the last entry). A task marked done by mistake: **Reopen** on the Subjects page, or `python status.py reopen "project 2" --left 6`.
