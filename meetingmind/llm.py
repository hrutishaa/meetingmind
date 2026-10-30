"""Optional LLM extraction with grounding checks.

The model only proposes items. We keep an item only if its evidence quote
really appears in the transcript and its owner is a real participant, so a
hallucinated task or owner is dropped instead of shipped to the team.
Bring your own client: any callable(prompt: str) -> str works.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from .actions import ActionItem, extract_action_items, find_due
from .transcript import Utterance

PROMPT = """You extract action items from a meeting transcript.
Return ONLY a JSON array. Each element: {{"owner": str, "task": str, "due": str|null, "evidence": str}}.
"evidence" must be copied word-for-word from the transcript. Owners must be meeting participants: {people}.
If there are no action items return [].

Transcript:
{transcript}
"""


def build_prompt(utterances: list[Utterance]) -> str:
    people = ", ".join(sorted({u.speaker for u in utterances}))
    body = "\n".join(f"[{u.start:.0f}s] {u.speaker}: {u.text}" for u in utterances)
    return PROMPT.format(people=people, transcript=body)


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s).strip().lower()


def parse_llm_items(raw: str, utterances: list[Utterance]) -> tuple[list[ActionItem], list[str]]:
    """Validate model output. Returns (kept items, rejection reasons)."""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return [], ["no JSON array in response"]
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return [], [f"invalid JSON: {e.msg}"]
    speakers = {u.speaker.lower(): u.speaker for u in utterances}
    kept, rejected = [], []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not d.get("task") or not d.get("evidence"):
            rejected.append(f"malformed item: {d!r}")
            continue
        owner = speakers.get(str(d.get("owner", "")).lower())
        if owner is None:
            rejected.append(f"unknown owner {d.get('owner')!r}")
            continue
        ev = _norm(d["evidence"])
        source = next((u for u in utterances if ev and ev in _norm(u.text)), None)
        if source is None:
            rejected.append(f"evidence not in transcript: {d['evidence'][:60]!r}")
            continue
        due = d.get("due") or find_due(d["evidence"])
        kept.append(ActionItem(owner, str(d["task"]).strip(), due, d["evidence"], source.speaker, source.start))
    return kept, rejected


def extract_with_llm(
    utterances: list[Utterance], complete: Callable[[str], str] | None = None
) -> tuple[list[ActionItem], list[str]]:
    """Use the LLM when given and it yields grounded items; otherwise fall back to rules."""
    if complete is None:
        return extract_action_items(utterances), ["no LLM configured; used rules"]
    try:
        items, rejected = parse_llm_items(complete(build_prompt(utterances)), utterances)
    except Exception as e:  # network / provider errors must not lose the meeting
        return extract_action_items(utterances), [f"LLM call failed: {type(e).__name__}; used rules"]
    if not items:
        return extract_action_items(utterances), rejected + ["no grounded LLM items; used rules"]
    return items, rejected
