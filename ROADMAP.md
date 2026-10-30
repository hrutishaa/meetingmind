# Roadmap

One working, tested piece per milestone.

- [x] **M1 Core (Oct 29, 2026):** transcript parser (timestamped, plain, WebVTT), rule-based action items with owner, due date and verbatim evidence, per-speaker analytics (talk share, balance score, questions, interruptions, decisions), SQLite store with named KPI queries, LLM extraction with grounding checks and rule fallback, CLI, browser demo with live transcription, CI with demo/Python parity check.
- [ ] **M2 API:** FastAPI service (`POST /meetings`, `GET /meetings/{id}/items`, `PATCH /items/{id}`), OpenAPI docs, Dockerfile.
- [ ] **M3 Streaming:** WebSocket endpoint that takes live transcript chunks and emits action items incrementally; speaker turn detection.
- [ ] **M4 LLM mode:** bring-your-own-key provider adapter (OpenAI-compatible), evaluation set of labeled transcripts with precision/recall vs. the rule baseline.
- [ ] **M5 Dashboard:** cross-meeting KPI dashboard (open items by owner, completion rate, meeting load per team, talk balance trend) backed by the SQL in `meetingmind/store.py`.
- [ ] **M6 Integrations:** export action items to Slack / Linear / Jira / CSV, follow-up email draft for the meeting owner.
