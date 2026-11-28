"""`make bi-report` : chiffres lus dans les vues Power BI → reports/powerbi_summary.json.

Phase 13 (ADR 016). Sert de source aux chiffres cités dans le README, le GUIDE Power BI et
`make figures` (CLAUDE.md § 5 : aucun chiffre inventé). Lecture seule ; la base lue (locale ou
production) est indiquée, jamais son adresse.
"""

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql

from tsuzuku_pipeline.config import load_settings, resolve_path
from tsuzuku_pipeline.db import loader

logger = logging.getLogger("tsuzuku_pipeline.bi_report")

# Toutes les vues bi : celles du pipeline et celles de l'activité (migration Alembic 0004, absentes
# d'une base qui n'a que le schéma du pipeline → None, jamais 0 inventé).
VIEWS = (
    "anime_drop", "anime_genre", "anime_studio", "anime_segment", "segment_retention",
    "drop_curve", "retention_by_genre", "retention_by_studio", "daily_stats", "model_metrics",
    "app_totals", "app_signups_weekly", "app_status_counts", "app_top_added",
    "app_declared_drops",
)  # fmt: skip
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def database_label(host: str) -> str:
    """Base lue, sans son adresse : boucle locale ou socket Unix → « locale » ; hôte Neon
    (production, ADR 014) → « production » ; tout autre hôte → « inconnue », plutôt qu'un
    libellé deviné (un chiffre du README ne doit pas passer pour de la prod sans l'être)."""
    if host in LOCAL_HOSTS or host.startswith("/"):
        return "locale"
    if host.endswith(".neon.tech"):
        return "production"
    return "inconnue"


def _count(conn: psycopg.Connection, view: str) -> int | None:
    exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"bi.{view}",)).fetchone()[0]
    if not exists:
        return None
    query = sql.SQL("SELECT count(*) FROM bi.{}").format(sql.Identifier(view))
    return conn.execute(query).fetchone()[0]


def summarize(conn: psycopg.Connection) -> dict[str, Any]:
    drops, finished, animes = conn.execute(
        "SELECT sum(nb_drops), sum(nb_finished), count(*) FROM bi.anime_drop"
    ).fetchone()
    tagged = conn.execute(
        "SELECT count(*) FROM bi.anime_drop a WHERE EXISTS"
        " (SELECT 1 FROM catalog.media_tag t WHERE t.media_id = a.media_id)"
    ).fetchone()[0]
    segments = [
        {"segment": s, "nb_anime": n, "nb_drops": d, "nb_completed": c, "drop_rate": r}
        for s, n, d, c, r in conn.execute(
            "SELECT segment, nb_anime, nb_drops, nb_completed, drop_rate"
            " FROM bi.segment_retention ORDER BY segment"
        )
    ]
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "database": database_label(conn.info.host or ""),
        "anime_with_drop_data": animes,
        "anime_with_tags": tagged,
        # Σ lâchés / Σ (lâchés + terminés), README § Définitions.
        "global_drop_rate": float(drops) / float(finished) if finished else None,
        "statuses_finished": int(finished or 0),
        "segments": [
            {**s, "nb_drops": int(s["nb_drops"]), "nb_completed": int(s["nb_completed"])}
            for s in segments
        ],  # fmt: skip
        "view_rows": {v: _count(conn, v) for v in VIEWS},
    }


@contextmanager
def _connection(conn: psycopg.Connection | None):
    if conn is not None:
        yield conn
        return
    with loader.connect(loader.database_url()) as own:
        own.read_only = True
        yield own


def run(settings: dict[str, Any], conn: psycopg.Connection | None = None) -> dict[str, Any]:
    with _connection(conn) as c:
        summary = summarize(c)
    reports = resolve_path(settings, "reports")
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "powerbi_summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Résumé des vues Power BI écrit dans %s", path)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
    run(load_settings())


if __name__ == "__main__":
    main()
