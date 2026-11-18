from datetime import date

import pytest

from meetingmind.dues import resolve_due

MON = date(2026, 11, 9)  # a Monday


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("eod", MON),
        ("end of day", MON),
        ("tonight", MON),
        ("tomorrow", date(2026, 11, 10)),
        ("friday", date(2026, 11, 13)),
        ("this friday", date(2026, 11, 13)),
        ("monday", MON),  # said on Monday: today
        ("next monday", date(2026, 11, 16)),
        ("next friday", date(2026, 11, 20)),
        ("eow", date(2026, 11, 13)),
        ("end of week", date(2026, 11, 13)),
        ("next week", date(2026, 11, 20)),
        ("end of month", date(2026, 11, 30)),
        ("nov 20", date(2026, 11, 20)),
        ("november 20", date(2026, 11, 20)),
        ("sept. 3", date(2027, 9, 3)),  # already passed this year: next one
        ("11/20", date(2026, 11, 20)),
        ("2026-12-01", date(2026, 12, 1)),
    ],
)
def test_resolves_relative_to_meeting_day(phrase, expected):
    assert resolve_due(phrase, MON) == expected


def test_accepts_iso_string_and_weekend_meetings():
    assert resolve_due("tomorrow", "2026-12-31") == date(2027, 1, 1)
    assert resolve_due("end of week", date(2026, 11, 14)) == date(2026, 11, 14)  # Saturday
    assert resolve_due("jan 5", date(2026, 12, 20)) == date(2027, 1, 5)


@pytest.mark.parametrize("phrase", [None, "", "soon", "asap", "feb 30", "13/45", "2026-02-30", "the friday after"])
def test_unknown_phrases_are_not_guessed(phrase):
    assert resolve_due(phrase, MON) is None
