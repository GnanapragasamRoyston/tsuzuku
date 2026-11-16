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
