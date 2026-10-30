"""Rule-based action-item extraction (offline, deterministic, explainable).

Every item keeps the exact sentence it came from (`evidence`) so a reviewer
can check it, and so LLM output can be grounded against the same transcript.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .transcript import Utterance

_WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DUE = re.compile(
    rf"\b(?:by|before|until|due)\s+((?:end of (?:day|week|month))|eod|eow|tomorrow|tonight|"
    rf"next week|(?:next |this )?(?:{_WEEKDAYS})|(?:{_MONTHS})[a-z]*\.? \d{{1,2}}|\d{{1,2}}/\d{{1,2}})\b"
    rf"|\b(tomorrow|tonight|next week|eod)\b",
    re.I,
)
# speaker commits themselves
_SELF = re.compile(
    r"\b(?:i'll|i will|i can|i'm going to|i am going to|let me|i'll go ahead and)\s+(?!be\b|think\b|guess\b)(.+)",
    re.I,
)
# speaker assigns someone: "Bob, can you ...", "@Bob please ...", "Bob will ..."
_ASSIGN = re.compile(
    r"(?:^|[.!?]\s+|\s)@?([A-Z][a-z]+)(?:,\s*(?:can|could|would) you|,?\s+please|\s+will|\s+is going to|\s+to)\s+(.+)"
)
_EXPLICIT = re.compile(r"\b(?:action item|todo|to-do|next step)s?\s*[:\-]\s*(.+)", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")
_NOT_TASK = re.compile(r"^(?:be|have|think|guess|say|see you|talk to you|agree)\b", re.I)


@dataclass(frozen=True)
class ActionItem:
    owner: str
    task: str
    due: str | None
    evidence: str
    speaker: str
    at: float  # seconds into the meeting

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(task: str) -> str:
    task = re.sub(r"\s+", " ", task).strip(" .!?,;")
    task = re.sub(r"^(?:also|then|just|quickly|go ahead and)\s+", "", task, flags=re.I)
    return task[:1].upper() + task[1:] if task else task


def find_due(text: str) -> str | None:
    m = _DUE.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(2)).strip().lower()


def extract_action_items(utterances: list[Utterance]) -> list[ActionItem]:
    speakers = {u.speaker.split()[0].lower(): u.speaker for u in utterances}
    items: list[ActionItem] = []
    seen: set[tuple[str, str]] = set()
    for u in utterances:
        for sent in _SENT.split(u.text):
            sent = sent.strip()
            if not sent or sent.endswith("?") and not re.search(r"can you|could you", sent, re.I):
                continue
            owner = task = None
            if m := _EXPLICIT.search(sent):
                task = m.group(1)
                a = _ASSIGN.search(" " + task)
                if a and a.group(1).lower() in speakers:
                    owner, task = speakers[a.group(1).lower()], a.group(2)
                else:
                    owner = u.speaker
            elif (m := _ASSIGN.search(sent)) and m.group(1).lower() in speakers:
                owner, task = speakers[m.group(1).lower()], m.group(2)
            elif m := _SELF.search(sent):
                owner, task = u.speaker, m.group(1)
            if not owner or not task or _NOT_TASK.match(task.strip()):
                continue
            task = _clean(_DUE.sub("", task) if find_due(task) else task)
            if len(task.split()) < 2:
                continue
            key = (owner.lower(), task.lower())
            if key in seen:
                continue
            seen.add(key)
            items.append(ActionItem(owner, task, find_due(sent), sent, u.speaker, u.start))
    return items
