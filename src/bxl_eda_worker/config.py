from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DIGEST_DIR = REPO_ROOT / "digests"
DB_PATH = DATA_DIR / "items.sqlite"
SOURCES_PATH = REPO_ROOT / "sources.toml"

# Keyword sets for classify.py.
# All matching is case-insensitive and word-bounded (\bKW\b), so we list
# explicit forms (palestinian, palestine) rather than stems (palestin).
MIDDLE_EAST_KEYWORDS = {
    "israel", "israeli", "israelis",
    "gaza", "gazan",
    "west bank",
    "palestine", "palestinian", "palestinians",
    "hamas", "hezbollah",
    "lebanon", "lebanese",
    "syria", "syrian", "assad",
    "iran", "iranian", "iaea", "jcpoa",
    "yemen", "yemeni", "houthi", "houthis", "red sea",
    "egypt", "egyptian",
    "jordan", "jordanian",
    "iraq", "iraqi",
    "saudi", "saudis",
    "uae", "emirates", "emirati",
    "qatar", "qatari",
    "bahrain", "bahraini",
    "oman", "omani",
    "kuwait", "kuwaiti",
    "libya", "libyan",
    "tunisia", "tunisian",
    "morocco", "moroccan",
    "algeria", "algerian",
    "sudan", "sudanese",
    "middle east", "mena",
}

SANCTIONS_KEYWORDS = {
    "sanction", "sanctions", "sanctioned", "sanctioning",
    "restrictive measure", "restrictive measures",
    "asset freeze", "asset freezes",
    "listing", "listings", "delisting", "delistings",
    "blacklist", "blacklisted",
    "cfsp decision", "council regulation",
    "designate", "designated", "designation", "designations",
    "embargo", "embargoes",
    "export control", "export controls",
}

HIGH_FP_KEYWORDS = {
    "foreign affairs council", "fac",
    "european council conclusions", "council conclusions",
    "high representative", "hr/vp",
    "kallas",  # Kaja Kallas, current HR/VP
    "joint statement",
    "enlargement", "accession",
    "ukraine", "russia",
    "china", "taiwan",
    "summit",
}

SWISS_RELEVANCE_KEYWORDS = {
    "switzerland", "swiss", "seco", "fdfa", "eda",
    "neutrality", "neutralität", "neutralité",
    "autonomous nachvollzug",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    type: str  # "rss" or "eeas_html"
    url: str
    weight: int = 1


def load_sources(path: Path = SOURCES_PATH) -> list[Source]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return [Source(**entry) for entry in raw.get("sources", [])]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
