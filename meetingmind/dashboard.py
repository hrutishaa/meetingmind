"""Cross-meeting team dashboard: action-item follow-through, owner load, meeting load, talk balance trend.

Every number comes from SQL over the store (meetings, utterances, action_items). The only step done
in Python is the talk-balance score, which reuses `analytics.balance_score` on per-speaker talk
time that SQL already summed, so a meeting gets the same score here as in its own report.

"Overdue" means: still open and its resolved due date (`due_on`) is before `as_of`.
Items whose due phrase could not be pinned to a date are counted as "no due date", never guessed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from importlib import resources

from .analytics import balance_score
from .store import Store
from .transcript import parse_transcript

DUE_SOON_DAYS = 7

# Meetings in scope (all teams, or one). Every query below starts from this CTE.
_SCOPE = "WITH m AS (SELECT * FROM meetings WHERE :team IS NULL OR team = :team)"
_OPEN = "a.status = 'open'"
# `due_on IS NOT NULL` keeps these 0/1 (never NULL) so SUM() counts undated items as not overdue.
_OVERDUE = f"({_OPEN} AND a.due_on IS NOT NULL AND a.due_on < :as_of)"
_SOON = f"({_OPEN} AND a.due_on IS NOT NULL AND a.due_on BETWEEN :as_of AND :soon)"

DASHBOARD_SQL = {
    "summary": f"""{_SCOPE}
        SELECT (SELECT COUNT(*) FROM m) AS meetings,
               COUNT(a.id) AS action_items,
               COALESCE(SUM({_OPEN}), 0) AS open,
               COALESCE(SUM(a.status = 'done'), 0) AS done,
               ROUND(100.0 * SUM(a.status = 'done') / NULLIF(COUNT(a.id), 0), 1) AS completion_pct,
               COALESCE(SUM({_OVERDUE}), 0) AS overdue,
               COALESCE(SUM({_SOON}), 0) AS due_soon,
               COALESCE(SUM({_OPEN} AND a.due_on IS NULL), 0) AS open_no_due_date
        FROM m LEFT JOIN action_items a ON a.meeting_id = m.id""",
    "owners": f"""{_SCOPE}
        SELECT a.owner, COUNT(*) AS items,
               SUM({_OPEN}) AS open, SUM({_OVERDUE}) AS overdue, SUM({_SOON}) AS due_soon,
               SUM(a.status = 'done') AS done,
               ROUND(100.0 * SUM(a.status = 'done') / COUNT(*), 1) AS completion_pct
        FROM action_items a JOIN m ON m.id = a.meeting_id
        GROUP BY a.owner ORDER BY open DESC, overdue DESC, a.owner""",
    "teams": f"""{_SCOPE},
        len AS (SELECT meeting_id, MAX(end_s) - MIN(start_s) AS s FROM utterances GROUP BY meeting_id),
        it AS (SELECT a.meeting_id, COUNT(*) AS items, SUM(a.status = 'done') AS done,
                      SUM({_OPEN}) AS open, SUM({_OVERDUE}) AS overdue
               FROM action_items a GROUP BY a.meeting_id)
        SELECT m.team, COUNT(*) AS meetings,
               ROUND(SUM(COALESCE(len.s, 0)) / 60.0, 1) AS meeting_minutes,
               ROUND(AVG(COALESCE(len.s, 0)) / 60.0, 1) AS avg_minutes,
               COALESCE(SUM(it.items), 0) AS items, COALESCE(SUM(it.open), 0) AS open,
               COALESCE(SUM(it.overdue), 0) AS overdue,
               ROUND(100.0 * SUM(it.done) / NULLIF(SUM(it.items), 0), 1) AS completion_pct
        FROM m LEFT JOIN len ON len.meeting_id = m.id LEFT JOIN it ON it.meeting_id = m.id
        GROUP BY m.team ORDER BY meeting_minutes DESC, m.team""",
    "meetings": f"""{_SCOPE}
        SELECT m.id, m.title, m.held_on, m.team,
               date(m.held_on, '-' || ((CAST(strftime('%w', m.held_on) AS INTEGER) + 6) % 7) || ' days') AS week,
               ROUND(COALESCE((SELECT MAX(end_s) - MIN(start_s) FROM utterances u WHERE u.meeting_id = m.id), 0) / 60.0, 1)
                   AS minutes,
               (SELECT COUNT(*) FROM action_items a WHERE a.meeting_id = m.id) AS items,
               (SELECT COUNT(*) FROM action_items a WHERE a.meeting_id = m.id AND {_OPEN}) AS open
        FROM m ORDER BY m.held_on, m.id""",
    "talk": f"""{_SCOPE}
        SELECT u.meeting_id, u.speaker, SUM(u.end_s - u.start_s) AS talk_s
        FROM utterances u JOIN m ON m.id = u.meeting_id GROUP BY u.meeting_id, u.speaker""",
    "overdue_items": f"""{_SCOPE}
        SELECT a.id, a.meeting_id, m.title AS meeting, m.team, a.owner, a.task, a.due, a.due_on,
               CAST(julianday(:as_of) - julianday(a.due_on) AS INTEGER) AS days_overdue
        FROM action_items a JOIN m ON m.id = a.meeting_id
        WHERE {_OVERDUE} ORDER BY days_overdue DESC, a.id LIMIT 20""",
}


def build_dashboard(store: Store, as_of: date | None = None, team: str | None = None) -> dict:
    as_of = as_of or date.today()
    params = {"team": team, "as_of": as_of.isoformat(), "soon": (as_of + timedelta(days=DUE_SOON_DAYS)).isoformat()}
    q = {name: store._rows(sql, params) for name, sql in DASHBOARD_SQL.items()}

    talk: dict[int, list[float]] = defaultdict(list)
    for r in q["talk"]:
        talk[r["meeting_id"]].append(r["talk_s"])
    meetings = []
    for m in q["meetings"]:
        secs = talk.get(m["id"], [])
        total = sum(secs)
        m["balance"] = round(balance_score([s / total for s in secs]), 3) if total else None
        meetings.append(m)

    weeks: dict[str, list[dict]] = defaultdict(list)
    for m in meetings:
        weeks[m["week"]].append(m)
    weekly = []
    for week in sorted(weeks):
        ms = weeks[week]
        bal = [m["balance"] for m in ms if m["balance"] is not None]
        weekly.append({
            "week": week,
            "meetings": len(ms),
            "minutes": round(sum(m["minutes"] for m in ms), 1),
            "items": sum(m["items"] for m in ms),
            "avg_balance": round(sum(bal) / len(bal), 3) if bal else None,
        })

    return {
        "as_of": params["as_of"],
        "team": team,
        "due_soon_days": DUE_SOON_DAYS,
        "summary": q["summary"][0],
        "owners": q["owners"],
        "teams": q["teams"],
        "weekly": weekly,
        "meetings": meetings,
        "overdue_items": q["overdue_items"],
    }


# --- sample data for the CLI and the live demo ------------------------------------------

SAMPLE_AS_OF = date(2026, 11, 13)


def load_sample(store: Store | None = None) -> Store:
    """Load the bundled sample team (fictional meetings) and mark the items listed under `done` as done."""
    store = store or Store()
    data = json.loads(resources.files("meetingmind").joinpath("data/team_meetings.json").read_text(encoding="utf-8"))
    for m in data["meetings"]:
        mid = store.save_meeting(m["title"], m["held_on"], parse_transcript(m["transcript"]), team=m["team"])
        items = store.items(mid)
        for i in m.get("done", []):
            store.update_item(items[i]["id"], status="done")
    return store


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def render_text(d: dict) -> str:
    s, pct = d["summary"], _pct
    lines = [
        f"MeetingMind dashboard as of {d['as_of']}" + (f" · team {d['team']}" if d["team"] else " · all teams"),
        (
            f"{s['meetings']} meetings · {s['action_items']} action items · {s['open']} open · "
            f"{s['done']} done ({pct(s['completion_pct'])}) · {s['overdue']} overdue · "
            f"{s['due_soon']} due in {d['due_soon_days']} days · {s['open_no_due_date']} open with no due date"
        ),
        "",
        f"{'Owner':<14}{'open':>6}{'overdue':>9}{'due soon':>10}{'done':>6}{'done %':>8}",
    ]
    lines += [f"{o['owner']:<14}{o['open']:>6}{o['overdue']:>9}{o['due_soon']:>10}{o['done']:>6}{pct(o['completion_pct']):>8}"
              for o in d["owners"]]
    lines += ["", f"{'Team':<12}{'meetings':>9}{'minutes':>9}{'avg min':>9}{'items':>7}{'overdue':>9}{'done %':>8}"]
    lines += [f"{t['team']:<12}{t['meetings']:>9}{t['meeting_minutes']:>9.1f}{t['avg_minutes']:>9.1f}"
              f"{t['items']:>7}{t['overdue']:>9}{pct(t['completion_pct']):>8}" for t in d["teams"]]
    lines += ["", f"{'Week of':<12}{'meetings':>9}{'minutes':>9}{'items':>7}{'avg balance':>13}"]
    lines += [f"{w['week']:<12}{w['meetings']:>9}{w['minutes']:>9.1f}{w['items']:>7}"
              f"{'—' if w['avg_balance'] is None else format(w['avg_balance'], '.2f'):>13}" for w in d["weekly"]]
    if d["overdue_items"]:
        lines += ["", "Overdue:"]
        lines += [f"  {i['owner']}: {i['task']} (due {i['due_on']}, {i['days_overdue']}d late, from {i['meeting']})"
                  for i in d["overdue_items"]]
    return "\n".join(lines)
