#!/usr/bin/env bash
# Publie le catalogue local (catalog + mart, embeddings compris) vers la base de production (Neon).
#   make db-publish TARGET_DATABASE_URL='postgresql://…'   (l'URL n'est jamais affichée)
#
# Étapes : 1) tailles vérifiées (offre gratuite Neon : 1 Go) ; 2) job de migration sur la cible
# (schéma du pipeline PUIS Alembic, comme le déploiement) ; 3) catalog et mart de la cible vidés
# puis rechargés en UNE transaction (tout ou rien). Le schéma app (comptes) n'est jamais copié.
# Sécurité : refuse si la cible a déjà des comptes (le vidage du catalogue effacerait leurs
# listes en cascade), sauf FORCE=1 ; demande une confirmation explicite.
set -euo pipefail

: "${TARGET_DATABASE_URL:?TARGET_DATABASE_URL manquante (URL Neon, depuis la console Neon)}"
MAX_MB="${MAX_MB:-900}"          # marge sous le 1 Go de l'offre gratuite Neon
IMAGE="pgvector/pgvector:pg16"   # mêmes outils (pg_dump, psql) que la base locale, Postgres 16
cd "$(dirname "$0")/../.."

local_url=$(grep '^DATABASE_URL=' .env | cut -d= -f2- | tr -d '\r"')
local_url=${local_url//localhost/host.docker.internal}
local_url=${local_url//127.0.0.1/host.docker.internal}
# -i seulement quand on envoie des données : sinon docker lirait (et viderait) la confirmation.
pg() { docker run --rm --add-host=host.docker.internal:host-gateway "$IMAGE" "$@"; }
pg_in() { docker run --rm -i --add-host=host.docker.internal:host-gateway "$IMAGE" "$@"; }

size_mb=$(pg psql "$local_url" -Atc "SELECT round(sum(pg_total_relation_size(c.oid)) / 1048576.0)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('catalog', 'mart') AND c.relkind IN ('r', 'm')")
echo "Taille locale de catalog + mart (tables, index compris) : ${size_mb} Mo (limite : ${MAX_MB} Mo)"
if (( size_mb > MAX_MB )); then
  echo "Trop gros pour l'offre gratuite : rien n'est envoyé." >&2
  exit 1
fi

accounts=0
# Deux requêtes : Postgres analyse une sous-requête même si elle ne s'exécute pas (table absente).
if [[ $(pg psql "$TARGET_DATABASE_URL" -Atc "SELECT to_regclass('app.users') IS NOT NULL") == "t" ]]; then
  accounts=$(pg psql "$TARGET_DATABASE_URL" -Atc "SELECT count(*) FROM app.users")
fi
if (( accounts > 0 )) && [[ "${FORCE:-0}" != "1" ]]; then
  echo "La cible a déjà ${accounts} compte(s) : vider le catalogue effacerait leurs listes." >&2
  echo "Relancer avec FORCE=1 seulement si c'est voulu." >&2
  exit 1
fi
read -r -p "Remplacer catalog et mart de la base cible par la copie locale ? Taper « oui » : " ok
[[ "$ok" == "oui" ]] || { echo "Annulé."; exit 1; }

echo "1/2 Migration de la cible (schéma du pipeline puis Alembic)…"
docker run --rm -e DATABASE_URL="$TARGET_DATABASE_URL" --entrypoint python \
  "${API_IMAGE:-tsuzuku-api:test}" -m app.migrate

echo "2/2 Copie des données (une seule transaction)…"
{
  # Historique quotidien de la PRODUCTION (job jikan-daily) mis de côté par clé naturelle
  # (type + identifiant MAL), puis remis après le rechargement : le vidage en cascade ne le perd pas.
  echo "CREATE TEMP TABLE keep_stats AS SELECT s.*, m.kind AS k_kind, m.mal_id AS k_mal"
  echo "  FROM catalog.media_daily_stats s JOIN catalog.media m ON m.id = s.media_id"
  echo "  WHERE m.mal_id IS NOT NULL;"
  echo "TRUNCATE catalog.media, catalog.genre, catalog.tag RESTART IDENTITY CASCADE;"
  echo "TRUNCATE mart.drop_curve, mart.critical_episode, mart.retention_by_studio,"
  echo "  mart.retention_by_genre, mart.model_runs;"
  pg pg_dump "$local_url" --data-only --schema=catalog --schema=mart --no-owner --no-privileges
  echo "INSERT INTO catalog.media_daily_stats (snapshot_date, media_id, score, members, watching,"
  echo "  completed, on_hold, dropped, plan_to_watch, source, in_season)"
  echo "SELECT k.snapshot_date, m.id, k.score, k.members, k.watching, k.completed, k.on_hold,"
  echo "  k.dropped, k.plan_to_watch, k.source, k.in_season FROM keep_stats k"
  echo "  JOIN catalog.media m ON m.kind = k.k_kind AND m.mal_id = k.k_mal"
  echo "ON CONFLICT (snapshot_date, media_id) DO UPDATE SET score = EXCLUDED.score,"
  echo "  members = EXCLUDED.members, watching = EXCLUDED.watching, completed = EXCLUDED.completed,"
  echo "  on_hold = EXCLUDED.on_hold, dropped = EXCLUDED.dropped,"
  echo "  plan_to_watch = EXCLUDED.plan_to_watch, source = EXCLUDED.source,"
  echo "  in_season = EXCLUDED.in_season;"
} | pg_in psql "$TARGET_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -q

pg psql "$TARGET_DATABASE_URL" -Atc "SELECT 'œuvres : ' || count(*) FROM catalog.media
  UNION ALL SELECT 'embeddings : ' || count(*) FROM catalog.media_embedding"
echo "Publication terminée."
