"""Turn spoken due phrases ("by Friday", "next week", "Nov 20") into calendar dates.

Phrases are resolved relative to the day the meeting was held, so "tomorrow" in a
meeting on Mon Nov 9 means Tue Nov 10. Anything we can't pin to a date returns
None and is reported as "no due date" instead of being guessed.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_DAY = re.compile(r"^([a-z]{3})[a-z]*\.?\s+(\d{1,2})$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FRIDAY = 4


def _friday_of_week(d: date) -> date:
    """End of the working week containing d (a weekend day keeps its own date)."""
    return d + timedelta(days=FRIDAY - d.weekday()) if d.weekday() <= FRIDAY else d


def _upcoming(month: int, day: int, held: date) -> date | None:
    """Month/day with no year: the next one on or after the meeting (Dec meeting, "Jan 5" -> next year)."""
    for year in (held.year, held.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= held:
            return d
    return None


def resolve_due(due: str | None, held_on: date | str) -> date | None:
    if not due:
        return None
    held = date.fromisoformat(held_on) if isinstance(held_on, str) else held_on
    phrase = re.sub(r"\s+", " ", due.strip().lower())
    if _ISO.match(phrase):
        try:
            return date.fromisoformat(phrase)
        except ValueError:
            return None
    if phrase in ("eod", "end of day", "today", "tonight"):
        return held
    if phrase == "tomorrow":
        return held + timedelta(days=1)
    if phrase in ("eow", "end of week", "this week"):
        return _friday_of_week(held)
    if phrase == "next week":
        return _friday_of_week(held + timedelta(days=7 - held.weekday()))
    if phrase in ("end of month", "eom"):
        return held.replace(day=calendar.monthrange(held.year, held.month)[1])
    words = phrase.split(" ")
    if words[-1] in _WEEKDAYS and len(words) <= 2:
        target = _WEEKDAYS.index(words[-1])
        if words[0] == "next" and len(words) == 2:  # that weekday in the following week
            return held + timedelta(days=7 - held.weekday() + target)
        return held + timedelta(days=(target - held.weekday()) % 7)  # "friday", "this friday"
    if (m := _MONTH_DAY.match(phrase)) and m.group(1) in _MONTHS:
        return _upcoming(_MONTHS[m.group(1)], int(m.group(2)), held)
    if m := _SLASH.match(phrase):  # US style month/day
        return _upcoming(int(m.group(1)), int(m.group(2)), held)
    return None
