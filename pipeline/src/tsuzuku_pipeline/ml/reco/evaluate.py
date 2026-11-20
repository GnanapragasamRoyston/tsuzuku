"""Évaluation des recommandations : RMSE et métriques de classement @K, par utilisateur masqué.

Protocole : chaque utilisateur évalué a une partie VISIBLE de ses notes (ce qu'il nous aurait
donné) et une partie MASQUÉE (ce qu'on cherche à retrouver). Le modèle reçoit le visible, classe
tout le catalogue sauf le visible, et on regarde si les animes masqués qu'il a aimés
(note ≥ relevant_min_score) remontent dans le top-K.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tsuzuku_ml.fold_in import top_k_positions

from tsuzuku_pipeline.ml.drop.evaluate import SURFACE, TEXT, TEXT_2, _axes, _save

# Fonction (anime_ids visibles, notes visibles) → score de chaque anime du catalogue, ou None si
# le modèle ne sait rien dire de cet utilisateur (on utilise alors `fallback`).
Scorer = Callable[[np.ndarray, np.ndarray], np.ndarray | None]
# Fonction (ids visibles, notes visibles, ids cibles) → notes prédites pour les cibles.
Predictor = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray]


def ranking_metrics(
    recommended: Sequence[int], relevant: set[int], k: int
) -> tuple[float, float, float]:
    """precision@k, recall@k et NDCG@k (pertinence binaire) pour UN utilisateur.

    - precision@k : part des k recommandations qui sont pertinentes (divisée par k même si la
      liste est plus courte : une liste courte n'est pas récompensée) ;
    - recall@k : part des animes pertinents retrouvés dans le top-k ;
    - NDCG@k : comme le rappel, mais un pertinent en tête compte plus qu'en 10e position
      (gain 1/log2(rang+1)), normalisé par le meilleur classement possible.
    """
    if not relevant:
        raise ValueError("aucun anime pertinent : métriques de classement non définies")
    top = list(recommended[:k])
    hits = [1.0 if item in relevant else 0.0 for item in top]
    dcg = sum(h / math.log2(rank + 2) for rank, h in enumerate(hits))
    idcg = sum(1.0 / math.log2(rank + 2) for rank in range(min(k, len(relevant))))
    return sum(hits) / k, sum(hits) / len(relevant), dcg / idcg


def rmse(y: np.ndarray, pred: np.ndarray) -> float | None:
    if len(y) == 0:
        return None
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(pred, float)) ** 2)))


def shrunk_item_means(stats: pd.DataFrame, global_mean: float, shrinkage: float) -> pd.Series:
    """Note moyenne de chaque anime, tirée vers la moyenne globale (baseline de la RMSE).

    `stats` : colonnes anime_id, sum, count (agrégées par Spark sur le train).
    (somme + m·moyenne_globale) / (n + m) : un anime noté 2 fois ne peut pas afficher 10/10.
    """
    s = stats.set_index("anime_id")
    return (s["sum"] + shrinkage * global_mean) / (s["count"] + shrinkage)


def onboarding_profile(
    holdout: pd.DataFrame,
    n_liked: int,
    relevant_min_score: float,
    default_score: float,
    seed: int,
) -> tuple[pd.DataFrame, int]:
    """Simule un nouvel utilisateur Tsuzuku : il ne donne que `n_liked` animes AIMÉS, sans note.

    Pour chaque utilisateur : parmi ses notes visibles ≥ relevant_min_score, on en tire n_liked
    (tirage stable par hachage), transmises au modèle avec la note par défaut d'onboarding. Les
    autres visibles ne sont pas transmises (colonne `signal`). Les cibles (masquées) ne changent
    pas : les résultats sont comparables d'un n à l'autre et avec le protocole complet.
    Renvoie (holdout réduit aux utilisateurs éligibles, nb d'utilisateurs écartés faute d'assez
    d'animes aimés visibles).
    """
    if n_liked < 1:
        raise ValueError("n_liked doit valoir au moins 1")
    df = holdout.reset_index(drop=True)
    liked = ~df["masked"] & (df["score"] >= relevant_min_score)
    key = pd.util.hash_pandas_object(
        df[["user_id", "anime_id"]].assign(seed=seed), index=False
    ).to_numpy()
    order = df.assign(_key=np.where(liked, key, np.iinfo(np.uint64).max), _liked=liked).sort_values(
        ["user_id", "_key"], kind="stable"
    )
    rank = order.groupby("user_id").cumcount()
    chosen = order["_liked"] & (rank < n_liked)
    signal = pd.Series(False, index=df.index)
    signal.loc[order.index[chosen.to_numpy()]] = True
    out = df.assign(signal=signal, score=np.where(signal, float(default_score), df["score"]))
    n_given = out.groupby("user_id")["signal"].sum()
    eligible = n_given[n_given >= n_liked].index
    return out[out["user_id"].isin(eligible)], int((n_given < n_liked).sum())


def evaluate_users(
    holdout: pd.DataFrame,
    item_ids: np.ndarray,
    scorer: Scorer,
    ks: Iterable[int],
    relevant_min_score: float,
    fallback: np.ndarray | None = None,
    predict: Predictor | None = None,
) -> dict[str, Any]:
    """Évalue un modèle sur des utilisateurs masqués (colonnes user_id, anime_id, score, masked).

    Colonne optionnelle `signal` (bool) : parmi les notes visibles, celles transmises au modèle.
    Les visibles hors signal restent exclues des candidats (l'utilisateur les a vues) mais le
    modèle n'en sait rien : c'est le régime « onboarding » (voir onboarding_profile).
    Les animes masqués hors catalogue (sans facteur) ne peuvent pas être recommandés : ils sont
    retirés et comptés, plutôt que de pénaliser le modèle pour un anime qu'il ne connaît pas.
    """
    ks = sorted(set(ks))
    kmax = ks[-1]
    # Tableaux NumPy triés par utilisateur, découpés par frontières : un groupby pandas par
    # utilisateur coûtait plusieurs ms chacun (× dizaines de milliers d'utilisateurs × la grille).
    df = holdout.sort_values("user_id", kind="stable")
    users = df["user_id"].to_numpy()
    ids = df["anime_id"].to_numpy()
    scores_all = df["score"].to_numpy(dtype=float)
    masked_all = df["masked"].to_numpy(dtype=bool)
    signal_all = (
        df["signal"].to_numpy(dtype=bool) if "signal" in df else np.ones(len(df), dtype=bool)
    )
    pos_all = pd.Index(item_ids).get_indexer(ids)
    outside = int((masked_all & (pos_all < 0)).sum())
    if len(df):
        bounds = np.flatnonzero(np.diff(users)) + 1
        starts, ends = np.r_[0, bounds], np.r_[bounds, len(users)]
    else:
        starts = ends = np.array([], dtype=int)  # aucun utilisateur (et pas un utilisateur vide)

    sums = {k: np.zeros(3) for k in ks}
    seen_items = {k: set() for k in ks}
    ranked = without_relevant = used_fallback = 0
    errors: list[np.ndarray] = []

    for start, end in zip(starts, ends, strict=True):
        m, pos = masked_all[start:end], pos_all[start:end]
        given = ~m & signal_all[start:end]
        v_ids, v_scores = ids[start:end][given], scores_all[start:end][given]
        v_pos = pos[~m]  # toutes les visibles sont exclues, même celles non transmises
        keep = m & (pos >= 0)
        t_ids, t_scores = ids[start:end][keep], scores_all[start:end][keep]

        if predict is not None and len(t_ids):
            errors.append(t_scores - predict(v_ids, v_scores, t_ids))

        relevant = set(t_ids[t_scores >= relevant_min_score].tolist())
        if not relevant:
            without_relevant += 1
            continue
        scores = scorer(v_ids, v_scores)
        if scores is None:
            used_fallback += 1
            if fallback is None:
                raise ValueError("le modèle n'a pas de score et aucun fallback n'est fourni")
            scores = fallback
        # Même règle de classement que le service (fold_in.top_k_positions) : mêmes ex æquo.
        recommended = item_ids[top_k_positions(scores, v_pos, kmax)].tolist()
        ranked += 1
        for k in ks:
            sums[k] += ranking_metrics(recommended, relevant, k)
            seen_items[k].update(recommended[:k])

    err = np.concatenate(errors) if errors else np.array([])
    return {
        "users_ranked": ranked,
        "users_without_relevant": without_relevant,
        "users_fallback": used_fallback,
        "masked_outside_catalog": outside,
        "rmse": rmse(err, np.zeros(len(err))),
        "rmse_ratings": int(len(err)),
        "at_k": {
            str(k): {
                "precision": float(sums[k][0] / ranked) if ranked else None,
                "recall": float(sums[k][1] / ranked) if ranked else None,
                "ndcg": float(sums[k][2] / ranked) if ranked else None,
                # Couverture : part du catalogue recommandée au moins une fois. Une baseline de
                # popularité recommande presque toujours les mêmes titres → couverture faible.
                "coverage": len(seen_items[k]) / len(item_ids),
            }
            for k in ks
        },
    }


# --- Figures -----------------------------------------------------------------------------------

SERIES = {"popularity": "#2a78d6", "als_explicit": "#eb6834", "als_implicit": "#1baf7a"}
LINESTYLE = {"popularity": ":", "als_explicit": "--", "als_implicit": "-"}
LABEL = {
    "popularity": "Baseline popularité",
    "als_explicit": "ALS explicite",
    "als_implicit": "ALS implicite",
}


def plot_at_k(results: dict[str, dict[str, Any]], metric: str, path: Path) -> None:
    """Une métrique de classement en fonction de K, pour chaque modèle (test)."""
    names = {"ndcg": "NDCG", "precision": "Précision", "recall": "Rappel"}
    fig, ax = _axes(f"{names[metric]}@K (test)", "K", names[metric])
    for kind, res in results.items():
        ks = sorted(int(k) for k in res["at_k"])
        ax.plot(ks, [res["at_k"][str(k)][metric] for k in ks], color=SERIES[kind],
                linestyle=LINESTYLE[kind], linewidth=2, marker="o", markersize=5,
                label=LABEL[kind])  # fmt: skip
    ax.set_xticks(ks)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, labelcolor=TEXT)
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path)


def plot_onboarding(results: dict[str, dict[str, Any]], k: int, path: Path) -> None:
    """NDCG@k (test) selon le nombre d'animes aimés donnés à l'onboarding."""
    fig, ax = _axes(f"Onboarding : NDCG@{k} selon le nb d'animes aimés (test)",
                    "Animes aimés donnés au modèle", f"NDCG@{k}")  # fmt: skip
    ns = sorted(int(n) for n in results)
    for kind in SERIES:
        if kind not in results[str(ns[0])]["models"]:
            continue
        values = [results[str(n)]["models"][kind]["at_k"][str(k)]["ndcg"] for n in ns]
        ax.plot(ns, values, color=SERIES[kind], linestyle=LINESTYLE[kind], linewidth=2,
                marker="o", markersize=5, label=LABEL[kind])  # fmt: skip
    ax.set_xticks(ns)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, labelcolor=TEXT)
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path)


def plot_grid(grid: Sequence[dict[str, Any]], k: int, path: Path) -> None:
    """NDCG@k de validation de chaque point de la grille, par variante et par rang."""
    fig, ax = _axes(f"Grille ALS : NDCG@{k} de validation", "regParam", f"NDCG@{k}")
    markers = {16: "o", 32: "s", 64: "^", 128: "D"}
    for kind in ("als_explicit", "als_implicit"):
        rows = [g for g in grid if g["kind"] == kind]
        for rank in sorted({g["rank"] for g in rows}):
            pts = sorted((g["reg_param"], g["val_ndcg"]) for g in rows if g["rank"] == rank)
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=SERIES[kind],
                    linestyle=LINESTYLE[kind], marker=markers.get(rank, "o"), markersize=5,
                    linewidth=1.5, label=f"{LABEL[kind]}, rank {rank}")  # fmt: skip
    ax.set_xscale("log")
    # Graduations = les valeurs de la grille, écrites telles quelles (pas « 6×10⁻² »).
    regs = sorted({g["reg_param"] for g in grid})
    ax.set_xticks(regs, [f"{r:g}" for r in regs])
    ax.minorticks_off()
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=7, ncol=2)
    ax.tick_params(colors=TEXT_2)
    fig.patch.set_facecolor(SURFACE)
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path)
