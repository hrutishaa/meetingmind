"""Team analytics for one meeting: talk time, balance, questions, interruptions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .actions import extract_action_items
from .transcript import Utterance

INTERRUPT_GAP = 0.5  # seconds: a new speaker starting before the previous one ended (+gap)


@dataclass
class SpeakerStats:
    speaker: str
    talk_seconds: float = 0.0
    words: int = 0
    turns: int = 0
    questions: int = 0
    interruptions: int = 0
    longest_turn_seconds: float = 0.0
    share: float = 0.0  # fraction of total talk time


@dataclass
class MeetingStats:
    duration_seconds: float
    speakers: list[SpeakerStats]
    balance: float  # 1.0 = everyone talked equally, 0.0 = one person talked
    action_items: int
    owners_with_items: int
    decisions: int
    questions: int = 0
    by_speaker: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "duration_seconds": round(self.duration_seconds, 1),
            "balance": round(self.balance, 3),
            "action_items": self.action_items,
            "owners_with_items": self.owners_with_items,
            "decisions": self.decisions,
            "questions": self.questions,
            "speakers": [
                {**s.__dict__, "talk_seconds": round(s.talk_seconds, 1), "share": round(s.share, 3)}
                for s in self.speakers
            ],
        }


def balance_score(shares: list[float]) -> float:
    """1 - normalized Gini coefficient of talk shares."""
    n = len(shares)
    if n <= 1 or sum(shares) == 0:
        return 1.0
    xs = sorted(shares)
    total = sum(xs)
    gini = sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(xs)) / (n * total)
    return max(0.0, 1.0 - gini * n / (n - 1))


DECISION_WORDS = ("we decided", "let's go with", "decision:", "agreed", "we'll go with", "final call")


def analyze(utterances: list[Utterance]) -> MeetingStats:
    stats: dict[str, SpeakerStats] = defaultdict(lambda: SpeakerStats(""))
    prev: Utterance | None = None
    decisions = 0
    for u in utterances:
        s = stats[u.speaker]
        s.speaker = u.speaker
        s.talk_seconds += u.duration
        s.words += u.words
        s.questions += u.text.count("?")
        s.longest_turn_seconds = max(s.longest_turn_seconds, u.duration)
        if prev is None or prev.speaker != u.speaker:
            s.turns += 1
            if prev is not None and u.start + INTERRUPT_GAP < prev.end:
                s.interruptions += 1
        low = u.text.lower()
        decisions += sum(low.count(w) for w in DECISION_WORDS)
        prev = u

    total = sum(s.talk_seconds for s in stats.values()) or 1.0
    for s in stats.values():
        s.share = s.talk_seconds / total
    speakers = sorted(stats.values(), key=lambda s: -s.talk_seconds)
    items = extract_action_items(utterances)
    duration = (utterances[-1].end - utterances[0].start) if utterances else 0.0
    return MeetingStats(
        duration_seconds=duration,
        speakers=speakers,
        balance=balance_score([s.share for s in speakers]),
        action_items=len(items),
        owners_with_items=len({i.owner for i in items}),
        decisions=decisions,
        questions=sum(s.questions for s in speakers),
    )
