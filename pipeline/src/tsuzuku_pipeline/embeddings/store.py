"""Calcul et stockage des embeddings dans catalog.media_embedding (pgvector).

Idempotent : une œuvre n'est (re)calculée que si son texte ou le modèle a changé (empreinte
`text_hash`). Relancer `make embeddings` après une synchro AniList ne calcule que les nouvelles
œuvres et celles dont la fiche a bougé.
"""

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

import numpy as np
import psycopg

from tsuzuku_pipeline.embeddings.encoder import Encoder
from tsuzuku_pipeline.embeddings.queries import missing_count  # noqa: F401  (ré-exporté)
from tsuzuku_pipeline.embeddings.text import media_text

logger = logging.getLogger("tsuzuku_pipeline.embeddings")

# Genres par ordre alphabétique ; tags AniList par pertinence décroissante (les plus parlants).
DOCS_SQL = """
SELECT m.id, m.mal_id, m.kind, m.title, m.title_alt, m.synopsis,
  coalesce((SELECT array_agg(g.name ORDER BY g.name) FROM catalog.media_genre mg
            JOIN catalog.genre g ON g.id = mg.genre_id WHERE mg.media_id = m.id), '{}'),
  coalesce((SELECT array_agg(t.name ORDER BY mt.rank DESC, t.name)
            FROM (SELECT tag_id, rank FROM catalog.media_tag WHERE media_id = m.id
                  ORDER BY rank DESC, tag_id LIMIT %(tags)s) mt
            JOIN catalog.tag t ON t.id = mt.tag_id), '{}')
FROM catalog.media m
WHERE %(kind)s::text IS NULL OR m.kind = %(kind)s
ORDER BY m.id
"""


def documents(
    conn: psycopg.Connection, tags_max: int = 10, kind: str | None = None
) -> list[dict[str, Any]]:
    """[{id, mal_id, kind, text}] pour chaque œuvre (ou d'un seul type)."""
    rows = conn.execute(DOCS_SQL, {"tags": tags_max, "kind": kind}).fetchall()
    return [
        {
            "id": mid,
            "mal_id": mal,
            "kind": k,
            "text": media_text(
                title=title, title_alt=alt, kind=k, genres=genres, tags=tags, synopsis=synopsis
            ),
        }
        for mid, mal, k, title, alt, synopsis, genres, tags in rows
    ]


def text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def _vector(v: np.ndarray) -> str:
    # Format texte de pgvector : « [0.1,0.2,…] » (pas besoin du paquet Python pgvector ici).
    return "[" + ",".join(f"{x:.7g}" for x in v.tolist()) + "]"


def _batches(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


UPSERT = (
    "INSERT INTO catalog.media_embedding (media_id, model, text_hash, embedding)"
    " VALUES (%s, %s, %s, %s::vector) ON CONFLICT (media_id) DO UPDATE SET"
    " model = EXCLUDED.model, text_hash = EXCLUDED.text_hash,"
    " embedding = EXCLUDED.embedding, updated_at = now()"
)


def build(
    conn: psycopg.Connection, encoder: Encoder, batch_size: int = 256, tags_max: int = 10
) -> dict[str, int]:
    docs = documents(conn, tags_max)
    known = dict(conn.execute("SELECT media_id, text_hash FROM catalog.media_embedding").fetchall())
    todo = [(d["id"], d["text"], text_hash(encoder.name, d["text"])) for d in docs]
    todo = [t for t in todo if known.get(t[0]) != t[2]]
    done = 0
    for batch in _batches(todo, batch_size):
        vectors = encoder.encode([text for _, text, _ in batch])
        rows = [
            (mid, encoder.name, h, _vector(v))
            for (mid, _, h), v in zip(batch, vectors, strict=True)
        ]
        with conn.transaction():
            conn.cursor().executemany(UPSERT, rows)
        done += len(batch)
        logger.info("Embeddings : %d / %d", done, len(todo))
    return {"computed": len(todo), "total": len(docs)}
