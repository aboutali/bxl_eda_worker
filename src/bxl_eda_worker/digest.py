from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from bxl_eda_worker.config import DIGEST_DIR, Source
from bxl_eda_worker.models import Item

CATEGORY_ORDER = (
    "swiss_official",
    "eu_institution",
    "press_eu",
    "press_swiss",
    "press_intl",
    "think_tank",
)
CATEGORY_LABELS = {
    "swiss_official": "🇨🇭 Swiss confederation",
    "eu_institution": "🇪🇺 EU institutions",
    "press_eu":       "Brussels press",
    "press_swiss":    "Swiss press",
    "press_intl":     "International press",
    "think_tank":     "Think tanks & analysis",
}

TOPIC_ORDER = ("sanctions", "middle_east", "foreign_policy")
TOPIC_LABELS = {
    "sanctions":      "Sanctions",
    "middle_east":    "Middle East",
    "foreign_policy": "Foreign Policy (general)",
}


def render(
    items: list[Item],
    sources: list[Source],
    *,
    window_start: datetime,
    window_end: datetime,
    headline: str = "",
) -> str:
    by_id = {s.id: s for s in sources}
    items = _dedupe_by_title(items)
    counts = {t: sum(1 for it in items if t in it.topics) for t in TOPIC_ORDER}
    swiss_items = [it for it in items if it.swiss_relevance]

    lines: list[str] = []
    date_str = window_end.strftime("%Y-%m-%d")
    lines.append(f"# EU Foreign Policy & Sanctions Digest — {date_str}")
    lines.append("")
    lines.append(
        f"Window: {_fmt(window_start)} → {_fmt(window_end)} (UTC) · "
        f"{len(items)} items · "
        f"Sanctions {counts['sanctions']} · Middle East {counts['middle_east']} · "
        f"FP {counts['foreign_policy']} · Swiss-relevance {len(swiss_items)}"
    )
    lines.append("")

    if headline:
        lines.append("## Today")
        lines.append("")
        lines.append(headline)
        lines.append("")

    if swiss_items:
        lines.append("## 🇨🇭 Swiss-relevance highlights")
        lines.append("")
        for it in _sort_for_section(swiss_items)[:15]:
            lines.extend(_render_item(it, by_id))
        if len(swiss_items) > 15:
            lines.append(f"  _… and {len(swiss_items) - 15} more in sections below._")
        lines.append("")

    by_cat: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_cat[it.category].append(it)

    for cat in CATEGORY_ORDER:
        cat_items = by_cat.get(cat, [])
        if not cat_items:
            continue
        lines.append(f"## {CATEGORY_LABELS[cat]}")
        lines.append("")
        for topic in TOPIC_ORDER:
            topic_items = [it for it in cat_items if topic in it.topics]
            if not topic_items:
                continue
            lines.append(f"### {TOPIC_LABELS[topic]}")
            lines.append("")
            for it in _sort_for_section(topic_items, by_id):
                lines.extend(_render_item(it, by_id))
            lines.append("")

    if not items:
        lines.append("_No relevant items in this window._")
        lines.append("")

    lines.append("---")
    polled = ", ".join(s.name for s in sources)
    lines.append(f"_Sources polled: {polled}._")
    return "\n".join(lines)


def write_digest(content: str, *, date: datetime, out_dir: Path = DIGEST_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.strftime('%Y-%m-%d')}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _render_item(it: Item, by_id: dict[str, Source]) -> list[str]:
    when = it.published_at or it.fetched_at
    src = by_id.get(it.source)
    source_name = src.name if src else it.source
    badge = f" {src.badge}" if (src and src.badge) else ""
    lang = f" `{it.language}`" if (src and it.language != "en") else ""
    importance = f" ★{it.importance}" if it.importance >= 4 else ""
    out = [
        f"- **[{it.title}]({it.url})** — {source_name}{badge}{lang}{importance} · {_fmt(when)}"
    ]
    if it.summary_oneliner:
        out.append(f"  > {it.summary_oneliner}")
    elif it.summary:
        out.append(f"  > {it.summary}")
    tags = []
    if it.swiss_rationale:
        tags.append(f"🇨🇭 {it.swiss_rationale}")
    elif it.swiss_relevance and "sanctions" in it.topics:
        tags.append("SECO alignment likely")
    if it.regions:
        tags.append("regions: " + ", ".join(it.regions))
    if tags:
        out.append(f"  _{' · '.join(tags)}_")
    return out


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _sort_for_section(items: list[Item], by_id: dict[str, Source] | None = None) -> list[Item]:
    """Order: importance desc, source weight desc, then time desc."""
    return sorted(
        items,
        key=lambda it: (
            -(it.importance or 0),
            -((by_id or {}).get(it.source).weight if by_id and it.source in by_id else 0),
            -(it.published_at or it.fetched_at).timestamp(),
        ),
    )


def _dedupe_by_title(items: list[Item]) -> list[Item]:
    """EEAS republishes the same press release under several delegation paths
    with different URLs but identical titles. Keep first per (source, normalized-title)."""
    seen: set[tuple[str, str]] = set()
    out: list[Item] = []
    for it in items:
        key = (it.source, " ".join(it.title.lower().split()))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
