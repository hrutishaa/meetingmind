from pathlib import Path

from meetingmind.store import Store
from meetingmind.transcript import parse_transcript

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


def make():
    st = Store()
    st.save_meeting("Weekly sync", "2026-10-26", parse_transcript(SAMPLE), team="data")
    st.save_meeting("Standup", "2026-10-27", parse_transcript("Ann: I'll fix the login bug today.\nBo: ok"), team="web")
    return st


def test_open_items_by_owner():
    rows = make().kpi("open_items_by_owner")
    assert rows[0] == {"owner": "Dana", "open_items": 2}
    assert {r["owner"] for r in rows} == {"Dana", "Marcus", "Priya", "Ann"}


def test_completion_rate_updates():
    st = make()
    st.complete(1)
    rates = {r["team"]: r["done_pct"] for r in st.kpi("completion_rate_by_team")}
    assert rates == {"data": 20.0, "web": 0.0}


def test_talk_share_and_meeting_counts():
    st = make()
    pct = sum(r["pct"] for r in st.kpi("talk_share_by_speaker"))
    assert abs(pct - 100) < 0.5
    assert [r["items"] for r in st.kpi("items_per_meeting")] == [5, 1]
    assert st.kpi("avg_meeting_minutes")[0]["avg_minutes"] > 0
