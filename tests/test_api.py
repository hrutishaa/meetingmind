from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from meetingmind.api import create_app  # noqa: E402

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


@pytest.fixture()
def client():
    return TestClient(create_app(":memory:"))


def post_sample(client, **over):
    body = {"title": "Weekly sync", "held_on": "2026-10-26", "team": "data", "transcript": SAMPLE, **over}
    r = client.post("/meetings", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/meetings", "/meetings/{meeting_id}/items", "/items/{item_id}"} <= set(paths)


def test_create_meeting_returns_items_and_stats(client):
    m = post_sample(client)
    assert m["id"] == 1 and m["held_on"] == "2026-10-26"
    assert len(m["action_items"]) == 5
    assert {i["owner"] for i in m["action_items"]} == {"Dana", "Marcus", "Priya"}
    assert all(i["status"] == "open" and i["evidence"] in SAMPLE for i in m["action_items"])
    assert m["stats"]


def test_items_filter_and_patch_flow(client):
    m = post_sample(client)
    item = m["action_items"][0]
    r = client.patch(f"/items/{item['id']}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert r.json()["owner"] == item["owner"]  # untouched fields stay put
    open_items = client.get(f"/meetings/{m['id']}/items", params={"status": "open"}).json()
    assert len(open_items) == 4
    r = client.patch(f"/items/{item['id']}", json={"owner": "Priya", "due": None})
    assert r.json()["owner"] == "Priya" and r.json()["due"] is None


def test_kpis_reflect_updates(client):
    m = post_sample(client)
    client.patch(f"/items/{m['action_items'][0]['id']}", json={"status": "done"})
    rates = client.get("/kpis/completion_rate_by_team").json()
    assert rates == [{"team": "data", "items": 5, "done_pct": 20.0}]
    assert "open_items_by_owner" in client.get("/kpis").json()
    assert client.get("/kpis/drop_table").status_code == 404


def test_list_meetings_by_team(client):
    post_sample(client)
    post_sample(client, title="Standup", team="web", transcript="Ann: I'll fix the login bug today.\nBo: ok")
    assert [m["title"] for m in client.get("/meetings").json()] == ["Weekly sync", "Standup"]
    web = client.get("/meetings", params={"team": "web"}).json()
    assert web == [{"id": 2, "title": "Standup", "held_on": "2026-10-26", "team": "web", "items": 1, "open_items": 1}]


def test_validation_and_404s(client):
    assert client.post("/meetings", json={"title": "x", "held_on": "not-a-date", "transcript": "A: hi"}).status_code == 422
    assert client.post("/meetings", json={"title": "x", "held_on": "2026-10-26", "transcript": "   "}).status_code == 422
    assert client.get("/meetings/99").status_code == 404
    assert client.get("/meetings/99/items").status_code == 404
    assert client.patch("/items/99", json={"status": "done"}).status_code == 404
    post_sample(client)
    assert client.patch("/items/1", json={"status": "archived"}).status_code == 422
    assert client.patch("/items/1", json={"owner": None}).status_code == 422


def test_store_update_item_rejects_unknown_columns():
    from meetingmind.store import Store

    with pytest.raises(ValueError):
        Store().update_item(1, evidence="x")
