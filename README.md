# MeetingMind

**[▶ Live demo](https://hrutishaa.github.io/meetingmind/)** · [![CI](https://github.com/hrutishaa/meetingmind/actions/workflows/ci.yml/badge.svg)](https://github.com/hrutishaa/meetingmind/actions/workflows/ci.yml) · MIT

MeetingMind turns a meeting transcript into **action items with owners and due dates** and **team analytics** (who talked, how balanced the meeting was, what got decided), then stores meetings in SQL so you can track KPIs across weeks.

It's a note-taking tool for meetings you run: paste a transcript, upload WebVTT from Zoom/Meet/Teams, or use live transcription in the browser.

## Try it

Open the [live demo](https://hrutishaa.github.io/meetingmind/), click **Load sample**, or press **🎙 Live transcribe** (Chrome/Edge) and talk. Everything runs in your browser.

```bash
pip install -e ".[dev]"
python -m meetingmind analyze samples/weekly_sync.txt   # JSON: stats + action items
python -m pytest -q                                     # 25 tests
```

From the sample 75-second sync, it finds 5 action items across 3 owners, for example:

| Owner | Task | Due | Evidence |
|---|---|---|---|
| Marcus | Rerun the cohort query with the fixed timezone | friday | "I'll rerun the cohort query with the fixed timezone by Friday." |
| Dana | Send the customer the updated CSV export spec | — | "Dana, can you send the customer the updated CSV export spec?" |
| Priya | Book the room and send the invite | tomorrow | "I will book the room and send the invite tomorrow." |

## How it works

| Module | What it does |
|---|---|
| `meetingmind/transcript.py` | Parses `[00:01:23] Name: text`, `Name: text` and WebVTT `<v Name>` cues into timed utterances; estimates timing when there are no timestamps. |
| `meetingmind/actions.py` | Finds commitments ("I'll…"), assignments ("Dana, can you…", "Marcus to…") and explicit "Action item:" lines, plus due dates. Never invents an owner who wasn't in the meeting, and keeps the verbatim sentence as evidence. |
| `meetingmind/analytics.py` | Talk time and share per speaker, a balance score (1 − normalized Gini), questions, interruptions (overlapping turns), decisions. |
| `meetingmind/store.py` | SQLite schema (meetings, utterances, action_items) and named KPI queries: open items by owner, completion rate by team, average meeting length, talk share, items per meeting. |
| `meetingmind/llm.py` | Optional LLM extraction with any `complete(prompt) -> str` client. Output is **grounded**: an item is kept only if its owner is a real participant and its evidence quote appears in the transcript; otherwise it falls back to the rule engine. |

### Why rules first, LLM second?
Rules are free, instant, deterministic and easy to test, so they're the baseline and the fallback. The LLM path adds recall on messy speech, but model output is checked against the transcript before anyone sees it, which catches hallucinated tasks and owners.

### Demo parity
The browser demo (`docs/index.html`) is a JavaScript port of the same logic. CI runs `scripts/demo_parity.js` to check that the demo and the Python package extract identical action items from the sample.

## Roadmap
FastAPI service, streaming WebSocket ingestion, BYO-key LLM mode with an eval set, a cross-meeting KPI dashboard, and Slack/Linear/Jira export. See [ROADMAP.md](ROADMAP.md).
