import json
from pathlib import Path

from meetingmind.__main__ import main


def test_cli_outputs_json(capsys):
    sample = Path(__file__).parent.parent / "samples" / "weekly_sync.txt"
    assert main(["analyze", str(sample)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stats"]["action_items"] == len(out["action_items"]) == 5
