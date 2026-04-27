from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DIGEST_DIR = REPO_ROOT / "digests"
DB_PATH = DATA_DIR / "items.sqlite"
SOURCES_PATH = REPO_ROOT / "sources.toml"

# Source categories drive how items are grouped in the digest.
CATEGORIES = (
    "eu_institution",   # EEAS, Council, Commission, Parliament — primary sources
    "swiss_official",   # SECO, EDA/FDFA, Federal Council — primary sources
    "press_eu",         # Brussels press: Politico, EUobserver, Brussels Times
    "press_swiss",      # NZZ, Tagi, SRF, Le Temps
    "press_intl",       # Le Monde Diplomatique, Spiegel, FAZ, etc.
    "think_tank",       # ECFR, Bruegel, CEPS, IFRI
)

# Keyword sets for classify.py.
# Word-bounded matching (\bKW\b), case-insensitive. Lowercase, full forms.
MIDDLE_EAST_KEYWORDS = {
    "israel", "israeli", "israelis", "israels",
    "gaza", "gazan",
    "west bank", "westjordanland",
    "palestine", "palestinian", "palestinians", "palästina",
    "hamas", "hezbollah", "hisbollah",
    "lebanon", "lebanese", "libanon",
    "syria", "syrian", "syrien", "assad",
    "iran", "iranian", "iranisch", "iaea", "jcpoa",
    "yemen", "yemeni", "jemen", "houthi", "houthis", "red sea",
    "egypt", "egyptian", "ägypten",
    "jordan", "jordanian", "jordanien",
    "iraq", "iraqi", "irak",
    "saudi", "saudis", "saudi-arabien",
    "uae", "emirates", "emirati",
    "qatar", "qatari", "katar",
    "bahrain", "bahraini",
    "oman", "omani",
    "kuwait", "kuwaiti",
    "libya", "libyan", "libyen",
    "tunisia", "tunisian", "tunesien",
    "morocco", "moroccan", "marokko",
    "algeria", "algerian", "algerien",
    "sudan", "sudanese",
    "middle east", "mena", "naher osten", "moyen-orient",
}

SANCTIONS_KEYWORDS = {
    "sanction", "sanctions", "sanctioned", "sanctioning",
    "sanktion", "sanktionen",
    "restrictive measure", "restrictive measures",
    "asset freeze", "asset freezes",
    "listing", "listings", "delisting", "delistings",
    "blacklist", "blacklisted",
    "cfsp decision", "council regulation",
    "designate", "designated", "designation", "designations",
    "embargo", "embargoes",
    "export control", "export controls", "exportkontrolle", "exportkontrollen",
    "autonomer nachvollzug", "autonome übernahme",
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
    "außenministerrat", "auswärtige beziehungen",
}

SWISS_RELEVANCE_KEYWORDS = {
    "switzerland", "swiss", "schweiz", "schweizer", "suisse", "svizzera",
    "seco", "fdfa", "eda",
    "neutrality", "neutralität", "neutralité", "neutralità",
    "autonomous nachvollzug", "autonomer nachvollzug",
    "bundesrat", "federal council",
    "embargogesetz",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    type: str  # "rss" | "eeas_html" | "headless_html"
    url: str
    category: str = "eu_institution"
    weight: int = 1
    language: str = "en"
    # CSS selector for headless_html / eeas_html: anchor selector that yields links.
    selector: str = ""
    # Optional CSS selector evaluated *inside* each matched anchor to extract a
    # cleaner title (Council wraps title + time + attribution in one anchor).
    title_selector: str = ""
    # Optional friendly badge for digest output.
    badge: str = ""


def load_sources(path: Path = SOURCES_PATH) -> list[Source]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[Source] = []
    for entry in raw.get("sources", []):
        cat = entry.get("category", "eu_institution")
        if cat not in CATEGORIES:
            raise ValueError(f"source {entry.get('id')!r} has unknown category {cat!r}")
        out.append(Source(**entry))
    return out


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
