from pathlib import Path

import pytest

from meetingmind import analyze, extract_action_items, parse_transcript
from meetingmind.stream import MAX_CHUNK_CHARS, StreamError, StreamSession

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


def replay(lines, **kw):
    s = StreamSession(**kw)
    events = []
    for line in lines:
        events += s.push(line)
    return s, events, s.finish()


def test_line_replay_matches_batch_items_and_stats():
    utts = parse_transcript(SAMPLE)
    s, live, final = replay(SAMPLE.splitlines())
    summary = final[-1]
    assert summary["type"] == "summary" and summary["turns"] == len(utts)
    assert summary["action_items"] == [i.to_dict() for i in extract_action_items(utts)]
    assert summary["stats"] == analyze(utts).to_dict()


def test_items_arrive_before_meeting_ends():
    _, live, final = replay(SAMPLE.splitlines())
    live_items = [e for e in live if e["type"] == "action_item"]
    assert len(live_items) == 4 and not any(e["late"] for e in live_items)
    # Marcus's commitment is emitted while his own turn is still open (before its turn event)
    first = live.index(next(e for e in live if e["type"] == "action_item"))
    assert live[first]["owner"] == "Marcus" and live[first]["due"] == "friday"
    assert not any(e["type"] == "turn" and e["speaker"] == "Marcus" for e in live[:first])


def test_assignment_to_someone_who_has_not_spoken_yet_arrives_late():
    _, _, final = replay(SAMPLE.splitlines())
    late = [e for e in final if e["type"] == "action_item"]
    assert [(e["owner"], e["late"]) for e in late] == [("Dana", True)]
    assert late[0]["evidence"].startswith("Dana, can you send")


def test_partial_chunks_join_into_one_sentence():
    s = StreamSession()
    assert s.push("I'll send the", speaker="Ana", t=0) == []
    events = s.push("pricing deck to the customer by Friday.", t=1)
    assert [(e["owner"], e["task"], e["due"]) for e in events] == [
        ("Ana", "Send the pricing deck to the customer", "friday")
    ]
    assert s.finish()[-1]["turns"] == 1


def test_speaker_change_and_pause_close_turns():
    s = StreamSession(pause_s=2.0)
    assert s.push("Hi team.", speaker="Ana", t=0) == []
    turn = s.push("Hello.", speaker="Ben", t=2)[0]
    assert turn == {"type": "turn", "speaker": "Ana", "text": "Hi team.", "start": 0.0, "end": 2.0}
    assert s.push("One more thing.", t=2.5) == []  # no speaker: Ben continues
    paused = s.push("After a long pause.", t=30)
    assert paused[0]["type"] == "turn" and paused[0]["text"] == "Hello. One more thing."
    s.finish()
    assert [(u.speaker, u.text) for u in s.utterances] == [
        ("Ana", "Hi team."),
        ("Ben", "Hello. One more thing."),
        ("Ben", "After a long pause."),
    ]


def test_assignment_resolves_known_speaker_live():
    s = StreamSession()
    s.push("Ben: hi.")
    events = s.push("Ana: Ben, can you update the churn dashboard by Monday?")
    items = [e for e in events if e["type"] == "action_item"]
    assert [(e["owner"], e["due"], e["late"]) for e in items] == [("Ben", "monday", False)]


def test_no_duplicate_items_and_timestamp_strings():
    s = StreamSession()
    a = s.push("[00:00:05] Ana: I'll write the migration plan.")
    b = s.push("[00:00:20] Ana: I'll write the migration plan.")
    assert len([e for e in a + b if e["type"] == "action_item"]) == 1
    final = s.finish()
    assert [u.start for u in s.utterances] == [5.0, 20.0]
    assert len(final[-1]["action_items"]) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": ""},
        {"text": "   "},
        {"text": 42},
        {"text": "x" * (MAX_CHUNK_CHARS + 1)},
        {"text": "hello", "speaker": ""},
        {"text": "hello", "t": -1},
        {"text": "hello", "t": "soon"},
        {"text": "hello", "t": float("nan")},
    ],
)
def test_bad_chunks_raise_and_session_survives(kwargs):
    s = StreamSession()
    text = kwargs.pop("text")
    with pytest.raises(StreamError):
        s.push(text, **kwargs)
    s.push("Ana: I'll still capture this action.")
    assert len(s.finish()[-1]["action_items"]) == 1


def test_push_after_finish_and_empty_stream():
    s = StreamSession()
    summary = s.finish()[-1]
    assert summary == {"type": "summary", "turns": 0, "stats": {}, "action_items": []}
    assert s.finish() == []
    with pytest.raises(StreamError):
        s.push("too late")


def test_word_chunks_match_batch_and_keyword_colons_are_not_speakers():
    """Mimic speech-to-text partials: each line split into 3-word chunks."""
    lines = [ln.split() for ln in SAMPLE.splitlines()]
    chunks = [" ".join(w[i : i + 3]) for w in lines for i in range(0, len(w), 3)]
    assert "Action item: Marcus" in chunks  # would look like a speaker label
    s, _, final = replay(chunks)
    utts = parse_transcript(SAMPLE)
    assert [(u.speaker, u.text, u.start) for u in s.utterances] == [(u.speaker, u.text, u.start) for u in utts]
    assert final[-1]["action_items"] == [i.to_dict() for i in extract_action_items(utts)]
