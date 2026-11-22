"""Conversion des réponses Jikan et AniList en enregistrements (sans réseau)."""

import httpx
import pytest

from tsuzuku_pipeline.ingestion import anilist_client, jikan_client
from tsuzuku_pipeline.ingestion.http import HttpError, PoliteClient
from tsuzuku_pipeline.ingestion.records import clean_text

JIKAN_ITEM = {
    "mal_id": 52991, "title": "Sousou no Frieren", "title_english": "Frieren", "type": "TV",
    "episodes": 28, "status": "Finished Airing", "duration": "24 min per ep", "year": 2023,
    "source": "Manga", "rating": "PG-13 - Teens 13 or older", "popularity": 120,
    "score": 9.3, "members": 1200000, "synopsis": "Elfe &amp; mage.<br>Fin.",
    "studios": [{"name": "Madhouse"}], "genres": [{"name": "Adventure"}],
    "themes": [{"name": "Fantasy"}], "demographics": [{"name": "Shounen"}],
    "images": {"jpg": {"image_url": "s.jpg", "large_image_url": "l.jpg"}},
}  # fmt: skip


def test_jikan_media_record_maps_mal_columns():
    r = jikan_client.media_record(JIKAN_ITEM)
    assert (r.kind, r.mal_id, r.format, r.episodes, r.start_year) == (
        "anime",
        52991,
        "TV",
        28,
        2023,
    )
    assert r.creators == ("Madhouse",) and r.cover_url == "l.jpg" and r.popularity == 120
    assert r.genres == ("Adventure", "Fantasy", "Shounen")
    assert r.duration_min == 24 and r.synopsis == "Elfe & mage.\nFin."


@pytest.mark.parametrize(("text", "minutes"), [
    ("24 min per ep", 24), ("1 hr 55 min", 115), ("2 hr", 120), ("45 sec", 0.75),
    ("Unknown", None), (None, None),
])  # fmt: skip
def test_duration_minutes(text, minutes):
    assert jikan_client.duration_minutes(text) == minutes


def test_jikan_year_falls_back_to_aired_date():
    item = {**JIKAN_ITEM, "year": None, "aired": {"prop": {"from": {"year": 2019}}}}
    assert jikan_client.media_record(item).start_year == 2019


@pytest.mark.parametrize("item", [
    {"rating": "Rx - Hentai"}, {"genres": [{"name": "Hentai"}]},
    {"explicit_genres": [{"name": "Hentai"}]},
])  # fmt: skip
def test_jikan_adult_rule(item):
    assert jikan_client.is_adult(item)


def _client(handler):
    return PoliteClient("https://api.test", timeout_s=1, min_interval_s=0, max_retries=0,
                        transport=httpx.MockTransport(handler), sleep=lambda s: None)  # fmt: skip


def test_season_now_paginates_dedups_and_filters_adult():
    pages = {
        "1": {"data": [{"mal_id": 1, "rating": "PG-13"}, {"mal_id": 2, "rating": "Rx - Hentai"}],
              "pagination": {"has_next_page": True}},
        "2": {"data": [{"mal_id": 1, "rating": "PG-13"}, {"mal_id": 3}],
              "pagination": {"has_next_page": False}},
    }  # fmt: skip

    def handler(request):
        assert request.url.params["sfw"] == "true"
        return httpx.Response(200, json=pages[request.url.params["page"]])

    items = jikan_client.season_now(_client(handler), max_pages=5)
    assert sorted(i["mal_id"] for i in items) == [1, 3]


def test_statistics_combines_counts_and_item_score():
    def handler(request):
        assert request.url.path == "/anime/52991/statistics"
        return httpx.Response(200, json={"data": {"watching": 10, "completed": 5, "on_hold": 1,
                                                  "dropped": 2, "plan_to_watch": 30}})  # fmt: skip

    s = jikan_client.statistics(_client(handler), JIKAN_ITEM)
    assert (s.score, s.members, s.dropped, s.plan_to_watch) == (9.3, 1200000, 2, 30)


ANILIST_ITEM = {
    "id": 30013, "idMal": 13, "countryOfOrigin": "JP", "format": "MANGA", "status": "RELEASING",
    "chapters": None, "isAdult": False, "title": {"romaji": "One Piece", "english": "One Piece"},
    "startDate": {"year": 1997}, "genres": ["Action", "Adventure"],
    "tags": [{"name": "Pirates", "rank": 95, "isAdult": False},
             {"name": "Ensemble Cast", "rank": 40, "isAdult": False},
             {"name": "Nudity", "rank": 70, "isAdult": True}],
    "description": "Gol D. Roger<br><br><i>Le trésor</i>", "coverImage": {"large": "c.jpg"},
    "source": "ORIGINAL",
    "staff": {"edges": [{"role": "Story & Art", "node": {"name": {"full": "Eiichiro Oda"}}},
                        {"role": "Editing", "node": {"name": {"full": "Editeur"}}}]},
}  # fmt: skip


@pytest.mark.parametrize(("country", "kind"), [("JP", "manga"), ("KR", "manhwa"), ("CN", "manhua"),
                                               ("TW", "manhua")])  # fmt: skip
def test_anilist_kind_from_country(country, kind):
    assert (
        anilist_client.media_record({**ANILIST_ITEM, "countryOfOrigin": country}, 1, 60).kind
        == kind
    )


def test_anilist_record_fields():
    r = anilist_client.media_record(ANILIST_ITEM, rank=3, tag_min_rank=60)
    assert (r.anilist_id, r.mal_id, r.title, r.popularity) == (30013, 13, "One Piece", 3)
    assert r.creators == ("Eiichiro Oda",)  # l'éditeur n'est pas un créateur
    assert r.tags == (("Pirates", 95),)  # sous le rang minimal et tags adultes exclus
    assert r.synopsis == "Gol D. Roger\n\nLe trésor"


@pytest.mark.parametrize("change", [{"isAdult": True}, {"genres": ["Hentai"]},
                                    {"countryOfOrigin": "FR"}])  # fmt: skip
def test_anilist_adult_or_uncovered_country_is_skipped(change):
    assert anilist_client.media_record({**ANILIST_ITEM, **change}, 1, 60) is None


def test_anilist_graphql_errors_are_failures():
    client = _client(lambda r: httpx.Response(200, json={"errors": [{"message": "Too Many"}]}))
    with pytest.raises(HttpError, match="Too Many"):
        anilist_client.fetch_page(client, 1, 50)


def test_clean_text_handles_empty():
    assert clean_text("") is None and clean_text(None) is None


CDN = "https://s4.anilist.co/file/anilistcdn/media/manga/cover"


# --- Titres et jaquettes (lot « qualité des jaquettes ») -----------------------------------------
@pytest.mark.parametrize(("titles", "title", "alt"), [
    ({"romaji": "Na Honjaman Level Up", "english": "Solo Leveling"}, "Solo Leveling",
     "Na Honjaman Level Up"),
    ({"romaji": "One Piece", "english": "One Piece"}, "One Piece", None),
    ({"romaji": "Oshi no Ko", "english": None}, "Oshi no Ko", None),
    # Ne diffèrent que par la ponctuation ou les espaces : l'original, mieux écrit, est gardé.
    ({"romaji": "Fullmetal Alchemist: Brotherhood", "english": "Fullmetal Alchemist:Brotherhood"},
     "Fullmetal Alchemist: Brotherhood", None),
])  # fmt: skip
def test_anilist_shows_the_english_title_first(titles, title, alt):
    # Le titre que tout le monde connaît (Solo Leveling) ; le romaji reste cherchable en titre_alt.
    r = anilist_client.media_record({**ANILIST_ITEM, "title": titles}, 1, 60)
    assert (r.title, r.title_alt) == (title, alt)


def test_jikan_shows_the_english_title_first():
    r = jikan_client.media_record(JIKAN_ITEM)
    assert (r.title, r.title_alt) == ("Frieren", "Sousou no Frieren")


@pytest.mark.parametrize(("cover", "url", "color"), [
    # extraLarge (460 px de large, mesuré le 2026-11-22) plutôt que large (230 px).
    ({"extraLarge": f"{CDN}/large/b.jpg", "large": f"{CDN}/medium/b.jpg", "color": "#E4A15D"},
     f"{CDN}/large/b.jpg", "#e4a15d"),
    ({"large": f"{CDN}/medium/b.jpg", "color": None}, f"{CDN}/medium/b.jpg", None),
    # Image par défaut d'AniList : ce n'est pas une jaquette.
    ({"extraLarge": f"{CDN}/large/default.jpg", "color": "#fff"}, None, None),
    ({"extraLarge": f"{CDN}/large/c.jpg", "color": "rouge"}, f"{CDN}/large/c.jpg", None),
])  # fmt: skip
def test_anilist_best_cover_and_color(cover, url, color):
    r = anilist_client.media_record({**ANILIST_ITEM, "coverImage": cover}, 1, 60)
    assert (r.cover_url, r.cover_color) == (url, color)
    assert r.cover_source == ("anilist" if url else None)
