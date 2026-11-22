"""Texte embarqué d'une œuvre : titre, type, genres, tags et synopsis (SPEC § 6.3).

Pur (aucune base, aucun modèle) : testable seul. L'ordre compte : les modèles tronquent les
textes trop longs par la fin, on met donc d'abord ce qui identifie l'œuvre (titre, type, genres,
tags), et le synopsis en dernier.
"""

from collections.abc import Sequence

KIND_LABEL = {"anime": "Anime", "manga": "Manga", "manhwa": "Manhwa", "manhua": "Manhua"}


def media_text(
    *,
    title: str,
    title_alt: str | None,
    kind: str,
    genres: Sequence[str],
    tags: Sequence[str],
    synopsis: str | None,
) -> str:
    head = f"{title} ({title_alt})" if title_alt else title
    parts = [f"{head}.", f"{KIND_LABEL.get(kind, kind)}."]
    if genres:
        parts.append(f"Genres: {', '.join(genres)}.")
    if tags:
        parts.append(f"Tags: {', '.join(tags)}.")
    if synopsis and synopsis.strip():
        parts.append(synopsis.strip())
    return " ".join(parts)
