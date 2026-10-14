# HeadStart

A study planner for your semester. Give it your subjects and weekly classes, exams,
assignments and the times you're free, and it plans when to study each thing so every
deadline is met, then re-plans as you log sessions, finish tasks or classes get cancelled.

- Plans study sessions into the free time you paint on a weekly grid, within your daily study limits.
- Adds a lecture to study after each class, and revision before each exam.
- Finishes work before its deadline in sensible session lengths with breaks, and says what can't fit.
- Keeps the plan stable: a re-plan only moves what something changed.
- Under the hood: a two-stage constraint solver (Google OR-Tools CP-SAT). See `spec.md`.

## Use it online

**https://headstart-1g49.onrender.com** has a demo to try it: set up a semester, add subjects,
exams and tasks, and watch it plan. The demo is shared and isn't kept (Reset wipes it, and so does the
server restarting). It runs on a free server that sleeps when nobody has used it for a while, so the
first page can take about a minute to appear. To use HeadStart for real, run it on your own computer
(below): your planner stays on your device.

## Run it on your own computer

You need Python 3.12.

```
git clone https://github.com/arcyadav/headstart-public.git
cd headstart-public
python -m venv .venv
.venv\Scripts\activate          # Windows (on macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000. The first time, it asks for your semester's dates; your
planner is kept in `data/` on your computer. `HOW_TO_USE.md` explains every feature.

To run the online version yourself: `python app.py --hosted` (or build the `Dockerfile`; that is how the site runs, on Render).
