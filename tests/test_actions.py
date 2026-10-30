from pathlib import Path

from meetingmind.actions import extract_action_items, find_due
from meetingmind.transcript import parse_transcript

SAMPLE = (Path(__file__).parent.parent / "samples" / "weekly_sync.txt").read_text()


def items(text):
    return extract_action_items(parse_transcript(text))


def test_sample_meeting_items():
    got = [(i.owner, i.task, i.due) for i in items(SAMPLE)]
    assert got == [
        ("Marcus", "Rerun the cohort query with the fixed timezone", "friday"),
        ("Dana", "Send the customer the updated CSV export spec", None),
        ("Dana", "Draft the FAQ for the support team", "next week"),
        ("Marcus", "Add retry with backoff to the sync job", None),
        ("Priya", "Book the room and send the invite", "tomorrow"),
    ]


def test_every_item_keeps_verbatim_evidence():
    for i in items(SAMPLE):
        assert i.evidence in SAMPLE


def test_assignment_to_unknown_name_is_ignored():
    # "Kevin" never speaks, so we don't invent an owner
    assert items("Ann: Kevin, can you look at the logs?\nBo: sure") == []


def test_small_talk_is_not_an_action_item():
    assert items("Ann: I'll be honest, that was fun.\nBo: I think so. See you next week.") == []


def test_plain_questions_are_skipped():
    assert items("Ann: Will we ship it?\nBo: Maybe.") == []


def test_duplicates_are_collapsed():
    got = items("Ann: I'll update the deck.\nBo: ok\nAnn: I'll update the deck.")
    assert len(got) == 1


def test_find_due_variants():
    assert find_due("send it by end of day") == "end of day"
    assert find_due("ship by Nov 3 please") == "nov 3"
    assert find_due("do it by next Monday") == "next monday"
    assert find_due("whenever") is None
