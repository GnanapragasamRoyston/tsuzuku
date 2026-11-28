-- Schéma bi : vues lues par Power BI (phase 13, SPEC § 11, ADR 016). Power BI ne lit jamais les
-- tables brutes : ces vues fixent des noms et des colonnes stables, et le rôle tsuzuku_bi n'a
-- accès qu'à elles (une vue s'exécute avec les droits de son propriétaire).
-- Vues sur catalog et mart ici (propriété du pipeline, ADR 003) ; vues sur l'activité des comptes
-- (schéma app) dans la migration Alembic 0004, propriété du backend.
-- Idempotent : appliqué après schema_mart.sql par le pipeline (apply_schemas) et par le job de
-- migration du déploiement. CREATE OR REPLACE VIEW ne peut qu'AJOUTER des colonnes en fin de
-- liste : supprimer ou renommer une colonne demande un DROP VIEW explicite.
-- Taux de drop partout = lâchés / (lâchés + terminés), recalculé à partir des comptes (jamais
-- une moyenne de taux), comme dans le README § Définitions.

CREATE SCHEMA IF NOT EXISTS bi;

-- Animes qui ont des données de drop (mart.critical_episode : volume minimal atteint, phase 2).
CREATE OR REPLACE VIEW bi.anime_drop AS
SELECT m.id                                     AS media_id,
       m.mal_id,
       m.title,
       m.title_alt,
       m.format,
       m.episodes,
       m.start_year,
       m.popularity,
       NULLIF(array_to_string(m.creators, ', '), '') AS studios,
       c.nb_drops,
       c.nb_completed,
       c.nb_drops + c.nb_completed              AS nb_finished,
       c.drop_rate,
       c.critical_episode,
       c.critical_drop_share,
       c.initial_drop_risk,
       c.point_of_no_return
FROM mart.critical_episode c
JOIN catalog.media m ON m.id = c.media_id;

-- Tables de liaison (un anime a plusieurs genres et studios) : filtres et segments Power BI.
CREATE OR REPLACE VIEW bi.anime_genre AS
SELECT mg.media_id, g.name AS genre
FROM mart.critical_episode c
JOIN catalog.media_genre mg ON mg.media_id = c.media_id
JOIN catalog.genre g ON g.id = mg.genre_id;

CREATE OR REPLACE VIEW bi.anime_studio AS
SELECT m.id AS media_id, s.studio
FROM mart.critical_episode c
JOIN catalog.media m ON m.id = c.media_id
CROSS JOIN LATERAL unnest(m.creators) AS s (studio);

-- Segments de la page 3 : « Isekai » vient du tag AniList (le dataset MAL 2020 ne connaît pas ce
-- genre ; tags récupérés par `make anime-tags`), « Shounen » du genre MAL. Un anime peut être
-- dans les deux ; « Autres » = ni l'un ni l'autre. Même population pour tous les segments : les
-- animes de mart.critical_episode.
CREATE OR REPLACE VIEW bi.anime_segment AS
WITH tagged AS (
    SELECT mt.media_id, 'Isekai'::text AS segment
    FROM catalog.media_tag mt JOIN catalog.tag t ON t.id = mt.tag_id
    WHERE t.name = 'Isekai'
    UNION
    SELECT mg.media_id, 'Shounen'::text
    FROM catalog.media_genre mg JOIN catalog.genre g ON g.id = mg.genre_id
    WHERE g.name = 'Shounen'
)
SELECT c.media_id, t.segment
FROM mart.critical_episode c
JOIN tagged t ON t.media_id = c.media_id
UNION ALL
SELECT c.media_id, 'Autres'::text
FROM mart.critical_episode c
WHERE NOT EXISTS (SELECT 1 FROM tagged t WHERE t.media_id = c.media_id);

CREATE OR REPLACE VIEW bi.segment_retention AS
SELECT s.segment,
       count(*)                       AS nb_anime,
       sum(c.nb_drops)                AS nb_drops,
       sum(c.nb_completed)            AS nb_completed,
       sum(c.nb_drops)::double precision
           / NULLIF(sum(c.nb_drops + c.nb_completed), 0) AS drop_rate
FROM bi.anime_segment s
JOIN mart.critical_episode c ON c.media_id = s.media_id
GROUP BY s.segment;

-- Courbe de drop d'un anime : part des drops à chaque épisode (0 = avant de commencer) et
-- marqueurs de l'épisode critique et du point de non-retour (page 2).
CREATE OR REPLACE VIEW bi.drop_curve AS
SELECT d.media_id,
       d.episode,
       d.nb_drops,
       d.cumulative_share,
       d.nb_drops::double precision / sum(d.nb_drops) OVER (PARTITION BY d.media_id) AS share,
       COALESCE(d.episode = c.critical_episode, false)   AS is_critical,
       COALESCE(d.episode = c.point_of_no_return, false) AS is_point_of_no_return
FROM mart.drop_curve d
LEFT JOIN mart.critical_episode c ON c.media_id = d.media_id;

CREATE OR REPLACE VIEW bi.retention_by_genre AS
SELECT genre, nb_anime, nb_completed, nb_dropped, drop_rate, completion_rate, median_drop_progress
FROM mart.retention_by_genre;

CREATE OR REPLACE VIEW bi.retention_by_studio AS
SELECT studio, nb_anime, nb_completed, nb_dropped, drop_rate, completion_rate,
       median_drop_progress
FROM mart.retention_by_studio;

-- Saison en cours (page 4) : une ligne par œuvre et par jour (DAG jikan_daily_ingest).
CREATE OR REPLACE VIEW bi.daily_stats AS
SELECT s.snapshot_date, s.media_id, m.title, m.kind, s.in_season, s.score, s.members,
       s.watching, s.completed, s.on_hold, s.dropped, s.plan_to_watch
FROM catalog.media_daily_stats s
JOIN catalog.media m ON m.id = s.media_id;

-- Métriques des modèles (page 5) : le JSON de mart.model_runs aplati en lignes (chemin, valeur),
-- par ex. « test.roc_auc » ou « test.at_k.10.ndcg ». Seules les valeurs numériques sont gardées ;
-- is_latest marque le dernier entraînement de chaque modèle.
CREATE OR REPLACE VIEW bi.model_metrics AS
WITH RECURSIVE walk (run_id, path, value) AS (
    SELECT r.run_id, e.key, e.value
    FROM mart.model_runs r
    CROSS JOIN LATERAL jsonb_each(r.metrics) e
    UNION ALL
    SELECT w.run_id, w.path || '.' || e.key, e.value
    FROM walk w
    -- jsonb_each refuse une valeur qui n'est pas un objet : on lui passe un objet vide.
    CROSS JOIN LATERAL jsonb_each(
        CASE WHEN jsonb_typeof(w.value) = 'object' THEN w.value ELSE '{}'::jsonb END) e
),
latest AS (
    SELECT model_name, max(created_at) AS created_at FROM mart.model_runs GROUP BY model_name
)
SELECT r.run_id,
       r.model_name,
       r.model_type,
       r.created_at,
       r.created_at = l.created_at          AS is_latest,
       w.path                               AS metric,
       (w.value #>> '{}')::double precision AS value
FROM walk w
JOIN mart.model_runs r ON r.run_id = w.run_id
JOIN latest l ON l.model_name = r.model_name
WHERE jsonb_typeof(w.value) = 'number';
