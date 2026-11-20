-- Schéma catalog : œuvres et genres. Possédé par pipeline/ (ADR 003) ; Alembic (phase 7) ne gère
-- que le schéma app. Idempotent : rejouable à chaque `make spark`.

CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE IF NOT EXISTS catalog.media (
    -- Identifiant interne stable : les listes des utilisateurs (app.list_entry) pointeront dessus.
    -- On ne le dérive pas de mal_id car mangas et animes ont des MAL_ID qui se chevauchent.
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('anime', 'manga', 'manhwa', 'manhua')),
    mal_id        integer,
    anilist_id    integer UNIQUE,
    title         text NOT NULL,
    title_alt     text,
    synopsis      text,
    episodes      integer CHECK (episodes >= 0),
    chapters      integer CHECK (chapters >= 0),
    airing_status text,
    format        text,
    duration_min  real,
    start_year    integer,
    creators      text[] NOT NULL DEFAULT '{}',
    source        text,
    age_rating    text,
    cover_url     text,
    popularity    integer,
    -- Qui a créé la ligne (ex. 'mal_kaggle_2020', plus tard 'jikan', 'anilist'). Permet de
    -- retirer les œuvres sorties d'une source (ex. nouvellement classées adultes) sans toucher
    -- à celles des autres sources.
    data_source   text NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    -- Clé naturelle de l'upsert : un MAL_ID est unique à l'intérieur d'un type d'œuvre.
    CONSTRAINT media_kind_mal_id_key UNIQUE (kind, mal_id)
);

-- data_source est arrivée après la 1re version. Ajout seulement si absente (un ALTER TABLE
-- verrouille la table même quand il ne change rien). Les lignes déjà présentes venaient toutes
-- du dataset Kaggle : c'est leur valeur de rattrapage, puis le défaut est retiré.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'catalog' AND table_name = 'media' AND column_name = 'data_source'
    ) THEN
        ALTER TABLE catalog.media ADD COLUMN data_source text NOT NULL DEFAULT 'mal_kaggle_2020';
        ALTER TABLE catalog.media ALTER COLUMN data_source DROP DEFAULT;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS catalog.genre (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog.media_genre (
    media_id bigint  NOT NULL REFERENCES catalog.media (id) ON DELETE CASCADE,
    genre_id integer NOT NULL REFERENCES catalog.genre (id) ON DELETE CASCADE,
    PRIMARY KEY (media_id, genre_id)
);
-- La PK couvre « genres d'une œuvre » ; cet index couvre « œuvres d'un genre ».
CREATE INDEX IF NOT EXISTS media_genre_genre_id_idx ON catalog.media_genre (genre_id);

-- Tags AniList (phase 6) : plus fins que les genres (« Time Travel », « Tragedy »…). Serviront aux
-- recos basées sur le contenu (phase 10). rank = pertinence du tag pour l'œuvre (0-100, AniList).
CREATE TABLE IF NOT EXISTS catalog.tag (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog.media_tag (
    media_id bigint  NOT NULL REFERENCES catalog.media (id) ON DELETE CASCADE,
    tag_id   integer NOT NULL REFERENCES catalog.tag (id) ON DELETE CASCADE,
    rank     smallint CHECK (rank BETWEEN 0 AND 100),
    PRIMARY KEY (media_id, tag_id)
);
CREATE INDEX IF NOT EXISTS media_tag_tag_id_idx ON catalog.media_tag (tag_id);

-- Statistiques quotidiennes (DAG jikan_daily_ingest, phase 6) : une ligne par œuvre et par jour.
-- Clé (date, œuvre) : relancer le DAG le même jour met la ligne à jour au lieu de la doubler.
CREATE TABLE IF NOT EXISTS catalog.media_daily_stats (
    snapshot_date date    NOT NULL,
    media_id      bigint  NOT NULL REFERENCES catalog.media (id) ON DELETE CASCADE,
    score         real    CHECK (score BETWEEN 0 AND 10),
    members       integer CHECK (members >= 0),
    watching      integer CHECK (watching >= 0),
    completed     integer CHECK (completed >= 0),
    on_hold       integer CHECK (on_hold >= 0),
    dropped       integer CHECK (dropped >= 0),
    plan_to_watch integer CHECK (plan_to_watch >= 0),
    source        text    NOT NULL,  -- ex. 'jikan' (statistiques MyAnimeList)
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, media_id)
);
-- « Historique d'une œuvre » (courbes Power BI) : la PK couvre « toutes les œuvres d'un jour ».
CREATE INDEX IF NOT EXISTS media_daily_stats_media_idx
    ON catalog.media_daily_stats (media_id, snapshot_date);

-- in_season : l'anime faisait partie de la saison en cours (/seasons/now) ce jour-là, par opposition
-- aux animes de la watchlist. /trending filtre dessus, comme son repli en direct sur Jikan.
-- Ajout conditionnel (colonne arrivée après la 1re version de la table), sans verrou inutile.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'catalog' AND table_name = 'media_daily_stats'
          AND column_name = 'in_season'
    ) THEN
        ALTER TABLE catalog.media_daily_stats ADD COLUMN in_season boolean NOT NULL DEFAULT true;
    END IF;
END $$;
