"""CLI: python -m meetingmind analyze transcript.txt [--llm] | python -m meetingmind eval [--llm]"""

import argparse
import json
import sys
from pathlib import Path

from .actions import extract_action_items
from .analytics import analyze
from .llm import extract_with_llm
from .providers import from_env
from .transcript import parse_transcript

NO_LLM = (
    "LLM mode needs MEETINGMIND_LLM_API_KEY (and optionally MEETINGMIND_LLM_BASE_URL, "
    "MEETINGMIND_LLM_MODEL) for any OpenAI-compatible API."
)


def _analyze(args) -> int:
    raw = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    utts = parse_transcript(raw)
    out = {"stats": analyze(utts).to_dict()}
    if args.llm:
        provider = from_env()
        if provider is None:
            print(NO_LLM, file=sys.stderr)
            return 2
        items, notes = extract_with_llm(utts, provider)
        out["action_items"] = [i.to_dict() for i in items]
        out["llm_notes"] = notes
    else:
        out["action_items"] = [i.to_dict() for i in extract_action_items(utts)]
    print(json.dumps(out, indent=2))
    return 0


def _eval(args) -> int:
    from .evaluate import evaluate, report

    results = {"rules": evaluate(extract_action_items)}
    if args.llm:
        provider = from_env()
        if provider is None:
            print(NO_LLM, file=sys.stderr)
            return 2
        notes: list[str] = []

        def llm(utts):
            items, n = extract_with_llm(utts, provider)
            notes.extend(n)
            return items

        results[f"llm ({provider.model})"] = evaluate(llm)
        print(f"LLM requests: {provider.calls}, rule fallbacks: {sum('used rules' in n for n in notes)}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(report(results))
        for name, r in results.items():
            for c in r["per_case"]:
                for m in c["misses"]:
                    print(f"  [{name}] {c['id']}: missed {m}")
                for x in c["extras"]:
                    print(f"  [{name}] {c['id']}: extra {x}")
    rules = results["rules"]["overall"]
    if rules["f1"] < args.min_f1 or rules["precision"] < args.min_precision:
        print(f"FAIL: rule baseline below gate (f1 {rules['f1']} < {args.min_f1} "
              f"or precision {rules['precision']} < {args.min_precision})", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="meetingmind")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="action items + team analytics as JSON")
    a.add_argument("path", help="transcript file, or - for stdin")
    a.add_argument("--llm", action="store_true", help="use your own OpenAI-compatible LLM (grounded, falls back to rules)")
    e = sub.add_parser("eval", help="precision/recall/F1 on the labeled golden set")
    e.add_argument("--llm", action="store_true", help="also score LLM mode with your own key")
    e.add_argument("--json", action="store_true")
    e.add_argument("--min-f1", type=float, default=0.0, help="exit 1 if the rule baseline F1 is lower")
    e.add_argument("--min-precision", type=float, default=0.0)
    args = p.parse_args(argv)
    return _analyze(args) if args.cmd == "analyze" else _eval(args)


if __name__ == "__main__":
    raise SystemExit(main())
