from pathlib import Path

import pytest

from meetingmind.analytics import analyze, balance_score
from meetingmind.transcript import Utterance, parse_transcript

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


def test_shares_sum_to_one_and_sorted():
    s = analyze(parse_transcript(SAMPLE))
    assert sum(x.share for x in s.speakers) == pytest.approx(1.0)
    assert [x.speaker for x in s.speakers] == ["Priya", "Marcus", "Dana"]
    assert s.action_items == 5 and s.owners_with_items == 3
    assert s.decisions == 2 and s.questions == 3


def test_balance_score_extremes():
    assert balance_score([0.5, 0.5]) == pytest.approx(1.0)
    assert balance_score([1.0, 0.0]) == pytest.approx(0.0)
    assert balance_score([1.0]) == 1.0


def test_interruption_detected_when_overlapping():
    u = [Utterance("Ann", "long point here", 0, 10), Utterance("Bo", "wait", 5, 7)]
    s = analyze(u)
    bo = next(x for x in s.speakers if x.speaker == "Bo")
    assert bo.interruptions == 1


def test_empty_meeting():
    s = analyze([])
    assert s.duration_seconds == 0 and s.speakers == [] and s.balance == 1.0
