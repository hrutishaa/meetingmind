"""FastAPI service: store meetings, review action items, read KPIs.

Run locally:   uvicorn meetingmind.api:app --reload   (docs at /docs)
Docker:        docker build -t meetingmind . && docker run -p 8000:8000 meetingmind
Live:          WebSocket /ws/live streams transcript chunks in and action items out (see stream.py)
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .analytics import analyze
from .store import KPIS, Store
from .stream import DEFAULT_PAUSE_S, StreamError, StreamSession
from .transcript import parse_transcript

MAX_TRANSCRIPT_CHARS = 200_000


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["Weekly sync"])
    held_on: date = Field(examples=["2026-10-26"])
    team: str = Field(default="default", min_length=1, max_length=80)
    transcript: str = Field(
        min_length=1,
        max_length=MAX_TRANSCRIPT_CHARS,
        description="'[00:01:23] Name: text', 'Name: text' lines, or WebVTT with <v Name> cues.",
    )


class ItemOut(BaseModel):
    id: int
    meeting_id: int
    owner: str
    task: str
    due: Optional[str]
    evidence: str
    status: Literal["open", "done"]


class MeetingMeta(BaseModel):
    """Sent with {"type": "end", "save": {...}} to store a live meeting when it ends."""

    title: str = Field(min_length=1, max_length=200)
    held_on: date
    team: str = Field(default="default", min_length=1, max_length=80)


class MeetingOut(BaseModel):
    id: int
    title: str
    held_on: str
    team: str


class MeetingCreated(MeetingOut):
    stats: dict
    action_items: list[ItemOut]


class MeetingSummary(MeetingOut):
    items: int
    open_items: int


class ItemPatch(BaseModel):
    """Only the fields you send are changed (e.g. mark done, reassign, fix a due date)."""

    status: Optional[Literal["open", "done"]] = None
    owner: Optional[str] = Field(default=None, min_length=1, max_length=80)
    task: Optional[str] = Field(default=None, min_length=1, max_length=500)
    due: Optional[str] = Field(default=None, max_length=40)


def create_app(db_path: str | None = None) -> FastAPI:
    store = Store(db_path or os.environ.get("MEETINGMIND_DB", ":memory:"))
    app = FastAPI(
        title="MeetingMind API",
        version=__version__,
        description="Meeting transcripts to action items with owners and due dates, plus team KPIs.",
    )
    app.state.store = store

    def _meeting_or_404(meeting_id: int) -> dict:
        m = store.get_meeting(meeting_id)
        if m is None:
            raise HTTPException(404, f"meeting {meeting_id} not found")
        return m

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/meetings", response_model=MeetingCreated, status_code=201)
    def create_meeting(body: MeetingIn) -> dict:
        utts = parse_transcript(body.transcript)
        if not utts:
            raise HTTPException(422, "no speaker turns found in transcript")
        mid = store.save_meeting(body.title, body.held_on.isoformat(), utts, team=body.team)
        return {**store.get_meeting(mid), "stats": analyze(utts).to_dict(), "action_items": store.items(mid)}

    @app.get("/meetings", response_model=list[MeetingSummary])
    def list_meetings(team: Optional[str] = None) -> list[dict]:
        return store.list_meetings(team)

    @app.get("/meetings/{meeting_id}", response_model=MeetingOut)
    def get_meeting(meeting_id: int) -> dict:
        return _meeting_or_404(meeting_id)

    @app.get("/meetings/{meeting_id}/stats")
    def meeting_stats(meeting_id: int) -> dict:
        _meeting_or_404(meeting_id)
        return analyze(store.utterances(meeting_id)).to_dict()

    @app.get("/meetings/{meeting_id}/items", response_model=list[ItemOut])
    def meeting_items(meeting_id: int, status: Optional[Literal["open", "done"]] = Query(None)) -> list[dict]:
        _meeting_or_404(meeting_id)
        return store.items(meeting_id, status)

    @app.patch("/items/{item_id}", response_model=ItemOut)
    def patch_item(item_id: int, body: ItemPatch) -> dict:
        changes = body.model_dump(exclude_unset=True)
        if any(v is None for k, v in changes.items() if k != "due"):
            raise HTTPException(422, "status, owner and task cannot be null")
        if store.get_item(item_id) is None:
            raise HTTPException(404, f"item {item_id} not found")
        return store.update_item(item_id, **changes)

    @app.get("/kpis")
    def list_kpis() -> list[str]:
        return sorted(KPIS)

    @app.get("/kpis/{name}")
    def kpi(name: str) -> list[dict]:
        if name not in KPIS:
            raise HTTPException(404, f"unknown KPI '{name}'; see GET /kpis")
        return store.kpi(name)

    @app.websocket("/ws/live")
    async def live(ws: WebSocket, pause_s: float = DEFAULT_PAUSE_S) -> None:
        """Live meeting notes over a WebSocket.

        Client sends JSON messages:
          {"type": "chunk", "text": "I'll send the deck", "speaker": "Dana", "t": 12.5}
              (speaker and t are optional; "Dana: text" or "[00:00:12] Dana: text" lines work too,
               and a plain-text frame is treated as a chunk)
          {"type": "end", "save": {"title": "...", "held_on": "2026-11-03", "team": "data"}}
              (save is optional)
        Server sends: ready, turn, action_item, item_retracted, error, and a final summary
        (with meeting_id when saved), then closes.
        """
        await ws.accept()
        session = StreamSession(pause_s=min(max(pause_s, 0.5), 60.0))
        await ws.send_json({"type": "ready", "pause_s": session.pause_s})
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw) if raw.lstrip().startswith("{") else {"type": "chunk", "text": raw}
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "detail": "invalid JSON"})
                    continue
                kind = msg.get("type", "chunk") if isinstance(msg, dict) else None
                if kind == "chunk":
                    try:
                        events = session.push(msg.get("text"), speaker=msg.get("speaker"), t=msg.get("t"))
                    except StreamError as exc:
                        await ws.send_json({"type": "error", "detail": str(exc)})
                        continue
                    for event in events:
                        await ws.send_json(event)
                elif kind == "end":
                    meta = None
                    if msg.get("save") is not None:
                        try:
                            meta = MeetingMeta.model_validate(msg["save"])
                        except ValidationError as exc:
                            await ws.send_json({"type": "error", "detail": exc.errors(include_url=False)[0]["msg"]})
                            continue
                    events = session.finish()
                    summary = events[-1]
                    if meta is not None and session.utterances:
                        summary["meeting_id"] = store.save_meeting(
                            meta.title, meta.held_on.isoformat(), session.utterances, team=meta.team
                        )
                    for event in events:
                        await ws.send_json(event)
                    await ws.close()
                    return
                else:
                    await ws.send_json({"type": "error", "detail": "type must be 'chunk' or 'end'"})
        except WebSocketDisconnect:
            return  # client left mid-meeting; nothing was saved

    return app


app = create_app()
