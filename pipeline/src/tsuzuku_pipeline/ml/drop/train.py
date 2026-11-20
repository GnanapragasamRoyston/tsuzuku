"""Entraînement du modèle de drop : split par utilisateur, pipelines, grille, seuil.

Protocole (ADR 004) :
- train (70 %) : apprentissage ;
- validation (15 %) : choix des hyperparamètres, du modèle final et du seuil de décision ;
- test (15 %) : évalué une seule fois, à la fin. Rien n'y est réglé.
Le split se fait par UTILISATEUR : ses features résument ses autres lignes, donc mettre ses lignes
dans train et test laisserait le modèle « reconnaître » l'utilisateur (fuite par le groupe).
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from tsuzuku_ml.drop_features import (  # noqa: F401  (prepare_x ré-exporté pour le pipeline)
    CATEGORICAL_COLUMNS,
    feature_columns,
    prepare_x,
)

TARGET = "is_dropped"
GROUP = "user_id"
MODEL_KINDS = ("dummy", "logreg", "hgb")


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


@dataclass
class Candidate:
    kind: str
    params: dict[str, Any]
    pipeline: Pipeline
    val_pr_auc: float


def split_by_user(df: pd.DataFrame, val_fraction: float, test_fraction: float, seed: int) -> Split:
    """Deux GroupShuffleSplit successifs : (train+val | test), puis (train | val)."""
    outer = GroupShuffleSplit(n_splits=1, test_size=test_fraction, random_state=seed)
    rest_idx, test_idx = next(outer.split(df, groups=df[GROUP]))
    rest = df.iloc[rest_idx]
    inner = GroupShuffleSplit(
        n_splits=1, test_size=val_fraction / (1 - test_fraction), random_state=seed
    )
    train_idx, val_idx = next(inner.split(rest, groups=rest[GROUP]))
    return Split(rest.iloc[train_idx], rest.iloc[val_idx], df.iloc[test_idx])


def build_pipeline(
    kind: str, params: dict[str, Any], genres: Sequence[str], top_studios: int, seed: int
) -> Pipeline:
    numeric = [c for c in feature_columns(genres) if c not in CATEGORICAL_COLUMNS]
    # Catégories : manquant → modalité dédiée ; studios rares ou inconnus → « infrequent ».
    # Le top-N est appris sur le train seul (dans le pipeline) : pas de fuite depuis le test.
    categorical = make_pipeline(
        SimpleImputer(strategy="constant", fill_value="__missing__"),
        OneHotEncoder(
            handle_unknown="infrequent_if_exist",
            max_categories=top_studios + 1,
            sparse_output=False,
        ),
    )
    if kind == "logreg":
        # Régression logistique : pas de NaN, et des échelles comparables (coefficients pénalisés).
        numeric_tf = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True), StandardScaler()
        )
        model = LogisticRegression(random_state=seed, **params)
    elif kind == "hgb":
        # Gradient boosting : gère les NaN nativement et ignore l'échelle → aucune transformation.
        numeric_tf = "passthrough"
        model = HistGradientBoostingClassifier(random_state=seed, **params)
    elif kind == "dummy":
        numeric_tf = "drop"
        # « prior » : prédit toujours le taux de drop du train ; plancher à battre.
        model = DummyClassifier(strategy="prior")
    else:
        raise ValueError(f"Modèle inconnu : {kind}")

    pre = ColumnTransformer(
        [("cat", categorical, list(CATEGORICAL_COLUMNS)), ("num", numeric_tf, numeric)]
    )
    return Pipeline([("pre", pre), ("model", model)])


def expand_grid(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """{'a': [1, 2], 'b': 3} → [{'a': 1, 'b': 3}, {'a': 2, 'b': 3}] (listes = axes de la grille)."""
    keys = list(cfg)
    axes = [v if isinstance(v, list) else [v] for v in cfg.values()]
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*axes)]


def select_models(
    split: Split, cfg: dict[str, Any], genres: Sequence[str], seed: int
) -> dict[str, Candidate]:
    """Pour chaque famille de modèle, la meilleure combinaison selon la PR-AUC de validation.

    PR-AUC plutôt que ROC-AUC : avec 6 % de drops, la ROC-AUC reste flatteuse même quand le modèle
    noie les vrais drops dans les faux positifs ; la PR-AUC regarde précisément la classe rare.
    """
    x_train, y_train = prepare_x(split.train, genres), split.train[TARGET]
    x_val, y_val = prepare_x(split.val, genres), split.val[TARGET]
    grids = {"dummy": [{}], "logreg": expand_grid(cfg["logreg"]), "hgb": expand_grid(cfg["hgb"])}

    best: dict[str, Candidate] = {}
    for kind in MODEL_KINDS:
        for params in grids[kind]:
            pipe = build_pipeline(kind, params, genres, cfg["top_studios"], seed)
            pipe.fit(x_train, y_train)
            score = average_precision_score(y_val, pipe.predict_proba(x_val)[:, 1])
            if kind not in best or score > best[kind].val_pr_auc:
                best[kind] = Candidate(kind, params, pipe, float(score))
    return best


def calibrate_isotonic(
    pipeline: Pipeline, val: pd.DataFrame, genres: Sequence[str], seed: int
) -> tuple[Any, pd.DataFrame]:
    """Calibration isotonique sur une moitié de la validation ; l'autre moitié sert au seuil.

    Deux moitiés disjointes (par utilisateur) : régler la calibration et le seuil sur les mêmes
    lignes reviendrait à évaluer le seuil sur des données déjà « apprises ». Le modèle de base est
    gelé (FrozenEstimator) : seule la fonction de correction des probabilités est apprise.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    halves = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=seed)
    cal_idx, thr_idx = next(halves.split(val, groups=val[GROUP]))
    cal, thr = val.iloc[cal_idx], val.iloc[thr_idx]
    model = CalibratedClassifierCV(FrozenEstimator(pipeline), method="isotonic")
    model.fit(prepare_x(cal, genres), cal[TARGET])
    return model, thr


def choose_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """Seuil qui maximise le F1 de la classe drop (sur la validation, jamais sur le test)."""
    precision, recall, thresholds = precision_recall_curve(y, p)
    # precision/recall ont un point de plus que thresholds (le point final recall = 0).
    p_, r_ = precision[:-1], recall[:-1]
    f1 = np.divide(2 * p_ * r_, p_ + r_, out=np.zeros_like(p_), where=(p_ + r_) > 0)
    return float(thresholds[int(np.argmax(f1))])
