"""Upcoming Council meetings, parsed from Council press-release titles.

The Council's meeting calendar sits behind a Cloudflare challenge and has no
feed, but its press-release RSS announces each meeting a few days ahead:
"Media advisory - Foreign Affairs Council of 12 October 2026" or
"Press briefing - Economic and Financial Affairs Council of 9 October 2026".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bxl_eda_worker.models import Item

EVENT_SOURCES = ("council_press",)

_TITLE_RE = re.compile(
    r"^(?:media advisory|press briefing)\s*[-–—]\s*"
    r"(?P<name>.+?)\s+of\s+"
    r"(?P<day>\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Event:
    when: date
    name: str
    url: str


def extract_events(items: list[Item]) -> list[Event]:
    """One Event per (date, meeting); advisory and briefing collapse into one."""
    seen: dict[tuple[date, str], Event] = {}
    for it in items:
        if it.source not in EVENT_SOURCES:
            continue
        ev = parse_event_title(it.title, it.url)
        if ev and (ev.when, ev.name.lower()) not in seen:
            seen[(ev.when, ev.name.lower())] = ev
    return sorted(seen.values(), key=lambda e: (e.when, e.name))


def parse_event_title(title: str, url: str) -> Event | None:
    m = _TITLE_RE.match(title.strip())
    if not m:
        return None
    try:
        when = datetime.strptime(
            f"{m['day']} {m['month']} {m['year']}", "%d %B %Y"
        ).date()
    except ValueError:
        return None
    return Event(when=when, name=m["name"].strip(), url=url)
