"""Embeddings des œuvres (phase 10, ADR 013) : texte embarqué, calcul idempotent, scorer de contenu.

Aucun modèle téléchargé : un encodeur factice, déterministe, remplace sentence-transformers.
"""

import hashlib

import numpy as np
import pandas as pd
import pytest

from tsuzuku_pipeline.embeddings import evaluate, store
from tsuzuku_pipeline.embeddings.text import media_text
from tsuzuku_pipeline.ml.reco.evaluate import evaluate_users

DIM = 384


class FakeEncoder:
    """Vecteur unitaire déterministe tiré du hachage du texte : même texte → même vecteur."""

    name = "fake-encoder"

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += len(texts)
        out = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).normal(size=DIM)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)


# --- Texte d'une œuvre ---------------------------------------------------------------------------
def test_media_text_has_title_type_genres_tags_and_synopsis():
    text = media_text(title="Solo Leveling", title_alt="Na Honjaman Level Up", kind="manhwa",
                      genres=["Action", "Fantasy"], tags=["Dungeon", "Overpowered"],
                      synopsis="Sung Jin-Woo, le chasseur le plus faible…")  # fmt: skip
    assert text.startswith("Solo Leveling (Na Honjaman Level Up). Manhwa.")
    assert "Genres: Action, Fantasy." in text and "Tags: Dungeon, Overpowered." in text
    assert text.endswith("Sung Jin-Woo, le chasseur le plus faible…")


def test_media_text_skips_missing_parts():
    assert media_text(title="Film", title_alt=None, kind="anime", genres=[], tags=[],
                      synopsis=None) == "Film. Anime."  # fmt: skip


# --- Calcul et stockage --------------------------------------------------------------------------
pytestmark_db = pytest.mark.db


def _media(pg, mid_title, kind="manhwa", synopsis="Une histoire."):
    return pg.execute(
        "INSERT INTO catalog.media (kind, title, synopsis, data_source) VALUES (%s, %s, %s, 'test')"
        " RETURNING id", (kind, mid_title, synopsis),
    ).fetchone()[0]  # fmt: skip


@pytestmark_db
def test_build_is_idempotent_and_recomputes_changed_texts(pg):
    a = _media(pg, "A")
    _media(pg, "B", kind="anime")
    enc = FakeEncoder()
    assert store.build(pg, enc, batch_size=1) == {"computed": 2, "total": 2}
    assert store.build(pg, enc, batch_size=1)["computed"] == 0  # rien n'a changé
    pg.execute("UPDATE catalog.media SET synopsis = 'Autre.' WHERE id = %s", (a,))
    assert store.build(pg, enc, batch_size=1)["computed"] == 1  # seul A est recalculé
    norm = pg.execute(
        "SELECT vector_norm(embedding) FROM catalog.media_embedding WHERE media_id = %s", (a,)
    ).fetchone()[0]
    assert norm == pytest.approx(1.0, abs=1e-5)


@pytestmark_db
def test_changing_the_model_recomputes_everything(pg):
    _media(pg, "A")
    store.build(pg, FakeEncoder(), batch_size=8)
    other = FakeEncoder()
    other.name = "autre-modele"
    assert store.build(pg, other, batch_size=8)["computed"] == 1


@pytestmark_db
def test_missing_count_for_the_dag_quality_check(pg):
    _media(pg, "A")
    assert store.missing_count(pg) == 1
    store.build(pg, FakeEncoder(), batch_size=8)
    assert store.missing_count(pg) == 0


# --- Scorer de contenu dans le protocole de la phase 4 -------------------------------------------
def test_content_scorer_ranks_similar_items_first_in_evaluate_users():
    # Trois animes : 1 et 2 très proches, 3 à l'opposé.
    emb = np.array([[1.0, 0.0], [0.99, 0.14], [-1.0, 0.0]], dtype=np.float32)
    item_ids = np.array([1, 2, 3])
    scorer = evaluate.content_scorer(item_ids, emb, neutral_score=5)
    # L'utilisateur a aimé 1 (visible) ; on a masqué 2 (aimé) et 3 (aimé aussi, mais loin).
    holdout = pd.DataFrame({"user_id": [7, 7, 7], "anime_id": [1, 2, 3], "score": [9, 9, 8],
                            "masked": [False, True, True]})  # fmt: skip
    res = evaluate_users(holdout, item_ids, scorer, [1], relevant_min_score=8)
    assert res["at_k"]["1"]["precision"] == 1.0  # 2 (le plus proche) est recommandé en premier


def test_popularity_prior_is_one_for_the_first_rank_and_zero_when_unranked():
    prior = evaluate.popularity_prior(np.array([1, 3, 10_000, np.nan]))
    assert prior[0] == pytest.approx(1.0)
    assert prior[0] > prior[1] > prior[2] > 0
    assert prior[3] == 0.0


def test_hybrid_scorer_lifts_popular_items_among_similar_ones():
    # 2 et 3 sont aussi proches du profil ; 3 est bien plus populaire.
    emb = np.array([[1.0, 0.0], [0.9, 0.436], [0.9, -0.436]], dtype=np.float32)
    prior = evaluate.popularity_prior(np.array([50.0, 900.0, 2.0]))
    pure = evaluate.content_scorer(np.array([1, 2, 3]), emb, 5)
    hybrid = evaluate.content_scorer(np.array([1, 2, 3]), emb, 5, prior=prior, beta=0.5)
    ids, scores = np.array([1]), np.array([9.0])
    assert pure(ids, scores)[1] == pytest.approx(pure(ids, scores)[2])
    assert hybrid(ids, scores)[2] > hybrid(ids, scores)[1]


def test_beta_is_the_knee_of_the_validation_curve():
    # Plus petit β à moins de 1 % du meilleur NDCG : presque le même score, plus de
    # personnalisation (mesuré le 2026-11-22 : la courbe est plate au-delà de 0,3).
    results = {0.0: 0.025, 0.2: 0.1785, 0.3: 0.1813, 0.5: 0.1818, 2.0: 0.1823}
    assert evaluate.knee_beta(results, tolerance=0.01) == 0.3
    assert evaluate.knee_beta(results, tolerance=0.0) == 2.0


def test_content_scorer_ignores_disliked_items_and_has_no_opinion_without_likes():
    emb = np.eye(3, dtype=np.float32)
    scorer = evaluate.content_scorer(np.array([1, 2, 3]), emb, neutral_score=5)
    assert scorer(np.array([1]), np.array([3.0])) is None  # note ≤ neutre : pas un goût
    scores = scorer(np.array([1, 2]), np.array([9.0, 2.0]))
    assert scores[0] > scores[1]  # 2 détesté ne tire pas le profil vers lui
