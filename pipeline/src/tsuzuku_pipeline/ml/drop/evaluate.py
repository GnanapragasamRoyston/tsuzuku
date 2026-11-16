"""Évaluation du modèle de drop : métriques, calibration, importance des variables, figures.

Toutes les valeurs retournées sont des types Python simples : elles vont telles quelles dans
reports/drop_metrics.json, seule source autorisée pour les chiffres du README.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # rendu en fichier, sans écran (serveur, CI)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline  # noqa: E402

# Palette validée (skill dataviz, validate_palette.js, 3 créneaux, mode clair : PASS ; le vert
# d'eau est sous 3:1 de contraste → légende + style de trait distinct + tableau dans le rapport).
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"dummy": "#2a78d6", "logreg": "#eb6834", "hgb": "#1baf7a"}
LINESTYLE = {"dummy": ":", "logreg": "--", "hgb": "-"}
LABEL = {"dummy": "Baseline (taux moyen)", "logreg": "Régression logistique",
         "hgb": "Gradient boosting"}  # fmt: skip


def reliability(
    y: np.ndarray, p: np.ndarray, n_bins: int = 10
) -> tuple[list[dict[str, Any]], float]:
    """Courbe de calibration par déciles de probabilité prédite, et ECE.

    ECE (expected calibration error) : écart moyen, pondéré par l'effectif, entre la probabilité
    annoncée et la fréquence observée. 0 = quand le modèle dit 30 %, il y a bien 30 % de drops.
    Bins à effectif égal (quantiles) : avec 6 % de positifs, des bins de largeur fixe seraient
    presque vides au-delà de 0,3.
    """
    y, p = np.asarray(y), np.asarray(p)
    edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    if len(edges) < 2:
        # Probabilité constante (baseline, ou calibration dégénérée) : un seul bin. Sans ce cas,
        # la boucle ne voyait aucun bin et l'ECE sortait à 0.0 — faux (relevé par la revue).
        mean_pred, observed = float(p.mean()), float(y.mean())
        return [{"mean_pred": mean_pred, "observed": observed, "n": int(len(p))}], abs(
            mean_pred - observed
        )
    ids = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    bins, ece = [], 0.0
    for b in range(len(edges) - 1):
        mask = ids == b
        if not mask.any():
            continue
        mean_pred, observed, n = float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())
        bins.append({"mean_pred": mean_pred, "observed": observed, "n": n})
        ece += n * abs(mean_pred - observed)
    return bins, float(ece / len(p))


def classification_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, Any]:
    y, p = np.asarray(y), np.asarray(p)
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    _, ece = reliability(y, p)
    return {
        "n": int(len(y)),
        "prevalence": float(y.mean()),
        "threshold": float(threshold),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, np.clip(p, 1e-7, 1 - 1e-7), labels=[0, 1])),
        "ece": ece,
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def permutation_ranking(
    pipeline: Pipeline,
    x: pd.DataFrame,
    y: pd.Series,
    n_rows: int,
    n_repeats: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Importance par permutation, mesurée en perte de PR-AUC, sur un sous-échantillon du test.

    On permute les colonnes BRUTES (avant encodage) : l'importance se lit en termes de features
    produit (« taux de drop de l'utilisateur »), pas de colonnes one-hot.
    """
    if len(x) > n_rows:
        sample = x.sample(n=n_rows, random_state=seed)
        x, y = sample, y.loc[sample.index]
    result = permutation_importance(
        pipeline, x, y, scoring="average_precision", n_repeats=n_repeats, random_state=seed,
        n_jobs=1,
    )  # fmt: skip
    ranking = [
        {"feature": f, "importance": float(m), "std": float(s)}
        for f, m, s in zip(x.columns, result.importances_mean, result.importances_std, strict=True)
    ]
    return sorted(ranking, key=lambda r: -r["importance"])


# --- Figures -----------------------------------------------------------------------------------


def _axes(title: str, xlabel: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=TEXT, loc="left", fontsize=12)
    ax.set_xlabel(xlabel, color=TEXT_2)
    ax.set_ylabel(ylabel, color=TEXT_2)
    ax.tick_params(colors=TEXT_2)
    ax.grid(color=GRID, linewidth=0.8)  # grille discrète : le regard va aux courbes
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def plot_curves(y: np.ndarray, probas: dict[str, np.ndarray], out_dir: Path) -> None:
    """Courbes ROC et précision-rappel des modèles comparés, sur le test."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = _axes("Courbe ROC (test)", "Taux de faux positifs", "Taux de vrais positifs")
    for kind, p in probas.items():
        fpr, tpr, _ = roc_curve(y, p)
        auc = roc_auc_score(y, p)
        ax.plot(fpr, tpr, color=SERIES[kind], linestyle=LINESTYLE[kind], linewidth=2,
                label=f"{LABEL[kind]} — AUC {auc:.3f}")  # fmt: skip
    ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, out_dir / "roc.png")

    fig, ax = _axes("Précision-rappel, classe drop (test)", "Rappel", "Précision")
    for kind, p in probas.items():
        ap = average_precision_score(y, p)
        if np.ptp(p) == 0:
            # Score constant (baseline) : sa précision vaut le taux de positifs à tout rappel.
            # precision_recall_curve ne renvoie que (0, 1) et (1, taux) : relier ces deux points
            # dessinerait une diagonale trompeuse, qui semble battre les vrais modèles.
            ax.axhline(y.mean(), color=SERIES[kind], linestyle=LINESTYLE[kind], linewidth=2,
                       label=f"{LABEL[kind]} — PR-AUC {ap:.3f}")  # fmt: skip
            continue
        precision, recall, _ = precision_recall_curve(y, p)
        ax.plot(recall, precision, color=SERIES[kind], linestyle=LINESTYLE[kind], linewidth=2,
                label=f"{LABEL[kind]} — PR-AUC {ap:.3f}")  # fmt: skip
    ax.set_ylim(0, 1)
    ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, out_dir / "pr.png")


def plot_calibration(bins: Sequence[dict[str, Any]], kind: str, path: Path) -> None:
    fig, ax = _axes(
        f"Calibration — {LABEL[kind]} (test)",
        "Probabilité de drop prédite",
        "Part de drops observée",
    )
    top = max(max(b["mean_pred"] for b in bins), max(b["observed"] for b in bins)) * 1.05
    ax.plot([0, top], [0, top], color=TEXT_2, linewidth=1, linestyle=":",
            label="Calibration parfaite")  # fmt: skip
    ax.plot([b["mean_pred"] for b in bins], [b["observed"] for b in bins], color=SERIES[kind],
            linewidth=2, marker="o", markersize=5, label=LABEL[kind])  # fmt: skip
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, path)


def plot_importance(ranking: Sequence[dict[str, Any]], path: Path, top: int = 15) -> None:
    rows = list(ranking[:top])[::-1]  # plus importante en haut
    fig, ax = _axes("Importance par permutation (perte de PR-AUC, test)", "Baisse de PR-AUC", "")
    ax.barh(
        [r["feature"] for r in rows],
        [r["importance"] for r in rows],
        xerr=[r["std"] for r in rows],
        color=SERIES["hgb"],
        height=0.6,
        error_kw={"ecolor": TEXT_2, "elinewidth": 1},
    )
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", labelsize=8)
    _save(fig, path)
