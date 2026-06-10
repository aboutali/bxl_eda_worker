"""Cross-source clustering of near-duplicate stories.

A daily digest pulls the same story from several outlets — Council statement,
Politico writeup, Reuters wire, NZZ German-language echo. The keyword-driven
classifier promotes all of them; the renderer should keep the most
authoritative one as the primary and demote the rest to a compact
"also covered by" line.

The algorithm is intentionally heuristic and runs in pure Python (no LLM
call): bucket items by topic + dominant region, then group across sources
when title shingles or LLM oneliner shingles cross a similarity threshold.
The dominant source within each cluster is picked by category authority,
source weight, importance and recency.

Mutates Items in place; sets cluster_id / cluster_role / cluster_peers.
Items from the same source never cluster together (those are separate
stories from the same outlet, not duplicates).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item

log = logging.getLogger(__name__)

# Category authority order — primary picked from earliest matching category.
# Mirrors digest.CATEGORY_ORDER but keyed on what's "more authoritative" for
# being the canonical source: an EU institution release outranks press
# coverage of the same release; a Swiss-confederation primary outranks Swiss
# press coverage.
_CATEGORY_PRIORITY = {
    "eu_institution": 0,
    "swiss_official": 1,
    "press_eu":       2,
    "press_swiss":    3,
    "press_intl":     4,
    "think_tank":     5,
}

# Tokens that drown out signal in title-shingle Jaccard. Kept small — common
# news boilerplate and EN/DE/FR articles. Adding domain words here would
# make stories look more similar than they are; resist the temptation.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "this", "to", "was", "were", "with",
    "der", "die", "das", "den", "dem", "des", "und", "oder", "in", "im",
    "von", "vom", "zu", "zur", "zum", "auf", "mit", "über", "für", "ist",
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou",
    "à", "au", "aux", "sur", "pour", "par", "dans",
    "eu", "eu's", "european", "europe",  # near-universal in this corpus
    "say", "says", "said",
})

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Similarity thresholds — empirically calibrated against a small set of
# known duplicates. Lower = more aggressive clustering; tune cautiously.
# Title is a token-set Jaccard (word-bag, no shingling): short news headlines
# reorder words across outlets ("EU adopts X" vs "X: EU adopts") so positional
# n-grams under-cluster. Oneliner is a 4-shingle (LLM rewrites are longer
# and more positional).
_TITLE_JACCARD_THRESHOLD = 0.6
_ONELINER_JACCARD_THRESHOLD = 0.4
_TITLE_MIN_OVERLAP = 3  # at least this many shared content tokens for a title match


def cluster_items(
    items: list[Item],
    sources: list[Source] | None = None,
) -> list[Item]:
    """Annotate each item with cluster_id / cluster_role / cluster_peers.

    Returns the input list (same objects, mutated).
    """
    if not items:
        return items
    by_id: dict[str, Source] = {s.id: s for s in sources or []}

    # Bucket by (primary topic, dominant region) to cap pairwise comparisons.
    buckets: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for it in items:
        topic = it.topics[0] if it.topics else "_"
        region = it.regions[0] if it.regions else "_"
        buckets[(topic, region)].append(it)

    # Union-find by item index in the global list.
    parent: dict[int, int] = {id(it): id(it) for it in items}

    def find(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Within each bucket, pairwise compare. Bucket sizes are small (<25 typ).
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        # Pre-compute token bags / shingles once per item.
        title_tokens = [_tokens(_normalize(it.title)) for it in bucket]
        oneliner_shingles = [
            _shingles(_normalize(it.summary_oneliner), 4) if it.summary_oneliner else set()
            for it in bucket
        ]
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i], bucket[j]
                if a.source == b.source:
                    continue  # different stories from same outlet, not duplicates
                if not _similar(
                    title_tokens[i], title_tokens[j],
                    oneliner_shingles[i], oneliner_shingles[j],
                    a.regions, b.regions,
                ):
                    continue
                union(id(a), id(b))

    # Materialize clusters from union-find.
    clusters: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        clusters[find(id(it))].append(it)

    n_singletons = 0
    n_clusters = 0
    largest = 0
    for cluster in clusters.values():
        if len(cluster) == 1:
            # Leave singleton fields empty (defaults) — render path treats
            # cluster_role == "" as "no clustering decision".
            n_singletons += 1
            continue
        n_clusters += 1
        largest = max(largest, len(cluster))
        primary = _pick_primary(cluster, by_id)
        cluster_id = _cluster_id_for(primary)
        peers = [
            {"source": it.source, "url": it.url, "title": it.title}
            for it in cluster if it is not primary
        ]
        primary.cluster_id = cluster_id
        primary.cluster_role = "primary"
        primary.cluster_peers = peers
        for it in cluster:
            if it is primary:
                continue
            it.cluster_id = cluster_id
            it.cluster_role = "secondary"
            it.cluster_peers = []

    log.info(
        "clustered %d items: %d singletons, %d clusters (largest=%d)",
        len(items), n_singletons, n_clusters, largest,
    )
    return items


def is_secondary(it: Item) -> bool:
    return it.cluster_role == "secondary"


def is_primary_or_singleton(it: Item) -> bool:
    return it.cluster_role != "secondary"


# ─── Internals ──────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t for t in text.split() if t and t not in _STOPWORDS}


def _shingles(text: str, n: int) -> set[str]:
    if not text:
        return set()
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    if len(tokens) < n:
        # Fall back to a single shingle so very short titles still compare.
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    if not inter:
        return 0.0
    return len(inter) / len(a | b)


def _similar(
    title_a: set[str], title_b: set[str],
    oneliner_a: set[str], oneliner_b: set[str],
    regions_a: list[str], regions_b: list[str],
) -> bool:
    overlap = title_a & title_b
    if (
        len(overlap) >= _TITLE_MIN_OVERLAP
        and _jaccard(title_a, title_b) >= _TITLE_JACCARD_THRESHOLD
    ):
        return True
    # Oneliner similarity is a weaker signal on its own (LLM may rephrase
    # similarly across unrelated stories sharing a region), so require region
    # overlap as confirmation.
    if oneliner_a and oneliner_b:
        if _jaccard(oneliner_a, oneliner_b) >= _ONELINER_JACCARD_THRESHOLD:
            if set(regions_a) & set(regions_b):
                return True
    return False


def _pick_primary(cluster: list[Item], by_id: dict[str, Source]) -> Item:
    """Order: category authority asc, source weight desc, importance desc,
    earliest published_at asc."""

    def key(it: Item) -> tuple:
        cat_rank = _CATEGORY_PRIORITY.get(it.category, 99)
        weight = by_id[it.source].weight if it.source in by_id else 0
        importance = it.importance or 0
        when = it.published_at or it.fetched_at
        return (cat_rank, -weight, -importance, when.timestamp())

    return min(cluster, key=key)


def _cluster_id_for(primary: Item) -> str:
    # Stable, debuggable id — the primary URL works fine, no need for a hash.
    return f"c:{primary.url}"
