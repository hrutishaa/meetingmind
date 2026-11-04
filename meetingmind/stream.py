"""Live transcript streaming: chunks in, speaker turns and action items out, incrementally.

A speech-to-text engine (or a person typing notes) sends small chunks as the meeting
happens. `StreamSession` keeps one open speaker turn, decides when a turn has ended,
and emits each action item as soon as the sentence that contains it is complete,
so a note-taker sees "Marcus: rerun the cohort query, due Friday" seconds after it is said.

Turn detection rules (simple, explainable, testable):
  * a chunk from a different speaker closes the open turn;
  * a pause of `pause_s` seconds or more since the speaker's last chunk closes it too
    (same speaker, new turn), which keeps long monologues split into readable turns;
  * a chunk with no speaker continues the current speaker (typical ASR partials).

When the stream ends, `finish()` runs the batch extractor over the whole meeting once
more, so items that needed later context (e.g. "Dana, can you ..." before Dana ever
spoke) are still emitted, flagged `late`. The final item list always equals the batch
result for the same transcript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .actions import ActionItem, extract_action_items
from .analytics import analyze
from .transcript import WORDS_PER_SECOND, Utterance, parse_timestamp

MAX_CHUNK_CHARS = 5_000
MAX_SESSION_CHARS = 200_000
DEFAULT_PAUSE_S = 2.0

# Stricter than the batch line parser: a mid-sentence chunk such as "pages. Action item: Marcus to ..."
# must not be mistaken for a new speaker, so names have no dots and at most four words.
_SPEAKER_PREFIX = re.compile(
    r"^\s*(?:\[(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]\s*)?"
    r"([A-Za-z][\w'-]{0,30}(?: [A-Za-z][\w'-]{0,30}){0,3})\s*:\s+(.+)$",
    re.S,
)
_NOT_A_SPEAKER = re.compile(r"^(?:action items?|todos?|to-dos?|next steps?|notes?|decision|agenda|re)$", re.I)
_SENT_END = re.compile(r"(?<=[.!?])\s+")


class StreamError(ValueError):
    """Bad chunk (too big, empty, wrong types). The session stays usable."""


@dataclass
class _Turn:
    speaker: str
    start: float
    last: float
    text: str = ""
    pending: str = ""  # text of the sentence still being spoken


@dataclass
class StreamSession:
    pause_s: float = DEFAULT_PAUSE_S
    utterances: list[Utterance] = field(default_factory=list)
    items: list[ActionItem] = field(default_factory=list)
    _turn: _Turn | None = None
    _clock: float = 0.0
    _chars: int = 0
    _seen: set = field(default_factory=set)
    _speakers: dict = field(default_factory=dict)
    finished: bool = False

    # ---- public API -------------------------------------------------------
    def push(self, text: str, speaker: str | None = None, t: float | str | None = None) -> list[dict]:
        """Add one chunk. Returns the events it produced (turn ends, new action items)."""
        if self.finished:
            raise StreamError("stream already finished")
        if not isinstance(text, str) or not text.strip():
            raise StreamError("chunk text must be a non-empty string")
        if len(text) > MAX_CHUNK_CHARS:
            raise StreamError(f"chunk longer than {MAX_CHUNK_CHARS} characters")
        if self._chars + len(text) > MAX_SESSION_CHARS:
            raise StreamError(f"session longer than {MAX_SESSION_CHARS} characters")
        if speaker is not None and (not isinstance(speaker, str) or not speaker.strip() or len(speaker) > 80):
            raise StreamError("speaker must be a non-empty string up to 80 characters")
        at = self._time(t)

        m = _SPEAKER_PREFIX.match(text) if speaker is None else None
        if m and not _NOT_A_SPEAKER.match(m.group(2)):
            # "[00:01:02] Dana: text" or "Dana: text" lines are accepted as-is
            if m.group(1) and t is None:
                at = parse_timestamp(m.group(1))
            speaker, text = m.group(2), m.group(3)
        speaker = (speaker or (self._turn.speaker if self._turn else "Speaker")).strip()
        text = " ".join(text.split())
        self._chars += len(text)

        events: list[dict] = []
        turn = self._turn
        if turn and (turn.speaker != speaker or (at is not None and at - turn.last >= self.pause_s)):
            events += self._close_turn(end=at)
            turn = None
        if at is None:
            at = turn.last if turn else self._clock
        if turn is None:
            turn = self._turn = _Turn(speaker=speaker, start=at, last=at)
            self._speakers.setdefault(speaker.split()[0].lower(), speaker)

        turn.text = f"{turn.text} {text}".strip()
        turn.pending = f"{turn.pending} {text}".strip()
        turn.last = max(turn.last, at) + len(text.split()) / WORDS_PER_SECOND
        events += self._flush_sentences(turn, final=False)
        return events

    def finish(self) -> list[dict]:
        """Close the stream: last turn, late items, and a summary event."""
        if self.finished:
            return []
        events = self._close_turn(end=None)
        self.finished = True
        batch = extract_action_items(self.utterances)
        for item in batch:
            events += self._emit(item, late=True)
        # A live guess made before everyone had spoken can differ from the full-context
        # answer (e.g. owner resolved later). Retract it so clients end up with the batch list.
        order = {(i.owner.lower(), i.task.lower()): n for n, i in enumerate(batch)}
        for i in self.items:
            if (i.owner.lower(), i.task.lower()) not in order:
                events.append({"type": "item_retracted", "owner": i.owner, "task": i.task})
        self.items = sorted(
            (i for i in self.items if (i.owner.lower(), i.task.lower()) in order),
            key=lambda i: order[(i.owner.lower(), i.task.lower())],
        )
        events.append(
            {
                "type": "summary",
                "turns": len(self.utterances),
                "stats": analyze(self.utterances).to_dict() if self.utterances else {},
                "action_items": [i.to_dict() for i in self.items],
            }
        )
        return events

    # ---- internals --------------------------------------------------------
    def _time(self, t: float | str | None) -> float | None:
        if t is None:
            return None
        if isinstance(t, bool):
            raise StreamError("t must be seconds or a timestamp like 00:01:23")
        try:
            v = parse_timestamp(t) if isinstance(t, str) else float(t)
        except ValueError as exc:
            raise StreamError("t must be seconds or a timestamp like 00:01:23") from exc
        if v < 0 or v != v or v == float("inf"):
            raise StreamError("t must be a finite number of seconds >= 0")
        return v

    def _flush_sentences(self, turn: _Turn, final: bool) -> list[dict]:
        parts = _SENT_END.split(turn.pending)
        done, rest = (parts, "") if final or re.search(r"[.!?]$", turn.pending) else (parts[:-1], parts[-1])
        turn.pending = rest
        events: list[dict] = []
        for sent in filter(None, (s.strip() for s in done)):
            utt = Utterance(turn.speaker, sent, turn.start, turn.last)
            for item in extract_action_items([utt], known_speakers=self._speakers.values()):
                events += self._emit(item, late=False)
        return events

    def _emit(self, item: ActionItem, late: bool) -> list[dict]:
        key = (item.owner.lower(), item.task.lower())
        if key in self._seen:
            return []
        self._seen.add(key)
        self.items.append(item)
        return [{"type": "action_item", "late": late, **item.to_dict()}]

    def _close_turn(self, end: float | None) -> list[dict]:
        turn, self._turn = self._turn, None
        if turn is None:
            return []
        events = self._flush_sentences(turn, final=True)
        # like the batch parser: a turn ends when the next one starts, else at the estimate
        stop = end if end is not None and end > turn.start else turn.last
        utt = Utterance(turn.speaker, turn.text, turn.start, stop)
        self.utterances.append(utt)
        self._clock = utt.end
        return [{"type": "turn", "speaker": utt.speaker, "text": utt.text, "start": utt.start, "end": utt.end}, *events]
