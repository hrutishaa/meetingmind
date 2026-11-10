"""Score action-item extraction against a labeled golden set.

A predicted item matches a gold item when the owner is the same person and the
task says the same thing (content-word overlap >= threshold). Matching is
one-to-one, so a duplicate prediction counts as a false positive, not a second
hit. Empty cases are defined (no NaN): nothing predicted and nothing expected is
a perfect score; anything else with zero hits scores 0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .actions import ActionItem, extract_action_items
from .transcript import Utterance, parse_transcript

_STOP = set(
    "a an the to for of on in at by with and or our my your their this that these those it "
    "is are be will can could would please up out over all".split()
)
GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "golden.jsonl"


def task_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w.rstrip("s") if len(w) > 3 else w for w in words if w not in _STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = task_tokens(a), task_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    due_correct: int = 0
    misses: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        n = self.tp + self.fp
        return 1.0 if n == 0 and self.fn == 0 else (self.tp / n if n else 0.0)

    @property
    def recall(self) -> float:
        n = self.tp + self.fn
        return 1.0 if n == 0 and self.fp == 0 else (self.tp / n if n else 0.0)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)

    @property
    def due_accuracy(self) -> float:
        return self.due_correct / self.tp if self.tp else 0.0

    def __iadd__(self, o: "Score") -> "Score":
        self.tp += o.tp
        self.fp += o.fp
        self.fn += o.fn
        self.due_correct += o.due_correct
        self.misses += o.misses
        self.extras += o.extras
        return self

    def summary(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 3), "recall": round(self.recall, 3),
            "f1": round(self.f1, 3), "due_accuracy": round(self.due_accuracy, 3),
        }


def score_items(predicted: list[dict], gold: list[dict], threshold: float = 0.5) -> Score:
    """Greedy one-to-one matching by best task similarity among same-owner pairs."""
    pairs = sorted(
        (
            (similarity(p["task"], g["task"]), i, j)
            for i, p in enumerate(predicted)
            for j, g in enumerate(gold)
            if p["owner"].strip().lower() == g["owner"].strip().lower()
        ),
        reverse=True,
    )
    used_p, used_g, s = set(), set(), Score()
    for sim, i, j in pairs:
        if sim < threshold or i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        s.tp += 1
        s.due_correct += (predicted[i].get("due") or None) == (gold[j].get("due") or None)
    s.fp = len(predicted) - len(used_p)
    s.fn = len(gold) - len(used_g)
    s.extras = [f"{predicted[i]['owner']}: {predicted[i]['task']}" for i in range(len(predicted)) if i not in used_p]
    s.misses = [f"{gold[j]['owner']}: {gold[j]['task']}" for j in range(len(gold)) if j not in used_g]
    return s


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


Extractor = Callable[[list[Utterance]], list[ActionItem]]


def evaluate(extract: Extractor = extract_action_items, cases: list[dict] | None = None) -> dict:
    cases = load_golden() if cases is None else cases
    total, per_case = Score(), []
    for case in cases:
        items = [i.to_dict() for i in extract(parse_transcript(case["transcript"]))]
        s = score_items(items, case["items"])
        per_case.append({"id": case["id"], **s.summary(), "misses": s.misses, "extras": s.extras})
        total += s
    return {"cases": len(cases), "overall": total.summary(), "per_case": per_case}


def report(results: dict[str, dict]) -> str:
    """Markdown table comparing extractors, e.g. {"rules": ..., "llm": ...}."""
    lines = ["| Extractor | Precision | Recall | F1 | Due accuracy | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        o = r["overall"]
        lines.append(
            f"| {name} | {o['precision']:.2f} | {o['recall']:.2f} | {o['f1']:.2f} | {o['due_accuracy']:.2f} "
            f"| {o['tp']} | {o['fp']} | {o['fn']} |"
        )
    return "\n".join(lines)

