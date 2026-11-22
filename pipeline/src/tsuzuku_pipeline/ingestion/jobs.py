"""Tâches d'ingestion appelées par les DAG Airflow (et testables sans Airflow).

Chaque tâche lit et écrit des fichiers bruts datés : data/raw/<source>/<AAAA-MM-JJ>/.
- une tâche peut être relancée seule (Airflow « clear ») sans rappeler les précédentes ;
- relancer la même date réécrit les mêmes fichiers et fait les mêmes upserts : idempotent ;
- la donnée brute reste disponible pour rejouer un chargement ou déboguer.
Le rapport de contrôle de chaque exécution va dans reports/ingestion/.
"""

import dataclasses
import datetime as dt
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import yaml

from tsuzuku_pipeline.config import REPO_ROOT, require_section, resolve_path
from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.ingestion import anilist_client, catalog_loader, jikan_client
from tsuzuku_pipeline.ingestion.catalog_loader import (
    ANILIST_SOURCE,
    JIKAN_SOURCE,
    upsert_anilist_media,
    upsert_daily_stats,
    upsert_jikan_anime,
)
from tsuzuku_pipeline.ingestion.http import HttpError, PoliteClient
from tsuzuku_pipeline.ingestion.records import StatsRecord

logger = logging.getLogger("tsuzuku_pipeline.ingestion")


class IngestionError(Exception):
    """Exécution invalide : la tâche Airflow doit échouer (et être visible comme telle)."""


# --- Fichiers ----------------------------------------------------------------------------------


def raw_dir(settings: dict[str, Any], source: str, day: dt.date) -> Path:
    path = resolve_path(settings, "raw") / source / day.isoformat()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, doc: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomique : jamais de fichier à moitié écrit pour la tâche suivante


def _read(path: Path) -> Any:
    if not path.is_file():
        raise IngestionError(f"{path.name} absent : l'étape précédente n'a pas tourné pour ce jour")
    return json.loads(path.read_text(encoding="utf-8"))


def _report(settings: dict[str, Any], name: str, day: dt.date, doc: dict[str, Any]) -> Path:
    sub = require_section(settings, "ingestion")["reports_subdir"]
    path = resolve_path(settings, "reports") / sub / f"{name}_{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, doc)
    return path


@contextmanager
def _connection(conn=None):
    if conn is not None:
        yield conn
        return
    with loader.connect(loader.database_url()) as c:
        loader.apply_schemas(c)
        yield c


# Public pour la ligne de commande (make covers-report) : même connexion que les tâches.
connection = _connection


def _client(cfg: dict[str, Any], base_url: str, transport: httpx.BaseTransport | None,
            sleep=None) -> PoliteClient:  # fmt: skip
    kwargs = {"sleep": sleep} if sleep else {}
    return PoliteClient(base_url, timeout_s=cfg["timeout_s"], min_interval_s=cfg["min_interval_s"],
                        max_retries=cfg["max_retries"], transport=transport, **kwargs)  # fmt: skip


def watchlist_ids(path: Path | None = None) -> list[int]:
    """Animes suivis en plus de la saison (config/watchlist.yaml), identifiants vérifiés."""
    path = path or REPO_ROOT / "config" / "watchlist.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [int(e["mal_id"]) for e in doc.get("anime") or []]


# --- Jikan : statistiques quotidiennes ---------------------------------------------------------


def _check_today(day: dt.date, today: dt.date | None, step: str) -> None:
    """Jikan ne donne que l'état ACTUEL : collecter « pour hier » rangerait les chiffres
    d'aujourd'hui sous la date d'hier, en écrasant le vrai snapshot. On le refuse. Rejouer
    load ou quality_check pour une date passée reste possible (ils lisent les fichiers bruts)."""
    today = today or dt.datetime.now(dt.UTC).date()
    if day != today:
        raise IngestionError(
            f"{step} pour le {day} refusé (nous sommes le {today}) : Jikan ne fournit que "
            "l'état actuel ; rejoue load/quality_check à la place"
        )


def jikan_collect(
    settings: dict[str, Any],
    day: dt.date,
    transport=None,
    sleep=None,
    watchlist: list[int] | None = None,
    today: dt.date | None = None,
) -> int:
    """Saison en cours + watchlist → targets.json (fiches Jikan brutes)."""
    _check_today(day, today, "collect")
    cfg = require_section(settings, "ingestion")["jikan"]
    with _client(cfg, cfg["base_url"], transport, sleep) as client:
        # _in_season : appartenance à la saison, enregistrée avec les stats (filtre de /trending).
        items = [{**i, "_in_season": True}
                 for i in jikan_client.season_now(client, cfg["max_season_pages"])]  # fmt: skip
        seen = {int(i["mal_id"]) for i in items}
        for mal_id in watchlist if watchlist is not None else watchlist_ids():
            if mal_id in seen:
                continue
            try:
                item = jikan_client.anime(client, mal_id)
            except HttpError as exc:
                logger.warning("Watchlist : anime %d indisponible (%s)", mal_id, exc)
                continue
            if item and not jikan_client.is_adult(item):
                items.append({**item, "_in_season": False})
                seen.add(mal_id)
    if not items:
        raise IngestionError("Jikan : aucune œuvre à suivre (saison vide ?)")
    _write(raw_dir(settings, JIKAN_SOURCE, day) / "targets.json", items)
    logger.info("Jikan : %d animes à suivre", len(items))
    return len(items)


def jikan_fetch_stats(settings: dict[str, Any], day: dt.date, transport=None, sleep=None,
                      today: dt.date | None = None) -> dict[str, int]:  # fmt: skip
    """Statistiques de chaque anime → stats.json.

    Un échec isolé est noté ; l'anime garde une ligne avec score et membres (lus dans sa fiche)
    sans le détail par statut, pour rester dans le snapshot du jour. Dès que les échecs dépassent
    `max_failure_share`, on s'arrête : inutile d'enchaîner des heures de retries si Jikan tombe.
    """
    _check_today(day, today, "fetch_stats")
    cfg = require_section(settings, "ingestion")["jikan"]
    folder = raw_dir(settings, JIKAN_SOURCE, day)
    targets = _read(folder / "targets.json")
    max_failures = cfg["max_failure_share"] * len(targets)
    stats, failures = [], []
    with _client(cfg, cfg["base_url"], transport, sleep) as client:
        for item in targets:
            try:
                stats.append(dataclasses.asdict(jikan_client.statistics(client, item)))
            except (HttpError, KeyError, TypeError, ValueError) as exc:
                failures.append({"mal_id": item.get("mal_id"), "error": str(exc)})
                stats.append(dataclasses.asdict(jikan_client.summary_stats(item)))
                if len(failures) > max_failures:
                    break
    _write(folder / "stats.json", {"stats": stats, "failures": failures})
    logger.info("Jikan : %d lignes, %d échecs sur %d animes", len(stats), len(failures),
                len(targets))  # fmt: skip
    if len(failures) > max_failures:
        # Au-delà du seuil, ce n'est plus « un échec isolé » : Jikan ou notre code a un problème.
        raise IngestionError(
            f"Jikan : {len(failures)} échecs sur {len(targets)} animes, au-delà du seuil "
            f"de {cfg['max_failure_share']:.0%}"
        )
    return {"stats": len(stats), "failures": len(failures)}


def jikan_load(settings: dict[str, Any], day: dt.date, conn=None) -> dict[str, int]:
    folder = raw_dir(settings, JIKAN_SOURCE, day)
    targets = _read(folder / "targets.json")
    stats = [StatsRecord(**s) for s in _read(folder / "stats.json")["stats"]]
    with _connection(conn) as c:
        ids = upsert_jikan_anime(c, [jikan_client.media_record(i) for i in targets])
        n = upsert_daily_stats(c, day, stats, ids)
    return {"media": len(ids), "stats_rows": n}


def jikan_quality(settings: dict[str, Any], day: dt.date, conn=None) -> dict[str, Any]:
    folder = raw_dir(settings, JIKAN_SOURCE, day)
    fetched = _read(folder / "stats.json")
    targets = _read(folder / "targets.json")
    with _connection(conn) as c:
        rows, negatives = c.execute(
            "SELECT count(*), count(*) FILTER (WHERE least(watching, completed, on_hold, dropped,"
            " plan_to_watch) < 0) FROM catalog.media_daily_stats"
            " WHERE snapshot_date = %s AND source = %s",
            (day, JIKAN_SOURCE),
        ).fetchone()
    checks = {
        "rows_for_day": rows > 0,
        "all_fetched_stats_loaded": rows >= len(fetched["stats"]),
        "no_negative_counts": negatives == 0,
        # Défense en profondeur : aucune fiche adulte dans ce qui a été chargé.
        "no_adult_content": not any(jikan_client.is_adult(i) for i in targets),
    }
    report = {
        "dag": "jikan_daily_ingest", "snapshot_date": day.isoformat(),
        "targets": len(targets), "stats_fetched": len(fetched["stats"]),
        "failures": fetched["failures"], "rows_for_day": rows, "checks": checks,
        "ok": all(checks.values()),
    }  # fmt: skip
    _report(settings, "jikan", day, report)
    if not report["ok"]:
        raise IngestionError(f"Contrôle qualité Jikan en échec : {checks}")
    return report


# --- AniList : catalogue manga / manhwa / manhua -----------------------------------------------


def anilist_fetch(settings: dict[str, Any], day: dt.date, transport=None,
                  sleep=None) -> dict[str, int]:  # fmt: skip
    """Pages AniList par popularité décroissante → pages.json (titres bruts + rang)."""
    cfg = require_section(settings, "ingestion")["anilist"]
    items, last_page = [], 0
    with _client(cfg, cfg["url"], transport, sleep) as client:
        for page in range(1, cfg["max_pages"] + 1):
            data = anilist_client.fetch_page(client, page, cfg["per_page"])
            for i, item in enumerate(data.get("media") or []):
                items.append({"rank": (page - 1) * cfg["per_page"] + i + 1, "item": item})
            last_page = page
            if not (data.get("pageInfo") or {}).get("hasNextPage"):
                break
    _write(raw_dir(settings, ANILIST_SOURCE, day) / "pages.json",
           {"pages": last_page, "items": items})  # fmt: skip
    logger.info("AniList : %d titres sur %d pages", len(items), last_page)
    return {"pages": last_page, "items": len(items)}


def anilist_load(settings: dict[str, Any], day: dt.date, conn=None) -> dict[str, int]:
    cfg = require_section(settings, "ingestion")["anilist"]
    raw = _read(raw_dir(settings, ANILIST_SOURCE, day) / "pages.json")
    records = [anilist_client.media_record(e["item"], e["rank"], cfg["tag_min_rank"])
               for e in raw["items"]]  # fmt: skip
    kept = [r for r in records if r is not None]
    with _connection(conn) as c:
        counts = upsert_anilist_media(c, kept)
    counts["skipped"] = len(records) - len(kept)  # adultes, romans ou pays non couverts
    _write(raw_dir(settings, ANILIST_SOURCE, day) / "load.json", counts)
    return counts


def anilist_quality(settings: dict[str, Any], day: dt.date, conn=None) -> dict[str, Any]:
    cfg = require_section(settings, "ingestion")["anilist"]
    folder = raw_dir(settings, ANILIST_SOURCE, day)
    raw, load = _read(folder / "pages.json"), _read(folder / "load.json")
    # Attendu : toutes les pages demandées, sauf si AniList a annoncé la fin plus tôt.
    expected = cfg["per_page"] * raw["pages"]
    # Titres gardés (ni adultes, ni romans, ni pays non couverts) : ils doivent TOUS être en base.
    kept_ids = sorted({
        int(e["item"]["id"]) for e in raw["items"]
        if anilist_client.media_record(e["item"], e["rank"], cfg["tag_min_rank"]) is not None
    })  # fmt: skip
    with _connection(conn) as c:
        in_db = c.execute(
            "SELECT count(*) FROM catalog.media WHERE data_source = %s AND anilist_id = ANY(%s)",
            (ANILIST_SOURCE, kept_ids),
        ).fetchone()[0]
        by_kind = dict(c.execute(
            "SELECT kind, count(*) FROM catalog.media WHERE data_source = %s GROUP BY kind",
            (ANILIST_SOURCE,),
        ).fetchall())  # fmt: skip
        adult = c.execute(
            "SELECT count(*) FROM catalog.media m JOIN catalog.media_genre mg ON mg.media_id = m.id"
            " JOIN catalog.genre g ON g.id = mg.genre_id"
            " WHERE m.data_source = %s AND g.name = 'Hentai'", (ANILIST_SOURCE,),
        ).fetchone()[0]  # fmt: skip
    checks = {
        "enough_titles": len(raw["items"]) >= cfg["min_share_of_expected"] * expected,
        "all_kept_titles_in_db": in_db == len(kept_ids) == load["loaded"],
        "no_adult_content": adult == 0,
    }
    report = {
        "dag": "anilist_catalog_sync", "run_date": day.isoformat(), "pages": raw["pages"],
        "fetched": len(raw["items"]), "expected": expected, **{f"load_{k}": v for k, v in
        load.items()}, "catalog_by_kind": by_kind, "checks": checks, "ok": all(checks.values()),
    }  # fmt: skip
    _report(settings, "anilist", day, report)
    if not report["ok"]:
        raise IngestionError(f"Contrôle qualité AniList en échec : {checks}")
    return report


# --- AniList : couvertures des animes (phase 8) ------------------------------------------------


def anilist_covers(settings: dict[str, Any], day: dt.date, transport=None, sleep=None,
                   conn=None, include_small: bool = False) -> dict[str, Any]:  # fmt: skip
    """Jaquettes des animes, par lots d'idMal → catalog.media (cover_url, cover_color).

    Les animes du dataset 2020 n'ont pas d'image, et Jikan (qui en fournit) est en panne depuis
    la phase 6. AniList les connaît par leur idMal. Sont demandées les jaquettes absentes, et avec
    `include_small` les petites images AniList (230 px → 460 px quand elle existe). Relancer ne
    refait rien (idempotent). Les URL reçues sont gardées dans
    covers.json pour rejouer ou auditer.
    """
    cfg = require_section(settings, "ingestion")["anilist"]
    size = int(cfg["covers_batch_size"])
    with _connection(conn) as c:
        targets = catalog_loader.anime_cover_targets(c, include_small)
        found: dict[int, dict[str, str | None]] = {}
        with _client(cfg, cfg["url"], transport, sleep) as client:
            for start in range(0, len(targets), size):
                found.update(anilist_client.fetch_covers(client, targets[start : start + size]))
        _write(raw_dir(settings, ANILIST_SOURCE, day) / "covers.json",
               {str(k): v for k, v in found.items()})  # fmt: skip
        updated = catalog_loader.apply_anime_covers(c, found)
        remaining = catalog_loader.missing_anime_count(c)
    report = {"dag": "anilist_catalog_sync", "task": "covers", "run_date": day.isoformat(),
              "requested": len(targets), "found": len(found), "updated": updated,
              "still_missing": remaining}  # fmt: skip
    _report(settings, "covers", day, report)
    logger.info("Couvertures AniList : %s", report)
    return report
