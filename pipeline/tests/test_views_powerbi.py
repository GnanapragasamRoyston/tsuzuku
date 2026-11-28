"""Vues Power BI du schéma bi sur catalog et mart (phase 13, SPEC § 11, ADR 016)."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tsuzuku_pipeline.db import loader

pytestmark = pytest.mark.db

PIPELINE_VIEWS = {
    "anime_drop", "anime_genre", "anime_studio", "anime_segment", "segment_retention",
    "drop_curve", "retention_by_genre", "retention_by_studio", "daily_stats", "model_metrics",
}  # fmt: skip


UPSERT_LABEL = ("INSERT INTO catalog.{} (name) VALUES (%s) ON CONFLICT (name)"
                " DO UPDATE SET name = EXCLUDED.name RETURNING id")  # fmt: skip


def _anime(pg, mal, title, studios=(), genres=(), tags=(), drops=None):
    mid = pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, title, format, episodes, start_year, popularity,"
        " creators, data_source) VALUES ('anime', %s, %s, 'TV', 12, 2015, %s, %s,"
        " 'mal_kaggle_2020') RETURNING id",
        (mal, title, mal, list(studios)),
    ).fetchone()[0]
    for g in genres:
        gid = pg.execute(UPSERT_LABEL.format("genre"), (g,)).fetchone()[0]
        pg.execute("INSERT INTO catalog.media_genre VALUES (%s, %s)", (mid, gid))
    for t in tags:
        tid = pg.execute(UPSERT_LABEL.format("tag"), (t,)).fetchone()[0]
        pg.execute("INSERT INTO catalog.media_tag VALUES (%s, %s, 90)", (mid, tid))
    if drops is not None:
        nb_drops, nb_completed = drops
        pg.execute(
            "INSERT INTO mart.critical_episode (media_id, critical_episode, critical_drop_share,"
            " initial_drop_risk, point_of_no_return, nb_drops, nb_completed, drop_rate)"
            " VALUES (%s, 2, 0.4, 0.1, 5, %s, %s, %s)",
            (mid, nb_drops, nb_completed, nb_drops / (nb_drops + nb_completed)),
        )
    return mid


@pytest.fixture
def catalog(pg):
    return {
        # Isekai (tag AniList) ET Shounen (genre MAL) : compte dans les deux segments.
        "isekai": _anime(
            pg,
            1,
            "Isekai Shounen",
            ["Studio A", "Studio B"],
            ["Shounen", "Action"],
            ["Isekai"],
            drops=(30, 70),
        ),  # fmt: skip
        "shounen": _anime(pg, 2, "Shounen seul", ["Studio A"], ["Shounen"], drops=(10, 90)),
        "other": _anime(pg, 3, "Autre", [], ["Drama"], ["Reverse Isekai"], drops=(50, 50)),
        "no_data": _anime(pg, 4, "Sans données", ["Studio C"], ["Shounen"], ["Isekai"]),
    }


def _rows(pg, query, *args):
    return pg.execute(query, args or None).fetchall()


def test_views_exist_and_reapplying_the_schemas_is_idempotent(pg):
    loader.apply_schemas(pg)
    loader.apply_schemas(pg)
    views = {r[0] for r in _rows(pg, "SELECT table_name FROM information_schema.views"
                                     " WHERE table_schema = 'bi'")}  # fmt: skip
    assert views == PIPELINE_VIEWS


def test_unchanged_views_are_not_reapplied_while_power_bi_reads_them(pg, pg_url, catalog):
    """CREATE OR REPLACE VIEW pose un verrou exclusif même sans changement : un rafraîchissement
    Power BI en cours ferait échouer le job d'ingestion du jour (revue de la phase 13). Les vues
    ne sont réappliquées que si views_powerbi.sql a changé (empreinte) ou si l'une manque."""
    with psycopg.connect(pg_url) as reader:
        reader.execute("SELECT count(*) FROM bi.anime_drop").fetchone()  # transaction ouverte
        loader.apply_schemas(pg, lock_timeout="300ms")  # rien à refaire : aucun verrou demandé
        reader.rollback()


def test_views_are_reapplied_when_one_is_missing_or_the_file_changed(pg):
    pg.execute("DROP VIEW bi.daily_stats")
    loader.apply_schemas(pg)
    assert _rows(pg, "SELECT to_regclass('bi.daily_stats') IS NOT NULL") == [(True,)]
    pg.execute("COMMENT ON SCHEMA bi IS 'views_powerbi sha256:ancienne-version'")
    pg.execute("DROP VIEW bi.retention_by_genre")  # « ancienne version » : une seule colonne
    pg.execute("CREATE VIEW bi.retention_by_genre AS SELECT 'x'::text AS genre")
    loader.apply_schemas(pg)  # empreinte différente : tout le fichier est réappliqué
    query = ("SELECT count(*) FROM information_schema.columns"
             " WHERE table_schema = 'bi' AND table_name = 'retention_by_genre'")  # fmt: skip
    columns = _rows(pg, query)
    assert columns == [(7,)]


def test_anime_drop_has_one_row_per_anime_with_drop_data(pg, catalog):
    rows = _rows(pg, "SELECT media_id, title, nb_drops, nb_completed, nb_finished, drop_rate,"
                     " critical_episode, point_of_no_return, studios FROM bi.anime_drop"
                     " ORDER BY media_id")  # fmt: skip
    # « Sans données » n'a pas de ligne dans le mart : absent.
    assert [r[1] for r in rows] == ["Isekai Shounen", "Shounen seul", "Autre"]
    first = rows[0]
    assert first[2:5] == (30, 70, 100)  # lâchés, terminés, total « lâchés + terminés »
    assert first[5] == pytest.approx(0.3) and first[6:8] == (2, 5)
    assert first[8] == "Studio A, Studio B"


def test_bridges_list_genres_and_studios_of_animes_with_drop_data(pg, catalog):
    studios = _rows(pg, "SELECT studio, count(*) FROM bi.anime_studio GROUP BY 1 ORDER BY 1")
    assert studios == [("Studio A", 2), ("Studio B", 1)]  # Studio C : anime sans données
    genres = dict(_rows(pg, "SELECT genre, count(*) FROM bi.anime_genre GROUP BY 1"))
    assert genres == {"Shounen": 2, "Action": 1, "Drama": 1}


def test_segments_overlap_and_rates_are_recomputed_from_counts(pg, catalog):
    seg = dict(_rows(pg, "SELECT media_id, array_agg(segment ORDER BY segment)"
                         " FROM bi.anime_segment GROUP BY 1"))  # fmt: skip
    assert seg[catalog["isekai"]] == ["Isekai", "Shounen"]
    assert seg[catalog["shounen"]] == ["Shounen"]
    assert seg[catalog["other"]] == ["Autres"]  # « Reverse Isekai » n'est pas « Isekai »
    assert catalog["no_data"] not in seg
    query = "SELECT segment, nb_anime, nb_drops, nb_completed, drop_rate FROM bi.segment_retention"
    retention = {r[0]: r[1:] for r in _rows(pg, query)}
    # Taux = Σ lâchés / Σ (lâchés + terminés), jamais une moyenne de taux.
    assert retention["Shounen"][:3] == (2, 40, 160)
    assert retention["Shounen"][3] == pytest.approx(40 / 200)
    assert retention["Isekai"][:3] == (1, 30, 70)
    assert retention["Autres"][3] == pytest.approx(0.5)


def test_drop_curve_marks_critical_and_point_of_no_return(pg, catalog):
    mid = catalog["isekai"]
    for ep, n, cum in ((0, 5, 0.17), (2, 20, 0.83), (5, 5, 1.0)):
        pg.execute("INSERT INTO mart.drop_curve VALUES (%s, %s, %s, %s)", (mid, ep, n, cum))
    rows = _rows(pg, "SELECT episode, share, is_critical, is_point_of_no_return"
                     " FROM bi.drop_curve WHERE media_id = %s ORDER BY episode", mid)  # fmt: skip
    assert [(r[0], r[2], r[3]) for r in rows] == [(0, False, False), (2, True, False),
                                                    (5, False, True)]  # fmt: skip
    assert sum(r[1] for r in rows) == pytest.approx(1.0)  # part des drops de l'anime, par épisode


def test_model_metrics_are_flattened_and_only_the_latest_run_is_flagged(pg):
    def run(rid, when, model, metrics):
        pg.execute(
            "INSERT INTO mart.model_runs (run_id, created_at, model_name, model_type, params,"
            " metrics, data_fingerprint) VALUES (%s, %s, %s, 'x', '{}', %s, 'fp')",
            (rid, when, model, Jsonb(metrics)),
        )

    run("00000000-0000-0000-0000-000000000001", "2026-11-15", "drop", {"test": {"roc_auc": 0.88}})
    run("00000000-0000-0000-0000-000000000002", "2026-11-16", "drop",
        {"test": {"roc_auc": 0.90, "confusion": {"tp": 7}, "note": "texte ignoré"}})  # fmt: skip
    run("00000000-0000-0000-0000-000000000003", "2026-11-16", "reco",
        {"test": {"at_k": {"10": {"ndcg": 0.49}}}})  # fmt: skip
    latest = dict(_rows(pg, "SELECT model_name || ':' || metric, value FROM bi.model_metrics"
                            " WHERE is_latest"))  # fmt: skip
    assert latest == {"drop:test.roc_auc": pytest.approx(0.90), "drop:test.confusion.tp": 7,
                      "reco:test.at_k.10.ndcg": pytest.approx(0.49)}  # fmt: skip
    assert _rows(pg, "SELECT count(*) FROM bi.model_metrics WHERE NOT is_latest") == [(1,)]


def test_daily_stats_carry_the_title(pg, catalog):
    pg.execute(
        "INSERT INTO catalog.media_daily_stats (snapshot_date, media_id, score, members, source)"
        " VALUES ('2026-11-28', %s, 8.1, 1000, 'jikan')",
        (catalog["shounen"],),
    )
    assert _rows(pg, "SELECT title, members FROM bi.daily_stats") == [("Shounen seul", 1000)]
