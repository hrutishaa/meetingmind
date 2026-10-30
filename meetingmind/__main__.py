"""CLI: python -m meetingmind analyze transcript.txt"""

import argparse
import json
import sys
from pathlib import Path

from .actions import extract_action_items
from .analytics import analyze
from .transcript import parse_transcript


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="meetingmind")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="action items + team analytics as JSON")
    a.add_argument("path", help="transcript file, or - for stdin")
    args = p.parse_args(argv)
    raw = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    utts = parse_transcript(raw)
    out = {
        "stats": analyze(utts).to_dict(),
        "action_items": [i.to_dict() for i in extract_action_items(utts)],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
