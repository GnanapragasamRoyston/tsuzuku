"""Modération des jaquettes proposées (ADR 012) : Royston liste, valide ou refuse en ligne de
commande. Pas de page d'administration web : aucune surface d'attaque en plus.

    make covers-review                 # propositions en attente
    make covers-approve ID=12          # la jaquette devient celle de l'œuvre
    make covers-reject ID=13

La liste ne montre jamais l'email de l'auteur, seulement son pseudo (minimisation).
"""

import argparse
import sys

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings


class NotPending(Exception):
    """Proposition inconnue ou déjà traitée."""


def _database_url() -> str:
    # Même URL que l'API, sans le préfixe de pilote SQLAlchemy, que psycopg ne comprend pas.
    return Settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def pending(url: str) -> list[dict]:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT s.id, s.url, s.created_at, m.id AS media_id, m.title, m.kind,"
            " m.cover_url AS current_cover, u.pseudo"
            " FROM app.cover_suggestion s JOIN catalog.media m ON m.id = s.media_id"
            " JOIN app.users u ON u.id = s.user_id"
            " WHERE s.status = 'pending' ORDER BY s.created_at, s.id"
        ).fetchall()


def _decide(url: str, suggestion_id: int, status: str) -> None:
    with psycopg.connect(url) as conn, conn.transaction():
        row = conn.execute(
            "UPDATE app.cover_suggestion SET status = %s, reviewed_at = now()"
            " WHERE id = %s AND status = 'pending' RETURNING media_id, url",
            (status, suggestion_id),
        ).fetchone()
        if row is None:
            raise NotPending(suggestion_id)
        if status == "approved":
            # La jaquette validée remplace l'actuelle ; cover_source = 'suggestion' la protège des
            # synchros suivantes (AniList, Jikan). Couleur AniList retirée : elle ne correspond
            # plus à l'image.
            conn.execute(
                "UPDATE catalog.media SET cover_url = %s, cover_source = 'suggestion',"
                " cover_color = NULL, updated_at = now() WHERE id = %s",
                (row[1], row[0]),
            )


def approve(url: str, suggestion_id: int) -> None:
    _decide(url, suggestion_id, "approved")


def reject(url: str, suggestion_id: int) -> None:
    _decide(url, suggestion_id, "rejected")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Modération des jaquettes proposées")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for action in ("approve", "reject"):
        sub.add_parser(action).add_argument("id", type=int)
    args = parser.parse_args(argv)
    url = _database_url()
    if args.action == "list":
        rows = pending(url)
        if not rows:
            print("Aucune proposition en attente.")
        for r in rows:
            current = r["current_cover"] or "(aucune)"
            print(f"#{r['id']}  {r['title']} ({r['kind']}, œuvre {r['media_id']})")
            print(f"     par {r['pseudo']}\n     proposée : {r['url']}\n     actuelle : {current}")
        return 0
    try:
        (approve if args.action == "approve" else reject)(url, args.id)
    except NotPending:
        print(f"Proposition #{args.id} inconnue ou déjà traitée.", file=sys.stderr)
        return 1
    print(f"Proposition #{args.id} : {'validée' if args.action == 'approve' else 'refusée'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
