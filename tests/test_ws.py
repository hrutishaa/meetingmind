from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from meetingmind.api import create_app  # noqa: E402

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


@pytest.fixture()
def client():
    return TestClient(create_app(":memory:"))


def drain(ws):
    out = []
    while True:
        msg = ws.receive_json()
        out.append(msg)
        if msg["type"] == "summary":
            return out


def test_live_stream_saves_meeting_same_as_batch(client):
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json() == {"type": "ready", "pause_s": 2.0}
        for line in SAMPLE.splitlines():
            ws.send_json({"type": "chunk", "text": line})
        ws.send_json({"type": "end", "save": {"title": "Weekly sync", "held_on": "2026-10-26", "team": "data"}})
        events = drain(ws)
    summary = events[-1]
    assert sum(e["type"] == "action_item" for e in events) == 5
    assert summary["meeting_id"] == 1 and len(summary["action_items"]) == 5
    stored = client.get("/meetings/1/items").json()
    assert [(i["owner"], i["task"]) for i in stored] == [(i["owner"], i["task"]) for i in summary["action_items"]]
    assert client.get("/meetings").json()[0]["open_items"] == 5


def test_items_stream_back_per_chunk(client):
    with client.websocket_connect("/ws/live?pause_s=1") as ws:
        assert ws.receive_json()["pause_s"] == 1.0
        ws.send_text("Ana: I'll draft the rollout plan by Thursday.")  # plain text frame
        item = ws.receive_json()
        assert (item["type"], item["owner"], item["due"]) == ("action_item", "Ana", "thursday")
        ws.send_json({"type": "chunk", "speaker": "Ben", "text": "Sounds good.", "t": 4})
        assert ws.receive_json()["type"] == "turn"
        ws.send_json({"type": "end"})
        summary = drain(ws)[-1]
    assert "meeting_id" not in summary and summary["turns"] == 2
    assert client.get("/meetings").json() == []


def test_bad_messages_get_errors_without_closing(client):
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_text("{not json")
        assert ws.receive_json() == {"type": "error", "detail": "invalid JSON"}
        ws.send_json({"type": "chunk", "text": ""})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "dance"})
        assert "chunk" in ws.receive_json()["detail"]
        ws.send_json({"type": "chunk", "text": "Ana: I'll fix the flaky test."})
        ws.receive_json()
        ws.send_json({"type": "end", "save": {"title": "x", "held_on": "not-a-date"}})
        assert ws.receive_json()["type"] == "error"  # stream still open, can retry end
        ws.send_json({"type": "end", "save": {"title": "x", "held_on": "2026-11-03"}})
        assert drain(ws)[-1]["meeting_id"] == 1
