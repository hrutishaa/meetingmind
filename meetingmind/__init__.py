"""MeetingMind: meeting transcripts -> action items + team analytics."""

from .actions import ActionItem, extract_action_items
from .analytics import MeetingStats, analyze
from .transcript import Utterance, parse_transcript

__all__ = [
    "ActionItem",
    "MeetingStats",
    "Utterance",
    "analyze",
    "extract_action_items",
    "parse_transcript",
]
__version__ = "0.2.0"
