"""EU sanctions tracker: Council sanctions decisions of the last 90 days.

Council press releases name the regime before the colon and the action after
it ("Nicaragua: Council extends restrictive measures until October 2027"),
so regime, measure type and validity come from rules, not an LLM call.
A SECO alignment column follows once a SECO source works (see #8).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bxl_eda_worker.models import Item
from bxl_eda_worker.render_html import DOCS_DIR

DECISION_SOURCES = ("council_press",)

# First match wins; order goes from most to least specific.
_MEASURES = (
    ("Delisting", re.compile(r"\bdelist|\bremoves?\b.*\bfrom\b.*\blist", re.I)),
    ("Renewal", re.compile(r"\b(extend|prolong|renew)", re.I)),
    ("New framework", re.compile(r"\b(establish|new framework|sets up)", re.I)),
    ("New package", re.compile(r"\b(package|round)\b", re.I)),
    ("New listings", re.compile(r"\b(lists?|listings?|sanctions? \d+|adds?|imposes?)\b", re.I)),
)
_NOT_A_DECISION = re.compile(r"\bstatement\b|\bdeclaration by the high representative\b", re.I)
_UNTIL = re.compile(
    r"\buntil (?:\d{1,2} )?(January|February|March|April|May|June|July|August|"
    r"September|October|November|December) (\d{4})",
    re.I,
)


@dataclass(frozen=True)
class Decision:
    when: date
    regime: str
    measure: str
    valid_until: str
    title: str
    url: str


def to_decision(it: Item) -> Decision | None:
    if it.source not in DECISION_SOURCES or "sanctions" not in it.topics:
        return None
    if _NOT_A_DECISION.search(it.title):
        return None
    regime, sep, action = it.title.partition(":")
    if not sep:
        regime, action = "—", it.title
    measure = next((name for name, rx in _MEASURES if rx.search(action)), "Other decision")
    m = _UNTIL.search(action)
    valid_until = f"{m.group(1).capitalize()} {m.group(2)}" if m else ""
    when = (it.published_at or it.fetched_at).date()
    return Decision(when, regime.strip(), measure, valid_until, it.title, it.url)


def decisions(items: list[Item]) -> list[Decision]:
    seen: set[str] = set()
    out: list[Decision] = []
    for it in sorted(items, key=lambda i: i.published_at or i.fetched_at, reverse=True):
        d = to_decision(it)
        if d and d.url not in seen:
            seen.add(d.url)
            out.append(d)
    return out


def render_sanctions_page(rows: list[Decision], generated_at: datetime) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\"><head>",
        "<meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>EU FP Digest — Sanctions tracker</title>",
        "<link rel=\"stylesheet\" href=\"style.css\">",
        "</head><body>",
        "<header>",
        "<h1>EU sanctions tracker</h1>",
        f"<div class=\"meta\">Council sanctions decisions of the last 90 days · "
        f"{len(rows)} decisions · updated {generated_at:%Y-%m-%d %H:%M} UTC</div>",
        "<nav><a href=\"./\">← Latest</a> · <a href=\"archive/\">Archive</a></nav>",
        "</header>",
        "<main>",
        "<p class=\"note\">Regime, measure and validity are read from the Council press-release "
        "titles. A column for SECO alignment follows once a SECO source is connected.</p>",
    ]
    if rows:
        parts.append("<div class=\"table-wrap\"><table class=\"sanctions\">")
        parts.append(
            "<thead><tr><th>Date</th><th>Regime</th><th>Measure</th>"
            "<th>Valid until</th><th>Decision</th></tr></thead><tbody>"
        )
        for d in rows:
            until = (
                f"<td>until {html.escape(d.valid_until)}</td>" if d.valid_until
                else "<td class=\"none\">—</td>"
            )
            parts.append(
                "<tr>"
                f"<td><time datetime=\"{d.when.isoformat()}\">{d.when:%Y-%m-%d}</time></td>"
                f"<td>{html.escape(d.regime)}</td>"
                f"<td>{html.escape(d.measure)}</td>"
                f"{until}"
                f"<td><a href=\"{html.escape(d.url, quote=True)}\">{html.escape(d.title)}</a></td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">No Council sanctions decisions stored yet.</p>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def write_sanctions_page(
    items: list[Item], generated_at: datetime, *, docs_dir: Path = DOCS_DIR
) -> Path:
    out = docs_dir / "sanctions.html"
    out.write_text(render_sanctions_page(decisions(items), generated_at), encoding="utf-8")
    return out
