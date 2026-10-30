import json

from meetingmind.llm import build_prompt, extract_with_llm, parse_llm_items
from meetingmind.transcript import parse_transcript

U = parse_transcript("Ann: I'll send the report by Friday.\nBo: Sounds good.")


def test_prompt_lists_participants():
    p = build_prompt(U)
    assert "Ann, Bo" in p and "send the report" in p


def test_grounded_item_kept():
    raw = json.dumps([{"owner": "ann", "task": "Send report", "due": None,
                       "evidence": "I'll send the report by Friday"}])
    items, rejected = parse_llm_items("Sure! " + raw, U)
    assert rejected == [] and items[0].owner == "Ann" and items[0].due == "friday"


def test_hallucinations_rejected():
    raw = json.dumps([
        {"owner": "Carl", "task": "x", "evidence": "I'll send the report by Friday"},
        {"owner": "Bo", "task": "Book flights", "evidence": "I'll book flights for everyone"},
    ])
    items, rejected = parse_llm_items(raw, U)
    assert items == [] and len(rejected) == 2


def test_falls_back_to_rules_on_bad_output_or_error():
    items, notes = extract_with_llm(U, lambda p: "not json")
    assert items[0].task == "Send the report" and "used rules" in notes[-1]

    def boom(p):
        raise TimeoutError

    items, notes = extract_with_llm(U, boom)
    assert len(items) == 1 and "TimeoutError" in notes[0]
