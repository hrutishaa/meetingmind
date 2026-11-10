import json

from meetingmind.__main__ import main
from meetingmind.evaluate import evaluate, load_golden, report, score_items, similarity


def item(owner, task, due=None):
    return {"owner": owner, "task": task, "due": due}


def test_similarity_ignores_stopwords_and_plurals():
    assert similarity("Send the reports", "send report") == 1.0
    assert similarity("Book the room", "Fix the bug") == 0.0


def test_perfect_match_and_due_accuracy():
    s = score_items([item("Ann", "Send the report", "friday")], [item("ann", "send report", "friday")])
    assert (s.tp, s.fp, s.fn, s.f1, s.due_accuracy) == (1, 0, 0, 1.0, 1.0)


def test_wrong_owner_is_a_miss_and_an_extra():
    s = score_items([item("Bo", "Send the report")], [item("Ann", "Send the report")])
    assert (s.tp, s.fp, s.fn) == (0, 1, 1) and s.misses == ["Ann: Send the report"]


def test_duplicates_count_once():
    s = score_items([item("Ann", "Send report"), item("Ann", "Send the report")], [item("Ann", "Send the report")])
    assert (s.tp, s.fp, s.fn) == (1, 1, 0) and s.precision == 0.5


def test_empty_cases_have_no_nan():
    assert score_items([], []).f1 == 1.0
    assert score_items([], [item("Ann", "Send report")]).summary()["precision"] == 0.0
    assert score_items([item("Ann", "Send report")], []).recall == 0.0
    assert score_items([item("A", "x y")], [item("A", "p q")]).f1 == 0.0


def test_golden_set_is_well_formed():
    cases = load_golden()
    assert len(cases) >= 10 and len({c["id"] for c in cases}) == len(cases)
    assert any(not c["items"] for c in cases)  # includes meetings with no action items
    for c in cases:
        for g in c["items"]:
            assert set(g) == {"owner", "task", "due"} and g["task"]
            assert g["owner"] in c["transcript"], (c["id"], g)


def test_rule_baseline_regression_gate():
    o = evaluate()["overall"]
    assert o["f1"] >= 0.75 and o["precision"] >= 0.7 and o["recall"] >= 0.75


def test_report_and_cli(capsys):
    assert "| rules |" in report({"rules": evaluate()})
    assert main(["eval", "--json", "--min-f1", "0.75"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rules"]["cases"] >= 10
    assert main(["eval", "--min-f1", "0.99"]) == 1


def test_llm_flag_without_key_explains(monkeypatch, capsys):
    monkeypatch.delenv("MEETINGMIND_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MEETINGMIND_LLM_BASE_URL", raising=False)
    assert main(["eval", "--llm"]) == 2
    assert "MEETINGMIND_LLM_API_KEY" in capsys.readouterr().err
