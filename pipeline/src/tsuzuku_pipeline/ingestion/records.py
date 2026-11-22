"""Enregistrements communs aux sources Jikan et AniList, prêts pour le chargement Postgres.

Python pur (aucun import Spark) : ce module tourne dans l'image Airflow, qui n'a pas PySpark.
"""

import re
from dataclasses import dataclass, field
from html import unescape


def display_titles(original: str | None, english: str | None) -> tuple[str, str | None]:
    """(titre affiché, titre secondaire). Le titre anglais d'abord, celui que tout le monde
    connaît (« Solo Leveling » et non « Na Honjaman Level Up ») ; le titre d'origine romanisé
    reste en titre secondaire, donc trouvable par la recherche. S'ils ne diffèrent que par la
    ponctuation, les espaces ou la casse (« Fullmetal Alchemist:Brotherhood »), l'original est
    gardé, souvent mieux écrit, et il n'y a pas de titre secondaire en double."""
    original = (original or "").strip() or None
    english = (english or "").strip() or None
    if not english or (original and title_key(english) == title_key(original)):
        return original or english or "", None
    return english, original


def title_key(title: str) -> str:
    """Titre réduit à ses lettres et chiffres ASCII, en minuscules (même règle que Spark)."""
    return re.sub(r"[^0-9a-z]", "", title.lower())


@dataclass(frozen=True)
class MediaRecord:
    """Une œuvre, au format des colonnes de catalog.media (+ genres et tags)."""

    kind: str
    title: str
    mal_id: int | None = None
    anilist_id: int | None = None
    title_alt: str | None = None
    synopsis: str | None = None
    episodes: int | None = None
    chapters: int | None = None
    airing_status: str | None = None
    format: str | None = None
    duration_min: float | None = None
    start_year: int | None = None
    creators: tuple[str, ...] = ()
    source: str | None = None
    age_rating: str | None = None
    cover_url: str | None = None
    # Couleur dominante de la jaquette (#rrggbb, fournie par AniList) et origine de l'image
    # ('anilist', 'jikan' ; 'suggestion' = proposée par un utilisateur et validée par Royston).
    cover_color: str | None = None
    cover_source: str | None = None
    popularity: int | None = None
    genres: tuple[str, ...] = ()
    tags: tuple[tuple[str, int], ...] = field(default_factory=tuple)  # (nom, rang 0-100)


@dataclass(frozen=True)
class StatsRecord:
    """Statistiques d'un anime à une date (catalog.media_daily_stats)."""

    mal_id: int
    score: float | None
    members: int | None
    watching: int | None
    completed: int | None
    on_hold: int | None
    dropped: int | None
    plan_to_watch: int | None
    in_season: bool = True  # False : anime de la watchlist hors saison en cours


_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t]+")


def clean_text(text: str | None) -> str | None:
    """Synopsis lisible : balises HTML retirées, entités décodées, espaces normalisés."""
    if not text:
        return None
    out = _TAGS.sub(" ", text.replace("<br>", "\n").replace("<br/>", "\n"))
    out = _SPACES.sub(" ", unescape(out))
    out = "\n".join(line.strip() for line in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip() or None


def as_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
