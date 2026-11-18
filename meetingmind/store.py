"""SQLite storage + KPI queries across meetings (the Business Analyst layer)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .actions import extract_action_items
from .dues import resolve_due
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
  owner TEXT NOT NULL, task TEXT NOT NULL, due TEXT, due_on TEXT, evidence TEXT NOT NULL,
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


def _iso(d) -> str | None:
    return d.isoformat() if d else None


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        # check_same_thread=False + a lock lets the API's worker threads share one connection safely.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        """v0.5.0 added action_items.due_on (resolved calendar date); upgrade older databases in place."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(action_items)")}
        with self.lock, self.db:
            if "due_on" not in cols:
                self.db.execute("ALTER TABLE action_items ADD COLUMN due_on TEXT")
            rows = self.db.execute(
                """SELECT a.id, a.due, m.held_on FROM action_items a JOIN meetings m ON m.id = a.meeting_id
                   WHERE a.due IS NOT NULL AND a.due_on IS NULL"""
            ).fetchall()
            self.db.executemany(
                "UPDATE action_items SET due_on = ? WHERE id = ?",
                [(_iso(resolve_due(r["due"], r["held_on"])), r["id"]) for r in rows],
            )

    def save_meeting(self, title: str, held_on: str, utterances: list[Utterance], team: str = "default") -> int:
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO meetings (title, held_on, team) VALUES (?, ?, ?)", (title, held_on, team)
            )
            mid = cur.lastrowid
            self.db.executemany(
                "INSERT INTO utterances (meeting_id, speaker, text, start_s, end_s) VALUES (?, ?, ?, ?, ?)",
                [(mid, u.speaker, u.text, u.start, u.end) for u in utterances],
            )
            self.db.executemany(
                "INSERT INTO action_items (meeting_id, owner, task, due, due_on, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (mid, i.owner, i.task, i.due, _iso(resolve_due(i.due, held_on)), i.evidence)
                    for i in extract_action_items(utterances)
                ],
            )
        return mid

    def complete(self, item_id: int) -> None:
        self.update_item(item_id, status="done")

    # --- read/update helpers used by the API -------------------------------
    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def list_meetings(self, team: str | None = None) -> list[dict]:
        sql = """SELECT m.id, m.title, m.held_on, m.team, COUNT(a.id) AS items,
                        COALESCE(SUM(a.status = 'open'), 0) AS open_items
                 FROM meetings m LEFT JOIN action_items a ON a.meeting_id = m.id"""
        params: tuple = ()
        if team is not None:
            sql += " WHERE m.team = ?"
            params = (team,)
        return self._rows(sql + " GROUP BY m.id ORDER BY m.held_on, m.id", params)

    def get_meeting(self, meeting_id: int) -> dict | None:
        rows = self._rows("SELECT id, title, held_on, team FROM meetings WHERE id = ?", (meeting_id,))
        return rows[0] if rows else None

    def utterances(self, meeting_id: int) -> list[Utterance]:
        rows = self._rows(
            "SELECT speaker, text, start_s, end_s FROM utterances WHERE meeting_id = ? ORDER BY start_s, id",
            (meeting_id,),
        )
        return [Utterance(r["speaker"], r["text"], r["start_s"], r["end_s"]) for r in rows]

    def items(self, meeting_id: int, status: str | None = None) -> list[dict]:
        sql = "SELECT id, meeting_id, owner, task, due, due_on, evidence, status FROM action_items WHERE meeting_id = ?"
        params: tuple = (meeting_id,)
        if status is not None:
            sql += " AND status = ?"
            params += (status,)
        return self._rows(sql + " ORDER BY id", params)

    def get_item(self, item_id: int) -> dict | None:
        rows = self._rows(
            "SELECT id, meeting_id, owner, task, due, due_on, evidence, status FROM action_items WHERE id = ?", (item_id,)
        )
        return rows[0] if rows else None

    _EDITABLE = ("status", "owner", "task", "due")

    def update_item(self, item_id: int, **changes) -> dict | None:
        """Update whitelisted columns of one action item; returns the new row or None if missing."""
        bad = set(changes) - set(self._EDITABLE)
        if bad:
            raise ValueError(f"not editable: {sorted(bad)}")
        if changes.get("status") not in (None, "open", "done"):
            raise ValueError("status must be 'open' or 'done'")
        with self.lock, self.db:
            if "due" in changes:  # keep the resolved date in sync with the spoken phrase
                held = self.db.execute(
                    "SELECT m.held_on FROM action_items a JOIN meetings m ON m.id = a.meeting_id WHERE a.id = ?",
                    (item_id,),
                ).fetchone()
                if held is not None:
                    changes["due_on"] = _iso(resolve_due(changes["due"], held["held_on"]))
            if changes:
                cols = [c for c in (*self._EDITABLE, "due_on") if c in changes]  # fixed column names, values bound
                self.db.execute(
                    f"UPDATE action_items SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                    (*[changes[c] for c in cols], item_id),
                )
        return self.get_item(item_id)

    def kpi(self, name: str) -> list[dict]:
        return self._rows(KPIS[name])
