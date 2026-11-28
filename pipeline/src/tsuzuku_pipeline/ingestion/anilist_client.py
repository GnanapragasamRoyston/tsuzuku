"""AniList GraphQL (lecture sans clé) : catalogue manga, manhwa et manhua (SPEC § 2.3).

Pages triées par popularité décroissante, contenus adultes exclus côté AniList (isAdult: false)
puis revérifiés ici (genre Hentai). Le type d'œuvre vient du pays d'origine :
JP → manga, KR → manhwa, CN et TW → manhua.
Chez AniList, `type: MANGA` couvre aussi les romans (light novels) : ils sont exclus côté requête
(format_not_in: NOVEL) et ici (défense en profondeur), car ce ne sont pas des mangas. Les
one-shots (histoires en un chapitre) sont des mangas et sont gardés.
"""

import re
from typing import Any

from tsuzuku_pipeline.ingestion.http import HttpError, PoliteClient
from tsuzuku_pipeline.ingestion.records import MediaRecord, as_int, clean_text, display_titles

KIND_BY_COUNTRY = {"JP": "manga", "KR": "manhwa", "CN": "manhua", "TW": "manhua"}
# Rôles retenus comme « créateurs » (auteurs), à la place des studios des animes.
CREATOR_ROLES = ("story", "art", "original creator")

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage currentPage }
    media(type: MANGA, isAdult: false, format_not_in: [NOVEL], sort: POPULARITY_DESC) {
      id idMal countryOfOrigin format status chapters isAdult
      title { romaji english }
      startDate { year }
      genres
      tags { name rank isAdult }
      description(asHtml: false)
      coverImage { extraLarge large color }
      source(version: 3)
      staff(perPage: 6, sort: RELEVANCE) { edges { role node { name { full } } } }
    }
  }
}
"""


# Couvertures des animes du catalogue (dataset 2020 sans images, Jikan en panne) : recherche
# par idMal, l'identifiant MAL que nos animes ont déjà (aucun identifiant deviné).
COVERS_QUERY = """
query ($ids: [Int], $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: ANIME, isAdult: false, idMal_in: $ids) {
      idMal coverImage { extraLarge large color }
    }
  }
}
"""


# Tags des animes du dataset MAL 2020 (phase 13) : le genre « Isekai » n'existait pas chez MAL en
# 2020, seul le tag AniList permet de mesurer la rétention des isekai (page 3 de Power BI). Même
# recherche par idMal ; l'identifiant AniList est gardé (fourni par AniList, jamais deviné).
ANIME_TAGS_QUERY = """
query ($ids: [Int], $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: ANIME, isAdult: false, idMal_in: $ids) {
      id idMal tags { name rank isAdult }
    }
  }
}
"""


def _graphql(client: PoliteClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = client.post_json("", json={"query": query, "variables": variables})
    if body.get("errors"):
        # GraphQL répond 200 avec une liste d'erreurs : ce n'est pas un succès.
        raise HttpError(f"AniList : {body['errors'][0].get('message', 'erreur GraphQL')}")
    page_data = (body.get("data") or {}).get("Page")
    if not isinstance(page_data, dict):
        raise HttpError("AniList : réponse sans Page")
    return page_data


def fetch_page(client: PoliteClient, page: int, per_page: int) -> dict[str, Any]:
    return _graphql(client, QUERY, {"page": page, "perPage": per_page})


HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")


def best_cover(cover: dict[str, Any] | None) -> str | None:
    """La plus grande image : extraLarge (460 px de large) plutôt que large (230 px), mesuré le
    2026-11-22. L'image par défaut d'AniList (« default.jpg ») n'est pas une jaquette."""
    cover = cover or {}
    url = cover.get("extraLarge") or cover.get("large")
    if not isinstance(url, str) or url.rsplit("/", 1)[-1].startswith("default."):
        return None
    return url


def cover_color(cover: dict[str, Any] | None) -> str | None:
    color = ((cover or {}).get("color") or "").lower()
    return color if HEX_COLOR.match(color) else None


def parse_covers(page: dict[str, Any]) -> dict[int, dict[str, str | None]]:
    """{idMal: {url, color}} ; les titres sans idMal ou sans vraie image sont ignorés."""
    covers = {}
    for item in page.get("media") or []:
        url = best_cover(item.get("coverImage"))
        if item.get("idMal") and url:
            covers[int(item["idMal"])] = {"url": url, "color": cover_color(item.get("coverImage"))}
    return covers


def fetch_covers(client: PoliteClient, mal_ids: list[int]) -> dict[int, dict[str, str | None]]:
    """Couvertures d'un lot d'animes (au plus 50 idMal, la taille de page maximale d'AniList)."""
    return parse_covers(_graphql(client, COVERS_QUERY, {"ids": mal_ids, "perPage": len(mal_ids)}))


def kept_tags(tags: list[dict[str, Any]] | None, tag_min_rank: int) -> tuple[tuple[str, int], ...]:
    """Tags gardés : pertinents (rang AniList ≥ tag_min_rank) et jamais adultes."""
    return tuple(
        (t["name"], int(t["rank"]))
        for t in tags or []
        if t.get("name") and not t.get("isAdult") and (t.get("rank") or 0) >= tag_min_rank
    )


def parse_anime_tags(page: dict[str, Any], tag_min_rank: int) -> dict[int, dict[str, Any]]:
    """{idMal: {anilist_id, tags}} ; un titre sans idMal ou sans identifiant AniList est ignoré
    (impossible à rattacher sans deviner). Un titre connu mais sans tag garde son identifiant."""
    found = {}
    for item in page.get("media") or []:
        if item.get("idMal") and item.get("id"):
            found[int(item["idMal"])] = {
                "anilist_id": int(item["id"]),
                "tags": list(kept_tags(item.get("tags"), tag_min_rank)),
            }
    return found


def fetch_anime_tags(
    client: PoliteClient, mal_ids: list[int], tag_min_rank: int
) -> dict[int, dict[str, Any]]:
    """Tags d'un lot d'animes (au plus 50 idMal, la taille de page maximale d'AniList)."""
    page = _graphql(client, ANIME_TAGS_QUERY, {"ids": mal_ids, "perPage": len(mal_ids)})
    return parse_anime_tags(page, tag_min_rank)


def is_adult(item: dict[str, Any]) -> bool:
    return bool(item.get("isAdult")) or "Hentai" in (item.get("genres") or [])


def _creators(item: dict[str, Any]) -> tuple[str, ...]:
    names = []
    for edge in ((item.get("staff") or {}).get("edges")) or []:
        role = (edge.get("role") or "").lower()
        name = (((edge.get("node") or {}).get("name")) or {}).get("full")
        if name and any(r in role for r in CREATOR_ROLES) and name not in names:
            names.append(name)
    return tuple(names)


def media_record(item: dict[str, Any], rank: int, tag_min_rank: int) -> MediaRecord | None:
    """Titre AniList → MediaRecord ; None si adulte ou pays d'origine non couvert."""
    kind = KIND_BY_COUNTRY.get(item.get("countryOfOrigin") or "")
    if kind is None or is_adult(item) or item.get("format") == "NOVEL":
        return None
    title, title_alt = display_titles(
        (item.get("title") or {}).get("romaji"), (item.get("title") or {}).get("english")
    )
    cover_url = best_cover(item.get("coverImage"))
    tags = kept_tags(item.get("tags"), tag_min_rank)
    return MediaRecord(
        kind=kind,
        anilist_id=int(item["id"]),
        # idMal fourni par AniList (jamais deviné, CLAUDE.md § 6).
        mal_id=as_int(item.get("idMal")),
        title=title,
        title_alt=title_alt,
        synopsis=clean_text(item.get("description")),
        chapters=as_int(item.get("chapters")),
        airing_status=item.get("status"),
        format=item.get("format"),
        start_year=as_int((item.get("startDate") or {}).get("year")),
        creators=_creators(item),
        source=item.get("source"),
        cover_url=cover_url,
        cover_color=cover_color(item.get("coverImage")) if cover_url else None,
        cover_source="anilist" if cover_url else None,
        # Rang dans le tri par popularité (1 = le plus populaire) : même sémantique que le rang
        # MAL des animes, pour que « trier par popularité » ait un sens dans tout le catalogue.
        popularity=rank,
        genres=tuple(item.get("genres") or ()),
        tags=tags,
    )
