# MeetingMind

**[▶ Live demo](https://hrutishaa.github.io/meetingmind/)** · [![CI](https://github.com/hrutishaa/meetingmind/actions/workflows/ci.yml/badge.svg)](https://github.com/hrutishaa/meetingmind/actions/workflows/ci.yml) · MIT

MeetingMind turns a meeting transcript into **action items with owners and due dates** and **team analytics** (who talked, how balanced the meeting was, what got decided), then stores meetings in SQL so you can track KPIs across weeks.

It's a note-taking tool for meetings you run: paste a transcript, upload WebVTT from Zoom/Meet/Teams, or use live transcription in the browser.

## Try it

Open the [live demo](https://hrutishaa.github.io/meetingmind/), click **Load sample**, or press **🎙 Live transcribe** (Chrome/Edge) and talk. Everything runs in your browser.

```bash
pip install -e ".[dev]"
python -m meetingmind analyze samples/weekly_sync.txt   # JSON: stats + action items
python -m meetingmind eval                              # precision/recall on 10 labeled meetings
python -m pytest -q                                     # 69 tests
```

From the sample 75-second sync, it finds 5 action items across 3 owners, for example:

| Owner | Task | Due | Evidence |
|---|---|---|---|
| Marcus | Rerun the cohort query with the fixed timezone | friday | "I'll rerun the cohort query with the fixed timezone by Friday." |
| Dana | Send the customer the updated CSV export spec | — | "Dana, can you send the customer the updated CSV export spec?" |
| Priya | Book the room and send the invite | tomorrow | "I will book the room and send the invite tomorrow." |

## REST API

A FastAPI service wraps the same engine so other tools can push transcripts in and track action items to done.

```bash
pip install -e ".[api]"
uvicorn meetingmind.api:app --reload          # interactive docs at http://localhost:8000/docs
# or
docker build -t meetingmind . && docker run -p 8000:8000 -v mm:/data meetingmind
```

| Endpoint | What it does |
|---|---|
| `POST /meetings` | Body `{title, held_on, team, transcript}`. Parses the transcript, stores it, returns the meeting with its action items and talk stats. |
| `GET /meetings?team=` | Meetings with item and open-item counts. |
| `GET /meetings/{id}/items?status=open` | Action items for one meeting, optionally filtered by status. |
| `GET /meetings/{id}/stats` | Talk share, balance score, questions, interruptions, decisions. |
| `PATCH /items/{id}` | Partial update: mark done, reassign the owner, fix the task or due date. Only listed fields can change. |
| `GET /kpis`, `GET /kpis/{name}` | The named SQL KPIs (open items by owner, completion rate by team, and more). |

```bash
curl -X POST localhost:8000/meetings -H 'content-type: application/json' \
  -d '{"title":"Standup","held_on":"2026-10-31","team":"web","transcript":"Ann: I will fix the login bug today.\nBo: ok"}'
curl -X PATCH localhost:8000/items/1 -H 'content-type: application/json' -d '{"status":"done"}'
curl localhost:8000/kpis/completion_rate_by_team
```

Design notes: inputs are validated by Pydantic (bad dates, empty transcripts and unknown statuses return 422), SQL values are always bound parameters, `PATCH` only touches a fixed column allowlist, and CI builds the Docker image and smoke-tests it end to end.

## Live streaming (WebSocket)

`/ws/live` takes transcript chunks while the meeting is happening and sends action items back as soon as the sentence that contains them is finished, so the notes build up during the call instead of after it.

```bash
uvicorn meetingmind.api:app                    # or the Docker image
pip install websockets
python scripts/live_client.py samples/weekly_sync.txt --save "Weekly sync" --team data
```

```text
ITEM: Marcus: Rerun the cohort query with the fixed timezone [due friday]
ITEM: Dana: Draft the FAQ for the support team [due next week]
ITEM: Marcus: Add retry with backoff to the sync job
ITEM: Priya: Book the room and send the invite [due tomorrow]
ITEM (late): Dana: Send the customer the updated CSV export spec
SUMMARY: 10 turns, 5 items, meeting_id=1
```

| You send | You get back |
|---|---|
| `{"type":"chunk","text":"I'll send the","speaker":"Ana","t":12.5}` (speaker and `t` optional; `Name: text` lines and plain-text frames also work) | `action_item` events as sentences complete, and a `turn` event each time a speaker turn ends |
| `{"type":"end","save":{"title":"...","held_on":"2026-11-03","team":"data"}}` (`save` optional) | Any `late` items, a `summary` with stats and the final item list (plus `meeting_id` if saved), then the socket closes |

How turns are detected: a different speaker closes the open turn, a pause of `pause_s` seconds (default 2, set with `/ws/live?pause_s=`) closes it too, and a chunk without a speaker continues the current one, like speech-to-text partials. Some items need context that only arrives later, such as "Dana, can you send the spec?" said before Dana has spoken, so when the stream ends MeetingMind runs the full extractor once more and sends those as `late` (and retracts any live guess that changed). The tests check that the final list always equals the batch result for the same transcript, even when it is streamed three words at a time. Bad frames get an `error` event and the stream stays open; chunk and session sizes are capped.

## LLM mode (bring your own key) and evals

MeetingMind works offline with rules, and can also use your own LLM through any OpenAI-compatible API: OpenAI, Groq, Together, OpenRouter, or a local Ollama or vLLM server. No SDK is needed; the adapter uses the standard library.

```bash
export MEETINGMIND_LLM_API_KEY=sk-...                     # optional for local servers
export MEETINGMIND_LLM_BASE_URL=https://api.openai.com/v1 # or http://localhost:11434/v1 for Ollama
export MEETINGMIND_LLM_MODEL=gpt-4o-mini
python -m meetingmind analyze samples/weekly_sync.txt --llm
python -m meetingmind eval --llm                          # rules vs. your model, same golden set
```

The LLM only proposes items. Each one is kept only if its owner is a real participant and its evidence quote appears word for word in the transcript, so a made-up task or owner never reaches the team. Rate limits and 5xx errors are retried with exponential backoff and jitter (honoring `Retry-After`); auth errors fail fast; any provider failure falls back to the rule engine so a meeting is never lost. The key is read from the environment and never logged or included in errors.

**Evaluation.** [`evals/golden.jsonl`](evals/golden.jsonl) holds 10 hand-labeled meetings (standups, a customer kickoff, a WebVTT design review, a data review, and meetings with no action items, hedges like "I'll be honest", and questions that are not assignments). A predicted item counts as correct when the owner matches and the task has at least 50% content-word overlap with the label; matching is one-to-one, so duplicates count as false positives, and empty cases score cleanly instead of dividing by zero.

Rule baseline today:

| Extractor | Precision | Recall | F1 | Due accuracy | TP | FP | FN |
|---|---|---|---|---|---|---|---|
| rules | 0.74 | 0.77 | 0.76 | 0.94 | 17 | 6 | 5 |

The misses are what rules can't do: pronouns and implicit volunteering ("I can take that", "Leave that with me"), follow-ups without a trigger phrase ("Ben, also write tests..."), and polite phrases that look like commitments ("Let me know if anything changes"). That's the gap LLM mode is meant to close, and `eval --llm` measures whether it does on your model. CI runs the eval on every push and fails if the rule baseline drops below F1 0.75 or precision 0.70.

## How it works

| Module | What it does |
|---|---|
| `meetingmind/transcript.py` | Parses `[00:01:23] Name: text`, `Name: text` and WebVTT `<v Name>` cues into timed utterances; estimates timing when there are no timestamps. |
| `meetingmind/actions.py` | Finds commitments ("I'll…"), assignments ("Dana, can you…", "Marcus to…") and explicit "Action item:" lines, plus due dates. Never invents an owner who wasn't in the meeting, and keeps the verbatim sentence as evidence. |
| `meetingmind/analytics.py` | Talk time and share per speaker, a balance score (1 − normalized Gini), questions, interruptions (overlapping turns), decisions. |
| `meetingmind/store.py` | SQLite schema (meetings, utterances, action_items) and named KPI queries: open items by owner, completion rate by team, average meeting length, talk share, items per meeting. |
| `meetingmind/api.py` | FastAPI app: create meetings, list and update action items, read KPIs; OpenAPI docs at `/docs`; `/ws/live` WebSocket. |
| `meetingmind/stream.py` | Live session: speaker turn detection, incremental action items, late items and retractions at the end of the stream. |
| `meetingmind/providers.py` | Bring-your-own-key adapter for OpenAI-compatible chat APIs with retries, backoff and safe errors. |
| `meetingmind/evaluate.py` | Golden-set scoring: one-to-one matching, precision, recall, F1, due-date accuracy, markdown report. |
| `meetingmind/llm.py` | Optional LLM extraction with any `complete(prompt) -> str` client. Output is **grounded**: an item is kept only if its owner is a real participant and its evidence quote appears in the transcript; otherwise it falls back to the rule engine. |

### Why rules first, LLM second?
Rules are free, instant, deterministic and easy to test, so they're the baseline and the fallback. The LLM path adds recall on messy speech, but model output is checked against the transcript before anyone sees it, which catches hallucinated tasks and owners.

### Demo parity
The browser demo (`docs/index.html`) is a JavaScript port of the same logic. CI runs `scripts/demo_parity.js` to check that the demo and the Python package extract identical action items from the sample.

## Roadmap
A cross-meeting KPI dashboard, and Slack/Linear/Jira export. See [ROADMAP.md](ROADMAP.md).
