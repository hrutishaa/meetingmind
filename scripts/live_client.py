"""Replay a transcript into a running MeetingMind server over WebSocket and print live events.

    pip install websockets
    python scripts/live_client.py samples/weekly_sync.txt --url ws://localhost:8000/ws/live
    python scripts/live_client.py samples/weekly_sync.txt --save "Weekly sync" --expect-items 5   # CI smoke

Each transcript line is split into a few word chunks to mimic speech-to-text partials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import websockets


def chunks(line: str, size: int):
    words = line.split()
    for i in range(0, len(words), size):
        yield " ".join(words[i : i + size])


async def run(args) -> int:
    lines = [ln for ln in Path(args.path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    async with websockets.connect(args.url) as ws:
        print(json.loads(await ws.recv()))
        for line in lines:
            # the first chunk carries the "[ts] Name:" prefix; the rest continue that speaker
            for part in chunks(line, args.words):
                await ws.send(json.dumps({"type": "chunk", "text": part}))
                await asyncio.sleep(args.delay)
        end = {"type": "end"}
        if args.save:
            end["save"] = {"title": args.save, "held_on": date.today().isoformat(), "team": args.team}
        await ws.send(json.dumps(end))
        summary = None
        async for raw in ws:
            event = json.loads(raw)
            if event["type"] == "action_item":
                tag = " (late)" if event["late"] else ""
                print(f"ITEM{tag}: {event['owner']}: {event['task']}" + (f" [due {event['due']}]" if event["due"] else ""))
            elif event["type"] == "summary":
                summary = event
                print(f"SUMMARY: {event['turns']} turns, {len(event['action_items'])} items, "
                      f"meeting_id={event.get('meeting_id')}")
            elif event["type"] == "error":
                print("ERROR:", event["detail"], file=sys.stderr)
    if summary is None:
        print("no summary received", file=sys.stderr)
        return 1
    if args.expect_items is not None and len(summary["action_items"]) != args.expect_items:
        print(f"expected {args.expect_items} items", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--url", default="ws://localhost:8000/ws/live")
    p.add_argument("--words", type=int, default=6, help="words per chunk")
    p.add_argument("--delay", type=float, default=0.0, help="seconds between chunks")
    p.add_argument("--save", metavar="TITLE", help="store the meeting when the stream ends")
    p.add_argument("--team", default="default")
    p.add_argument("--expect-items", type=int)
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
