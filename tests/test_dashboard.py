import json
import sqlite3
from datetime import date
from importlib import resources
from pathlib import Path

import pytest

from meetingmind.__main__ import main
from meetingmind.dashboard import SAMPLE_AS_OF, build_dashboard, load_sample, render_text
from meetingmind.store import Store
from meetingmind.transcript import parse_transcript


@pytest.fixture(scope="module")
def sample():
    return build_dashboard(load_sample(), as_of=SAMPLE_AS_OF)


def test_summary_counts(sample):
    s = sample["summary"]
    assert (s["meetings"], s["action_items"], s["open"], s["done"]) == (8, 28, 10, 18)
    assert s["completion_pct"] == 64.3
    assert (s["overdue"], s["due_soon"], s["open_no_due_date"]) == (3, 2, 5)
    assert s["open"] == s["overdue"] + s["due_soon"] + s["open_no_due_date"]


def test_owner_load_is_sorted_by_open_then_overdue(sample):
    owners = sample["owners"]
    assert [o["owner"] for o in owners][:2] == ["Bo", "Dana"]
    bo = owners[0]
    assert (bo["open"], bo["overdue"], bo["done"], bo["completion_pct"]) == (3, 2, 1, 25.0)
    assert sum(o["items"] for o in owners) == sample["summary"]["action_items"]


def test_overdue_items_oldest_first(sample):
    late = sample["overdue_items"]
    assert [(i["owner"], i["due_on"], i["days_overdue"]) for i in late] == [
        ("Bo", "2026-11-06", 7),
        ("Dana", "2026-11-12", 1),
        ("Bo", "2026-11-12", 1),
    ]
    assert all(i["due_on"] < sample["as_of"] for i in late)


def test_team_meeting_load_and_weekly_balance_trend(sample):
    teams = {t["team"]: t for t in sample["teams"]}
    assert set(teams) == {"data", "web"}
    assert teams["data"]["meetings"] == teams["web"]["meetings"] == 4
    assert teams["data"]["meeting_minutes"] > teams["web"]["meeting_minutes"]
    assert [w["week"] for w in sample["weekly"]] == ["2026-10-26", "2026-11-02", "2026-11-09"]
    assert [w["meetings"] for w in sample["weekly"]] == [2, 3, 3]
    assert all(0 <= w["avg_balance"] <= 1 for w in sample["weekly"])
    assert sum(w["items"] for w in sample["weekly"]) == 28


def test_meeting_balance_matches_single_meeting_report(sample):
    from meetingmind.analytics import analyze

    first = sample["meetings"][0]
    raw = json.loads(resources.files("meetingmind").joinpath("data/team_meetings.json").read_text())
    raw = raw["meetings"][0]["transcript"]
    assert first["balance"] == round(analyze(parse_transcript(raw)).balance, 3)
    assert first["week"] == "2026-10-26" and first["items"] == 5


def test_team_filter_and_as_of(sample):
    web = build_dashboard(load_sample(), as_of=SAMPLE_AS_OF, team="web")
    assert web["summary"]["meetings"] == 4 and {o["owner"] for o in web["owners"]} == {"Ann", "Bo", "Cara"}
    early = build_dashboard(load_sample(), as_of=date(2026, 11, 1))
    assert early["summary"]["overdue"] == 0  # everything due before Nov 1 was done
    assert build_dashboard(load_sample(), as_of=SAMPLE_AS_OF, team="nobody")["summary"]["meetings"] == 0


def test_empty_store_has_no_division_by_zero():
    d = build_dashboard(Store(), as_of=SAMPLE_AS_OF)
    assert d["summary"]["meetings"] == 0 and d["summary"]["completion_pct"] is None
    assert d["owners"] == d["teams"] == d["weekly"] == d["overdue_items"] == []
    assert "0 meetings" in render_text(d)


def test_undated_open_items_count_as_zero_not_null():
    st = Store()
    st.save_meeting("Sync", "2026-11-09", parse_transcript("Ann: I'll fix the login bug.\nBo: ok"))
    d = build_dashboard(st, as_of=SAMPLE_AS_OF)
    assert d["owners"] == [
        {"owner": "Ann", "items": 1, "open": 1, "overdue": 0, "due_soon": 0, "done": 0, "completion_pct": 0.0}
    ]
    assert d["summary"]["open_no_due_date"] == 1 and d["teams"][0]["overdue"] == 0


def test_patching_due_reresolves_date():
    st = Store()
    mid = st.save_meeting("Standup", "2026-11-09", parse_transcript("Ann: I'll fix the login bug by Friday.\nBo: ok"))
    item = st.items(mid)[0]
    assert item["due_on"] == "2026-11-13"
    assert st.update_item(item["id"], due="tomorrow")["due_on"] == "2026-11-10"
    assert st.update_item(item["id"], due=None)["due_on"] is None


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "v04.db"
    db = sqlite3.connect(path)  # the v0.4.0 schema, without due_on
    db.executescript("""
        CREATE TABLE meetings (id INTEGER PRIMARY KEY, title TEXT NOT NULL, held_on TEXT NOT NULL, team TEXT NOT NULL DEFAULT 'default');
        CREATE TABLE utterances (id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL,
                                 start_s REAL NOT NULL, end_s REAL NOT NULL);
        CREATE TABLE action_items (id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL, owner TEXT NOT NULL, task TEXT NOT NULL,
                                   due TEXT, evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open');
        INSERT INTO meetings VALUES (1, 'Sync', '2026-11-09', 'data');
        INSERT INTO action_items VALUES (1, 1, 'Ann', 'Fix the bug', 'friday', 'I will fix the bug by Friday.', 'open');
    """)
    db.commit()
    db.close()
    st = Store(path)
    assert st.get_item(1)["due_on"] == "2026-11-13"
    assert build_dashboard(st, as_of=date(2026, 11, 16))["summary"]["overdue"] == 1


def test_cli_dashboard(capsys, tmp_path):
    assert main(["dashboard", "--sample", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["as_of"] == "2026-11-13" and d["summary"]["action_items"] == 28
    assert main(["dashboard", "--sample", "--team", "data"]) == 0
    assert "team data" in capsys.readouterr().out
    assert main(["dashboard", "--db", str(tmp_path / "missing.db")]) == 2


def test_api_dashboard():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from meetingmind.api import create_app

    app = create_app(":memory:")
    load_sample(app.state.store)
    client = TestClient(app)
    d = client.get("/dashboard", params={"as_of": "2026-11-13"}).json()
    assert d["summary"]["overdue"] == 3 and d["owners"][0]["owner"] == "Bo"
    assert client.get("/dashboard", params={"team": "web", "as_of": "2026-11-13"}).json()["summary"]["meetings"] == 4
    assert client.get("/dashboard", params={"as_of": "nope"}).status_code == 422
    items = client.get("/meetings/1/items").json()
    assert items[0]["due_on"] == "2026-10-30"  # "by Friday" in a Monday Oct 26 meeting


def test_live_demo_embeds_the_same_sample_team():
    html = (Path(__file__).parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    embedded = json.loads(html.split("const TEAM = ", 1)[1].split(";\n", 1)[0])
    bundled = json.loads(resources.files("meetingmind").joinpath("data/team_meetings.json").read_text(encoding="utf-8"))
    assert embedded == bundled
    assert embedded["as_of"] == SAMPLE_AS_OF.isoformat()
