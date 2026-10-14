"""Load an input file and print a quick sanity summary (no scheduling yet)."""

import sys
from datetime import datetime

from scheduler import load_input


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def main(path: str) -> None:
    inp = load_input(path, progress="data/progress.json")
    print(f"now: {inp.now:%a %d %b %H:%M}   horizon ends: {inp.horizon_end:%a %d %b %H:%M}\n")

    for area in inp.areas:
        print(f"{area.name} ({area.kind.value})")
        for m in area.milestones:
            print(f"  * {m.title} on {m.at:%a %d %b %H:%M}")
        for i in area.items:
            fb = f"by {i.finish_by:%a %d %b %H:%M}" if i.finish_by else "no deadline"
            af = f", from {i.available_from:%a %d %b %H:%M}" if i.available_from else ""
            hard = sum(d.hard for d in i.depends_on)
            soft = len(i.depends_on) - hard
            deps = "".join([f", after {hard} (hard)" if hard else "", f", after {soft} (soft)" if soft else ""])
            print(f"    {i.title:<24} {hm(i.estimate_min):>6}  {fb}{af}{deps}")
        for w in area.weekly:
            form = (f"{w.sessions_per_week} x {hm(w.session_min)}" if w.sessions_per_week
                    else f"{hm(w.weekly_min or 0)} total")
            print(f"    ~ {w.title}: {form} per week{' (fixed)' if w.is_fixed else ''}")
    print()

    print("Daily room for work (free time, capped at the day's max)")
    total_room = 0
    rooms = {}
    for day in inp.days():
        free = sum(int((min(e, inp.horizon_end) - max(s, inp.now)).total_seconds() // 60)
                   for s, e in inp.free_windows_on(day) if e > inp.now and s < inp.horizon_end)
        room = min(free, inp.max_work_on(day))
        rooms[day] = room
        total_room += room
        classes = ", ".join(b.title for b in inp.blocks_on(day) if b.kind == "class")
        print(f"  {day:%a %d %b}  free {hm(free):>6}  work room {hm(room):>6}   {classes}")
    print()

    print("Work due by each date vs. room before it (ignores buffer and hobby time)")
    dated = sorted({i.finish_by for i in inp.items if i.finish_by and i.is_work})
    for fb in dated:
        need = sum(i.estimate_min for i in inp.items if i.is_work and i.finish_by and i.finish_by <= fb)
        room = sum(r for d, r in rooms.items() if datetime.combine(d, datetime.min.time()) < fb)
        flag = "  <-- too much" if need > room else ""
        print(f"  by {fb:%a %d %b %H:%M}: need {hm(need):>7}, room {hm(room):>7}{flag}")
    rest = sum(i.estimate_min for i in inp.items if i.is_work and not i.finish_by)
    print(f"  no deadline: {hm(rest)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/sem5.json")
