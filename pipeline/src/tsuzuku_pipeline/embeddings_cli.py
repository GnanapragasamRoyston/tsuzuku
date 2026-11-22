"""Embeddings des œuvres (phase 10, ADR 013).

    make embeddings-eval   # compare les modèles candidats aux recos de la phase 4 (mêmes
                           # utilisateurs de test) → reports/content_reco_metrics.json
    make embeddings        # calcule les embeddings manquants ou périmés avec le modèle retenu
    make embeddings ARGS=examples   # exemples cross-média → reports/content_reco_examples.json

Demande l'extra « embeddings » (PyTorch, sentence-transformers) : `uv run --extra embeddings`.
"""

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tsuzuku_ml.artifacts import load_reco_model

from tsuzuku_pipeline.config import load_settings, require_section, resolve_path
from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.embeddings import store
from tsuzuku_pipeline.embeddings.encoder import SentenceEncoder
from tsuzuku_pipeline.embeddings.evaluate import content_scorer, knee_beta, popularity_prior
from tsuzuku_pipeline.ml.reco.evaluate import evaluate_users, onboarding_profile

logger = logging.getLogger("tsuzuku_pipeline.embeddings")


def _write(path: Path, doc: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ndcg(result: dict[str, Any], k: int) -> float | None:
    return result["at_k"][str(k)]["ndcg"]


def evaluate_candidates(settings: dict[str, Any]) -> Path:
    """Même protocole et mêmes utilisateurs de test que l'ALS (phase 4) : seul le scorer change."""
    emb_cfg, reco = require_section(settings, "embeddings"), require_section(settings, "reco")
    rel, ks, k_sel = reco["relevant_min_score"], reco["k_values"], reco["selection_k"]
    model, card = load_reco_model(resolve_path(settings, "models"))
    item_ids = model.item_ids
    # Repli quand un utilisateur n'a aucun goût exploitable : la popularité du modèle servi.
    fallback = np.full(len(item_ids), -1e9)
    positions = pd.Index(item_ids).get_indexer(card["popularity_fallback"])
    fallback[positions[positions >= 0]] = -np.arange((positions >= 0).sum())

    holdout = pd.read_parquet(resolve_path(settings, "features") / "reco" / "holdout")
    test = holdout[holdout["split"] == "test"]
    with loader.connect(loader.database_url()) as conn:
        docs = store.documents(conn, emb_cfg["tags_max"], kind="anime")
    text_by_mal = {d["mal_id"]: d["text"] for d in docs if d["mal_id"] is not None}
    missing = [int(i) for i in item_ids if int(i) not in text_by_mal]
    texts = [text_by_mal.get(int(i), "") for i in item_ids]

    results: dict[str, Any] = {
        "popularity_check": evaluate_users(test, item_ids, lambda i, s: fallback, ks, rel)
    }
    for cand in emb_cfg["candidates"]:
        started = time.monotonic()
        encoder = SentenceEncoder(cand["model"], cand.get("prefix", ""), emb_cfg["batch_size"])
        embeddings = encoder.encode(texts)
        encode_seconds = round(time.monotonic() - started, 1)
        scorer = content_scorer(item_ids, embeddings, reco["implicit_neutral_score"])
        onboarding = {}
        for n in reco["onboarding_n_liked"]:
            profile, _ = onboarding_profile(test, n, rel, reco["onboarding_default_score"],
                                            settings["project"]["seed"])  # fmt: skip
            onboarding[str(n)] = evaluate_users(profile, item_ids, scorer, ks, rel,
                                                fallback=fallback)  # fmt: skip
        results[encoder.name] = {
            "encode_seconds": encode_seconds,
            "test": evaluate_users(test, item_ids, scorer, ks, rel, fallback=fallback),
            "onboarding": onboarding,
        }
        logger.info("%s : NDCG@%d test %.4f", encoder.name, k_sel,
                    _ndcg(results[encoder.name]["test"], k_sel))  # fmt: skip

    # Chiffres de la phase 4 recopiés depuis leur rapport (jamais retapés à la main).
    phase4 = json.loads((resolve_path(settings, "reports") / "reco_metrics.json").read_text())
    reference = {
        "test": {m: _ndcg(r, k_sel) for m, r in phase4["test"].items()},
        "onboarding": {
            n: {m: _ndcg(r, k_sel) for m, r in o["models"].items()}
            for n, o in phase4["onboarding_test"].items()
        },  # fmt: skip
    }
    doc = {
        "generated_at": _now(),
        "protocol": "phase 4 (reco_metrics.json) : mêmes utilisateurs de test, mêmes cibles, "
        "mêmes animes candidats ; profil = moyenne des embeddings des animes aimés pondérée par "
        "(note − note neutre)",
        "selection_k": k_sel,
        "items": len(item_ids),
        "items_without_text": len(missing),
        "reference_ndcg_phase4": reference,
        "results": results,
    }
    # Mise à jour de SES clés seulement : la partie « hybrid » (eval-hybrid), dont dépend le β
    # servi, n'est pas effacée (revue de la phase 10).
    path = resolve_path(settings, "reports") / "content_reco_metrics.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    return _write(path, {**previous, **doc})


def evaluate_hybrid(settings: dict[str, Any]) -> Path:
    """Contenu + β × popularité, avec le modèle retenu : β réglé sur la VALIDATION (échantillon
    d'utilisateurs, comme la grille ALS), puis test mesuré une seule fois (ADR 013)."""
    emb_cfg, reco = require_section(settings, "embeddings"), require_section(settings, "reco")
    rel, ks, k_sel, seed = (reco["relevant_min_score"], reco["k_values"], reco["selection_k"],
                            settings["project"]["seed"])  # fmt: skip
    model, card = load_reco_model(resolve_path(settings, "models"))
    item_ids = model.item_ids
    fallback = np.full(len(item_ids), -1e9)
    positions = pd.Index(item_ids).get_indexer(card["popularity_fallback"])
    fallback[positions[positions >= 0]] = -np.arange((positions >= 0).sum())

    holdout = pd.read_parquet(resolve_path(settings, "features") / "reco" / "holdout")
    val, test = holdout[holdout["split"] == "val"], holdout[holdout["split"] == "test"]
    users = np.sort(val["user_id"].unique())
    chosen_users = np.random.default_rng(seed).choice(
        users, size=min(reco["grid_eval_users"], len(users)), replace=False
    )
    val_sample = val[val["user_id"].isin(chosen_users)]

    with loader.connect(loader.database_url()) as conn:
        docs = store.documents(conn, emb_cfg["tags_max"], kind="anime")
        ranks = dict(conn.execute(
            "SELECT mal_id, popularity FROM catalog.media"
            " WHERE kind = 'anime' AND mal_id IS NOT NULL"
        ).fetchall())  # fmt: skip
    text_by_mal = {d["mal_id"]: d["text"] for d in docs if d["mal_id"] is not None}
    texts = [text_by_mal.get(int(i), "") for i in item_ids]
    # Même a priori que le service : rang de popularité du catalogue (MAL pour les animes).
    prior = popularity_prior(np.array([ranks.get(int(i)) or np.nan for i in item_ids], float))

    encoder = SentenceEncoder(emb_cfg["model"], emb_cfg.get("prefix", ""), emb_cfg["batch_size"])
    embeddings = encoder.encode(texts)
    neutral = reco["implicit_neutral_score"]

    def scorer(beta: float):
        return content_scorer(item_ids, embeddings, neutral, prior=prior, beta=beta)

    val_ndcg = {
        float(b): _ndcg(
            evaluate_users(val_sample, item_ids, scorer(b), [k_sel], rel, fallback=fallback), k_sel
        )  # fmt: skip
        for b in emb_cfg["beta_grid"]
    }
    beta = knee_beta(val_ndcg, emb_cfg["beta_tolerance"])
    logger.info("β retenu sur la validation : %s (NDCG@%d %s)", beta, k_sel, val_ndcg)
    onboarding = {}
    for n in reco["onboarding_n_liked"]:
        profile, _ = onboarding_profile(test, n, rel, reco["onboarding_default_score"], seed)
        onboarding[str(n)] = evaluate_users(profile, item_ids, scorer(beta), ks, rel,
                                            fallback=fallback)  # fmt: skip

    path = resolve_path(settings, "reports") / "content_reco_metrics.json"
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc["hybrid"] = {
        "generated_at": _now(),
        "model": encoder.name,
        "prior": "1 / log2(1 + rang de popularité du catalogue)",
        "val_users": int(len(chosen_users)),
        "val_ndcg_by_beta": {str(b): v for b, v in val_ndcg.items()},
        "beta_rule": f"plus petit β à moins de {emb_cfg['beta_tolerance']:.0%} du meilleur NDCG",
        "beta": beta,
        "test": evaluate_users(test, item_ids, scorer(beta), ks, rel, fallback=fallback),
        "onboarding": onboarding,
    }
    return _write(path, doc)


def build(settings: dict[str, Any]) -> Path:
    cfg = require_section(settings, "embeddings")
    encoder = SentenceEncoder(cfg["model"], cfg.get("prefix", ""), cfg["batch_size"])
    started = time.monotonic()
    with loader.connect(loader.database_url()) as conn:
        loader.apply_schemas(conn)
        counts = store.build(conn, encoder, batch_size=256, tags_max=cfg["tags_max"])
        missing = store.missing_count(conn)
    doc = {"generated_at": _now(), "model": encoder.name, **counts, "missing_after": missing,
           "seconds": round(time.monotonic() - started, 1)}  # fmt: skip
    return _write(resolve_path(settings, "reports") / "embeddings_run.json", doc)


# Titres de départ des exemples, cherchés par titre exact en base (aucun identifiant deviné).
EXAMPLE_TITLES = ("Attack on Titan", "Death Note", "Fullmetal Alchemist: Brotherhood",
                  "Solo Leveling", "Your Name.", "Monster")  # fmt: skip


def examples(settings: dict[str, Any], k: int = 5) -> Path:
    out = []
    with loader.connect(loader.database_url()) as conn:
        for title in EXAMPLE_TITLES:
            seed = conn.execute(
                "SELECT m.id, m.kind, m.title FROM catalog.media m JOIN catalog.media_embedding e"
                " ON e.media_id = m.id WHERE m.title = %s ORDER BY m.popularity NULLS LAST LIMIT 1",
                (title,),
            ).fetchone()
            if seed is None:
                continue
            neighbours = {}
            for kinds in (("manga",), ("manhwa", "manhua"), ("anime",)):
                rows = conn.execute(
                    "SELECT m.title, m.kind, round((1 - (e.embedding <=> s.embedding))::numeric, 3)"
                    " FROM catalog.media_embedding e JOIN catalog.media m ON m.id = e.media_id,"
                    " catalog.media_embedding s WHERE s.media_id = %s AND e.media_id <> %s"
                    " AND m.kind = ANY(%s) ORDER BY e.embedding <=> s.embedding LIMIT %s",
                    (seed[0], seed[0], list(kinds), k),
                ).fetchall()
                neighbours["/".join(kinds)] = [
                    {"title": t, "kind": kd, "cosine": float(c)} for t, kd, c in rows
                ]
            out.append({"seed": {"title": seed[2], "kind": seed[1]}, "neighbours": neighbours})
    doc = {"generated_at": _now(), "model": require_section(settings, "embeddings")["model"],
           "examples": out}  # fmt: skip
    return _write(resolve_path(settings, "reports") / "content_reco_examples.json", doc)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tsuzuku-embeddings")
    parser.add_argument("task", nargs="?", default="build",
                        choices=["build", "eval", "eval-hybrid", "examples"])  # fmt: skip
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    task = {"build": build, "eval": evaluate_candidates, "eval-hybrid": evaluate_hybrid,
            "examples": examples}[args.task]  # fmt: skip
    print(task(settings))


if __name__ == "__main__":
    main()
