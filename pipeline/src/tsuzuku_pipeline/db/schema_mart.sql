-- Schéma mart : agrégats analytiques produits par Spark (phase 2), lus par l'API et Power BI.
-- Tables entièrement remplacées à chaque chargement (dans une transaction). Idempotent.
-- Définitions des indicateurs : README § Définitions et ADR 003.

CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS mart.drop_curve (
    media_id         bigint  NOT NULL REFERENCES catalog.media (id) ON DELETE CASCADE,
    episode          integer NOT NULL CHECK (episode >= 0),  -- 0 = lâché avant de commencer
    nb_drops         integer NOT NULL CHECK (nb_drops > 0),
    cumulative_share real    NOT NULL CHECK (cumulative_share > 0 AND cumulative_share <= 1),
    PRIMARY KEY (media_id, episode)
);

CREATE TABLE IF NOT EXISTS mart.critical_episode (
    media_id            bigint  PRIMARY KEY REFERENCES catalog.media (id) ON DELETE CASCADE,
    critical_episode    integer NOT NULL CHECK (critical_episode >= 1),
    critical_drop_share real    NOT NULL CHECK (critical_drop_share > 0 AND critical_drop_share <= 1),
    initial_drop_risk   real    CHECK (initial_drop_risk BETWEEN 0 AND 1),
    point_of_no_return  integer CHECK (point_of_no_return >= 1),  -- null : seuil jamais atteint
    nb_drops            integer NOT NULL,
    nb_completed        integer NOT NULL,
    drop_rate           real    NOT NULL CHECK (drop_rate BETWEEN 0 AND 1)
);

-- initial_drop_risk est arrivée après la 1re version (définition relative du point de
-- non-retour, ADR 003). Pour une base déjà créée, on n'ajoute la colonne QUE si elle manque :
-- un ALTER TABLE prend un verrou exclusif, même quand « IF NOT EXISTS » ne change rien, et
-- bloquerait l'API et Power BI à chaque chargement.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'mart' AND table_name = 'critical_episode'
          AND column_name = 'initial_drop_risk'
    ) THEN
        ALTER TABLE mart.critical_episode
            ADD COLUMN initial_drop_risk real CHECK (initial_drop_risk BETWEEN 0 AND 1);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS mart.retention_by_genre (
    genre                text    PRIMARY KEY,
    nb_anime             integer NOT NULL,
    nb_completed         bigint  NOT NULL,
    nb_dropped           bigint  NOT NULL,
    drop_rate            real    NOT NULL CHECK (drop_rate BETWEEN 0 AND 1),
    completion_rate      real    NOT NULL CHECK (completion_rate BETWEEN 0 AND 1),
    median_drop_progress real    CHECK (median_drop_progress BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS mart.retention_by_studio (
    studio               text    PRIMARY KEY,
    nb_anime             integer NOT NULL,
    nb_completed         bigint  NOT NULL,
    nb_dropped           bigint  NOT NULL,
    drop_rate            real    NOT NULL CHECK (drop_rate BETWEEN 0 AND 1),
    completion_rate      real    NOT NULL CHECK (completion_rate BETWEEN 0 AND 1),
    median_drop_progress real    CHECK (median_drop_progress BETWEEN 0 AND 1)
);

-- Historique des entraînements (phase 3+). AJOUT SEUL : jamais vidée ni remplacée, c'est la trace
-- de ce qui a été entraîné, sur quelles données, avec quels résultats.
CREATE TABLE IF NOT EXISTS mart.model_runs (
    run_id           uuid        PRIMARY KEY,
    created_at       timestamptz NOT NULL,
    model_name       text        NOT NULL,  -- ex. drop
    model_type       text        NOT NULL,  -- ex. hgb
    params           jsonb       NOT NULL,
    metrics          jsonb       NOT NULL,
    data_fingerprint text        NOT NULL,  -- empreinte des données brutes + config
    artifact         text
);
