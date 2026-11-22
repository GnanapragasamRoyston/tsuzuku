"""Couverture des jaquettes du catalogue → reports/covers_coverage.json (lot qualité, ADR 012).

Par type d'œuvre : part avec jaquette, origine des images (anilist, jikan, suggestion, none) et
couverture par tranche de popularité (top 1 000, 1 000 à 10 000, au-delà, rang inconnu). Les rangs
viennent de MAL pour les animes et d'AniList pour les mangas : ils ne se comparent pas d'un type à
l'autre, d'où des tranches calculées par type, jamais sur tout le catalogue.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import psycopg

FILE_NAME = "covers_coverage.json"
BUCKETS = (("top_1000", 1, 1000), ("1000_to_10000", 1001, 10_000),
           ("beyond_10000", 10_001, None))  # fmt: skip


def _share(total: int, with_cover: int) -> dict[str, Any]:
    return {"total": total, "with_cover": with_cover,
            "share": with_cover / total if total else 0.0}  # fmt: skip


def coverage(conn: psycopg.Connection) -> dict[str, Any]:
    by_kind = {
        kind: _share(total, covered)
        for kind, total, covered in conn.execute(
            "SELECT kind, count(*), count(cover_url) FROM catalog.media GROUP BY kind ORDER BY kind"
        )
    }
    by_source: dict[str, dict[str, int]] = {}
    for kind, source, n in conn.execute(
        "SELECT kind, coalesce(cover_source, 'none'), count(*) FROM catalog.media"
        " GROUP BY 1, 2 ORDER BY 1, 2"
    ):
        by_source.setdefault(kind, {})[source] = n
    by_popularity: dict[str, dict[str, Any]] = {}
    for kind, bucket, total, covered in conn.execute(
        "SELECT kind, CASE WHEN popularity IS NULL THEN 'unranked'"
        " WHEN popularity <= 1000 THEN 'top_1000' WHEN popularity <= 10000 THEN '1000_to_10000'"
        " ELSE 'beyond_10000' END, count(*), count(cover_url)"
        " FROM catalog.media GROUP BY 1, 2 ORDER BY 1, 2"
    ):
        by_popularity.setdefault(kind, {})[bucket] = _share(total, covered)
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "buckets": {name: {"from": lo, "to": hi} for name, lo, hi in BUCKETS},
        "by_kind": by_kind,
        "by_source": by_source,
        "by_popularity": by_popularity,
    }


def write(conn: psycopg.Connection, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / FILE_NAME
    path.write_text(json.dumps(coverage(conn), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")  # fmt: skip
    return path
