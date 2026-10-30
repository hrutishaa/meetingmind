"""SQLite storage + KPI queries across meetings (the Business Analyst layer)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .actions import extract_action_items
from .transcript import Utterance

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, held_on TEXT NOT NULL, team TEXT NOT NULL DEFAULT 'default'
);
CREATE TABLE IF NOT EXISTS utterances (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  speaker TEXT NOT NULL, text TEXT NOT NULL, start_s REAL NOT NULL, end_s REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS action_items (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  owner TEXT NOT NULL, task TEXT NOT NULL, due TEXT, evidence TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done'))
);
CREATE INDEX IF NOT EXISTS ix_utt_meeting ON utterances(meeting_id);
CREATE INDEX IF NOT EXISTS ix_items_owner ON action_items(owner, status);
"""

# Named KPI queries so dashboards and tests share one definition.
KPIS = {
    "talk_share_by_speaker": """
        SELECT speaker, ROUND(SUM(end_s - start_s), 1) AS talk_s,
               ROUND(100.0 * SUM(end_s - start_s) / (SELECT SUM(end_s - start_s) FROM utterances), 1) AS pct
        FROM utterances GROUP BY speaker ORDER BY talk_s DESC""",
    "open_items_by_owner": """
        SELECT owner, COUNT(*) AS open_items FROM action_items
        WHERE status = 'open' GROUP BY owner ORDER BY open_items DESC, owner""",
    "completion_rate_by_team": """
        SELECT m.team, COUNT(a.id) AS items,
               ROUND(100.0 * SUM(a.status = 'done') / COUNT(a.id), 1) AS done_pct
        FROM action_items a JOIN meetings m ON m.id = a.meeting_id GROUP BY m.team""",
    "avg_meeting_minutes": """
        SELECT ROUND(AVG(len) / 60.0, 1) AS avg_minutes FROM (
          SELECT MAX(end_s) - MIN(start_s) AS len FROM utterances GROUP BY meeting_id)""",
    "items_per_meeting": """
        SELECT m.id, m.title, m.held_on, COUNT(a.id) AS items
        FROM meetings m LEFT JOIN action_items a ON a.meeting_id = m.id
        GROUP BY m.id ORDER BY m.held_on""",
}


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def save_meeting(self, title: str, held_on: str, utterances: list[Utterance], team: str = "default") -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO meetings (title, held_on, team) VALUES (?, ?, ?)", (title, held_on, team)
            )
            mid = cur.lastrowid
            self.db.executemany(
                "INSERT INTO utterances (meeting_id, speaker, text, start_s, end_s) VALUES (?, ?, ?, ?, ?)",
                [(mid, u.speaker, u.text, u.start, u.end) for u in utterances],
            )
            self.db.executemany(
                "INSERT INTO action_items (meeting_id, owner, task, due, evidence) VALUES (?, ?, ?, ?, ?)",
                [(mid, i.owner, i.task, i.due, i.evidence) for i in extract_action_items(utterances)],
            )
        return mid

    def complete(self, item_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE action_items SET status = 'done' WHERE id = ?", (item_id,))

    def kpi(self, name: str) -> list[dict]:
        cur = self.db.execute(KPIS[name])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
