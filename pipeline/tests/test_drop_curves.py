"""Courbes de drop, épisode critique, point de non-retour — cas calculés à la main.

Anime 1 (4 épisodes) :
  - 6 Completed (dont 2 avec watched_episodes < 4 : le statut fait foi)
  - Dropped à 0, 1, 2, 2, et 6 (> 4 épisodes → plafonné à 4)
  Drops par épisode : 0→1, 1→1, 2→2, 4→1 (total 5 ; 4 après avoir commencé)
  Part cumulée      : 0.2, 0.4, 0.8, 1.0
  Épisode critique  : 2 (2 drops sur 4 après le début → part 0.5)
  Risque de lâcher pour qui a atteint e : drops avec reached ≥ e / (completed + ces drops)
    e=1 : 4/10 = 0.40 (risque de départ)   e=2 : 3/9 = 0.33   e=3 : 1/7 = 0.14   e=4 : 1/7 = 0.14
  Point de non-retour = 1er e où risque ≤ ratio × 0.40 :
    ratio 0.4  → cible 0.16 → e=3
    ratio 0.25 → cible 0.10 → jamais atteint → null
Anime 2 (épisodes inconnus) : 1 drop à 3 → courbe oui, épisode critique non.
Anime 3 (film, 1 épisode)   : exclu de l'épisode critique par min_episodes.
Anime 4 (5 épisodes)        : 2 drops à 1, 2 drops à 3, aucun Completed
  → égalité : le plus petit épisode gagne (1) ; risque toujours 1 → point de non-retour null.
"""

import pytest

from tsuzuku_pipeline.spark.drop_curves import critical_episodes, drop_curve, outcomes

COMPLETED, DROPPED, WATCHING = 2, 4, 1
LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"


def _data(spark):
    rows = [(u, 1, 8, COMPLETED, 4) for u in range(4)]
    rows += [(4, 1, 8, COMPLETED, 2), (5, 1, 8, COMPLETED, 0)]
    rows += [(10, 1, 0, DROPPED, 0), (11, 1, 0, DROPPED, 1), (12, 1, 0, DROPPED, 2)]
    rows += [(13, 1, 0, DROPPED, 2), (14, 1, 0, DROPPED, 6)]
    rows += [(15, 1, 0, WATCHING, 1)]  # ignoré : issue inconnue
    rows += [(20, 2, 0, DROPPED, 3)]
    rows += [(30, 3, 0, DROPPED, 1)] + [(31 + i, 3, 0, DROPPED, 0) for i in range(5)]
    rows += [(40, 4, 0, DROPPED, 1), (41, 4, 0, DROPPED, 1)]
    rows += [(42, 4, 0, DROPPED, 3), (43, 4, 0, DROPPED, 3)]
    animelist = spark.createDataFrame(rows, LIST_SCHEMA)
    anime = spark.createDataFrame([(1, 4), (2, None), (3, 1), (4, 5)], "anime_id int, episodes int")
    return outcomes(animelist, anime, completed=COMPLETED, dropped=DROPPED)


def _critical(spark, risk_ratio=0.4, min_drops=4, min_episodes=3):
    df = critical_episodes(
        _data(spark), risk_ratio=risk_ratio, min_drops=min_drops, min_episodes=min_episodes
    )
    return {r["anime_id"]: r for r in df.collect()}


def test_outcomes_keep_only_completed_and_dropped(spark):
    assert _data(spark).where("anime_id = 1").count() == 11


def test_outcomes_reached_rules(spark):
    rows = _data(spark).where("anime_id = 1").collect()
    completed = [r["reached"] for r in rows if not r["is_dropped"]]
    dropped = sorted(r["reached"] for r in rows if r["is_dropped"])
    assert completed == [4] * 6  # statut Completed = tout vu, même si watched_episodes < 4
    assert dropped == [0, 1, 2, 2, 4]  # 6 plafonné à 4


def test_drop_curve(spark):
    curve = {
        (r["anime_id"], r["episode"]): (r["nb_drops"], r["cumulative_share"])
        for r in drop_curve(_data(spark)).collect()
    }
    assert curve[(1, 0)] == (1, pytest.approx(0.2))
    assert curve[(1, 1)] == (1, pytest.approx(0.4))
    assert curve[(1, 2)] == (2, pytest.approx(0.8))
    assert curve[(1, 4)] == (1, pytest.approx(1.0))
    assert (1, 3) not in curve  # pas de ligne pour un épisode sans drop
    assert curve[(2, 3)] == (1, pytest.approx(1.0))  # épisodes inconnus : courbe quand même


def test_critical_episode_and_point_of_no_return(spark):
    a1 = _critical(spark)[1]
    assert a1["critical_episode"] == 2
    assert a1["critical_drop_share"] == pytest.approx(0.5)
    assert a1["initial_drop_risk"] == pytest.approx(0.4)
    assert a1["point_of_no_return"] == 3
    assert a1["nb_drops"] == 5
    assert a1["nb_completed"] == 6
    assert a1["drop_rate"] == pytest.approx(5 / 11)


def test_point_of_no_return_null_when_never_reached(spark):
    assert _critical(spark, risk_ratio=0.25)[1]["point_of_no_return"] is None


def test_critical_episode_exclusions(spark):
    ids = set(_critical(spark))
    assert 2 not in ids  # nombre d'épisodes inconnu
    assert 3 not in ids  # film : moins de min_episodes
    assert ids == {1, 4}


def test_min_drops_counts_only_drops_after_start(spark):
    # Anime 1 : 5 drops dont 1 à l'épisode 0 → seulement 4 "utiles".
    assert 1 not in _critical(spark, min_drops=5)


def test_tie_and_no_completion(spark):
    a4 = _critical(spark)[4]
    assert a4["critical_episode"] == 1
    assert a4["point_of_no_return"] is None
    assert a4["drop_rate"] == pytest.approx(1.0)


@pytest.mark.parametrize(("min_drops", "min_episodes"), [(0, 3), (4, 0)])
def test_thresholds_must_be_at_least_one(spark, min_drops, min_episodes):
    with pytest.raises(ValueError, match="≥ 1"):
        critical_episodes(
            _data(spark), risk_ratio=0.4, min_drops=min_drops, min_episodes=min_episodes
        )


@pytest.mark.parametrize("ratio", [0, 1, 1.5, -0.2])
def test_risk_ratio_must_be_strictly_between_0_and_1(spark, ratio):
    with pytest.raises(ValueError, match="risk_ratio"):
        critical_episodes(_data(spark), risk_ratio=ratio, min_drops=4, min_episodes=3)
