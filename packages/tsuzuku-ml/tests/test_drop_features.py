"""feature_row en Python pur (la parité exacte avec Spark est testée côté pipeline)."""

import pytest
from tsuzuku_ml.drop_features import (
    FORBIDDEN_COLUMNS,
    AnimeInfo,
    Entry,
    feature_columns,
    feature_row,
)

GENRES = ["Action", "Drama"]
CATALOG = {
    1: AnimeInfo(genres=("Action",), format="TV", episodes=12, studios=("Bones",)),
    2: AnimeInfo(genres=("Drama",), format="Movie", episodes=1),
    3: AnimeInfo(genres=("Action", "Drama"), format="TV", episodes=24),
}


def test_feature_row_leave_one_out_and_contract():
    entries = [
        Entry(1, "completed", 8),
        Entry(2, "dropped", None),
        Entry(3, "completed", 6),  # la cible : exclue de ses propres features
        Entry(999, "dropped", 2),  # hors catalogue : ignorée, comme la jointure Spark
    ]
    row = feature_row(entries, 3, CATALOG, GENRES)
    assert list(row) == feature_columns(GENRES)
    assert not FORBIDDEN_COLUMNS & set(row)
    assert row["user_list_size"] == 2 and row["user_cd_count"] == 2
    assert row["user_drop_rate"] == 0.5
    assert row["user_mean_score"] == 8  # la note 6 est celle de la cible, la 2 hors catalogue
    assert row["genre_action"] == 1 and row["genre_drama"] == 1
    assert row["genre_affinity"] == pytest.approx((0.5 + 0.5) / 2)


def test_feature_row_empty_list_gives_missing_user_features():
    row = feature_row([], 1, CATALOG, GENRES)
    assert row["user_list_size"] == 0
    assert row["user_drop_rate"] is None and row["genre_affinity"] is None
    assert row["main_studio"] == "Bones"


def test_unknown_target_has_missing_anime_features():
    row = feature_row([Entry(1, "completed", 7)], 12345, CATALOG, GENRES)
    assert row["format"] is None and row["episodes"] is None
    assert row["genre_action"] == 0
