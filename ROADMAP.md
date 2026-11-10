# Roadmap

One working, tested piece per milestone.

- [x] **M1 Core (Oct 29, 2026):** transcript parser (timestamped, plain, WebVTT), rule-based action items with owner, due date and verbatim evidence, per-speaker analytics (talk share, balance score, questions, interruptions, decisions), SQLite store with named KPI queries, LLM extraction with grounding checks and rule fallback, CLI, browser demo with live transcription, CI with demo/Python parity check.
- [x] **M2 API (Oct 31, 2026):** FastAPI service (`POST /meetings`, `GET /meetings`, `GET /meetings/{id}/items?status=`, `PATCH /items/{id}`, `GET /kpis/{name}`), OpenAPI docs at `/docs`, Dockerfile (non-root, SQLite volume, healthcheck), CI builds the image and smoke-tests it.
- [x] **M3 Streaming (Nov 3, 2026):** `/ws/live` WebSocket takes live transcript chunks and emits action items as each sentence completes; speaker turn detection (speaker change or pause), late items and retractions at end of stream so the final list equals the batch result, optional save to SQL, replay client, CI smoke test against the Docker image.
- [x] **M4 LLM mode (Nov 9, 2026):** bring-your-own-key provider for any OpenAI-compatible API (OpenAI, Groq, OpenRouter, local Ollama/vLLM; stdlib only, retries 429/5xx with backoff and `Retry-After`, key never logged), `analyze --llm`, a 10-meeting labeled golden set, `meetingmind eval` with precision/recall/F1 and due-date accuracy, rules vs. LLM report, and a CI regression gate on the rule baseline.
- [ ] **M5 Dashboard:** cross-meeting KPI dashboard (open items by owner, completion rate, meeting load per team, talk balance trend) backed by the SQL in `meetingmind/store.py`.
- [ ] **M6 Integrations:** export action items to Slack / Linear / Jira / CSV, follow-up email draft for the meeting owner.
