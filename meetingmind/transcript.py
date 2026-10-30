"""Parse meeting transcripts into timed, speaker-attributed utterances.

Supported line formats (mixed freely):
  [00:01:23] Alice: text      00:01:23 Alice: text      [1:23] Alice: text
  Alice: text                 (no timestamp; times are estimated from word count)
  WebVTT cues:  00:00:01.000 --> 00:00:04.000  followed by  <v Alice>text
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORDS_PER_SECOND = 2.5  # ~150 wpm, used only when a transcript has no timestamps

_TS = r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
_LINE = re.compile(rf"^\s*(?:\[{_TS}\]|{_TS})?\s*([A-Za-z][\w .'-]{{0,40}}?)\s*:\s+(.+)$")
_VTT_CUE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_VTT_VOICE = re.compile(r"^\s*<v\s+([^>]+)>(.*?)(?:</v>)?\s*$")


@dataclass(frozen=True)
class Utterance:
    speaker: str
    text: str
    start: float  # seconds from meeting start
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_timestamp(ts: str) -> float:
    """'01:02:03.5' -> 3723.5, '1:23' -> 83.0"""
    parts = ts.replace(",", ".").split(":")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def _estimate(text: str) -> float:
    return max(1.0, len(text.split()) / WORDS_PER_SECOND)


def parse_transcript(raw: str) -> list[Utterance]:
    """Return utterances in order. Ends are the next utterance's start (or estimated)."""
    rows: list[tuple[str, str, float | None, float | None]] = []
    cue: tuple[float, float] | None = None
    for line in raw.splitlines():
        if not line.strip() or line.strip().upper() == "WEBVTT":
            continue
        if m := _VTT_CUE.match(line):
            cue = (parse_timestamp(m.group(1)), parse_timestamp(m.group(2)))
            continue
        if m := _VTT_VOICE.match(line):
            start, end = cue if cue else (None, None)
            rows.append((m.group(1).strip(), m.group(2).strip(), start, end))
            cue = None
            continue
        if m := _LINE.match(line):
            ts = m.group(1) or m.group(2)
            rows.append((m.group(3).strip(), m.group(4).strip(), parse_timestamp(ts) if ts else None, None))
            continue
        if rows:  # continuation line: append to the previous speaker
            spk, txt, s, e = rows[-1]
            rows[-1] = (spk, f"{txt} {line.strip()}", s, e)

    out: list[Utterance] = []
    clock = 0.0
    for i, (spk, txt, start, end) in enumerate(rows):
        start = clock if start is None else start
        if end is None:
            nxt = next((r[2] for r in rows[i + 1 :] if r[2] is not None), None)
            end = nxt if nxt is not None and nxt > start else start + _estimate(txt)
        out.append(Utterance(spk, txt, start, end))
        clock = end
    return out
