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

**https://headstart-1g49.onrender.com**: open it, then **Start my planner** for a planner of your own at a private link
(bookmark it), or **Open the demo** to try a shared one. It runs on a free server that sleeps when
nobody has used it for a while, so the first page can take about a minute to appear.

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
