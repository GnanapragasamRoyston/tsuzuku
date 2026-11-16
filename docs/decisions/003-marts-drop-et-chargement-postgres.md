# ADR 003 — Marts de drop/rétention et chargement Postgres

**Date** : 2026-11-16 · **Statut** : accepté (seuils validés par Royston)

## Contexte
La phase 2 transforme la couche `clean` (107 M interactions) en indicateurs produit : courbe de
drop, épisode critique, point de non-retour, rétention par genre et studio. Ils doivent être
servis par l'API (phase 5) et lus par Power BI (phase 12), donc vivre dans Postgres.

## Décisions

### Définitions
- **Population** : lignes Completed et Dropped uniquement (issue connue). Watching / On Hold sont
  ignorés : *censure à droite*, limite assumée.
- **Épisode atteint** : Completed → `episodes` (le statut fait foi : 332 795 lignes Completed ont
  un `watched_episodes` inférieur, listes non mises à jour) ; Dropped → `watched_episodes`
  plafonné à `episodes` (46 276 lignes le dépassent).
- **Courbe de drop** : drops par épisode atteint et part cumulée. L'épisode **0** (lâché avant de
  commencer : 885 298 drops) est gardé dans la courbe.
- **Épisode critique** : épisode **≥ 1** qui concentre le plus de drops (égalité → le plus tôt).
  L'épisode 0 est exclu, sinon il gagnerait pour une grande partie du catalogue sans rien dire
  du contenu. Publié seulement si `episodes ≥ min_episodes` (3) et si au moins `min_drops` (50)
  drops ont lieu à un épisode ≥ 1.
- **Point de non-retour** — définition **relative** :
  `risk(e) = drops avec épisode atteint ≥ e / (completed + ces drops)` est le risque de lâcher
  pour qui a atteint *e* ; `initial_drop_risk = risk(1)`. Le point de non-retour est le premier
  *e* où `risk(e) ≤ no_return_risk_ratio × risk(1)` (0,25 : « risque divisé par 4 »).
  `risk(e)` ne peut que baisser avec *e* : le premier *e* qui passe le seuil suffit. Null si
  jamais atteint (on n'invente pas de valeur).

  **Pourquoi relatif (révision du 2026-11-16, choix de Royston après mesure)** : la 1re version
  utilisait un seuil absolu (`completed / (completed + drops ≥ e) ≥ 0,9`). Sur les données
  réelles, il tombait à l'épisode 1 pour **2 022 animes sur 3 339** : les utilisateurs de MAL
  déclarent ~16 fois plus de Completed que de Dropped, donc le risque initial médian n'est que
  de 8 % et le seuil est franchi d'emblée. Comparer l'anime à lui-même neutralise cette
  sous-déclaration. Mesures comparées (script d'exploration, même jour) :

  | Définition | Point à l'ép. 1 | Position médiane dans la série |
  |---|---:|---:|
  | absolue ≥ 0,9 | 2 022 | 0,08 |
  | absolue ≥ 0,98 | 337 | 0,42 |
  | relative ÷ 4 (retenue) | 0 | 0,46 |

  Contrôle qualitatif : Death Note → critique 25, non-retour 26 ; Naruto → critique 135
  (début des fillers), non-retour 138.
- **Rétention** par genre/studio : `drop_rate = dropped / (dropped + completed)` ;
  `completion_rate = completed / commencés` (Watching + Completed + On Hold + Dropped, Plan to
  Watch exclu) — ce n'est donc pas `1 − drop_rate` ; `median_drop_progress` = médiane
  approximative (`percentile_approx`) de `watched / episodes` sur les drops. Publié si
  ≥ 1 000 interactions et ≥ 5 animes.

### Calcul
- Agrégation par anime **avant** l'explosion des genres/studios (16 000 lignes au lieu de
  ~300 M). Seule la médiane exige les lignes individuelles (une médiane ne s'additionne pas).
- `outcomes` mis en cache : relu par deux calculs.
- Marts écrits en Parquet (`data/marts/`) avant chargement : on peut recharger sans Spark, et
  `reports/marts_summary.json` décrit exactement ce qui est chargé (contrôles de cohérence
  bloquants : courbes qui ne finissent pas à 1, taux hors [0, 1]).

### Chargement
- **Spark `toLocalIterator()` + `COPY` psycopg 3**, et non JDBC Spark (driver Java à télécharger,
  difficile à tester) ni `toPandas()` (types numpy non adaptés par psycopg, dépendances en plus).
  Les marts sont petits : le streaming ligne à ligne suffit.
- **Propriété des schémas** : `pipeline/` crée `catalog` et `mart` (SQL idempotent,
  `db/schema_*.sql`). Alembic (phase 7) ne gérera que `app`.
- **`catalog.media` en upsert** sur `(kind, mal_id)` : les `id` restent stables pour les futures
  listes utilisateurs. Genres remplacés par œuvre.
- **Marts remplacés en entier dans une transaction** (`TRUNCATE` + `INSERT`) : un lecteur voit
  l'ancienne ou la nouvelle version, jamais un état intermédiaire. Un `mal_id` absent du
  catalogue annule tout.
- **`lock_timeout` de 30 s** : `TRUNCATE` attend les lectures en cours ; une session restée
  ouverte (outil BI, psql) bloquerait le chargement indéfiniment. Découvert en test : une
  transaction de lecture jamais fermée a figé la suite pendant 10 min.
- **Tout le chargement dans une seule transaction** (catalogue + 4 marts ; les transactions
  internes deviennent des savepoints) : un échec au 3ᵉ mart laisse la base entièrement dans
  l'état précédent, jamais un mélange de versions.
- **DDL sans verrou inutile** : les colonnes ajoutées après coup (`initial_drop_risk`,
  `data_source`) passent par un bloc `DO` qui ne fait `ALTER TABLE` que si la colonne manque.
  `ALTER … ADD COLUMN IF NOT EXISTS` prend un verrou exclusif même quand il ne change rien.
- **`catalog.media.data_source`** : chaque ligne connaît sa source (`mal_kaggle_2020`, puis
  `jikan`, `anilist`). Le chargement retire les œuvres de *sa* source qui ont disparu de `clean`
  (ex. nouvellement classées adultes), sans toucher aux autres sources.
- **Garde-fous de cohérence à deux niveaux** : si `marts_summary.json` signale une anomalie, les
  Parquet sont supprimés (l'étape sera refaite) et le chargement relit le résumé avant d'écrire.

### Fraîcheur des étapes
Chaque étape qui dépend de réglages (`clean`, `quality`, `sample`, `marts`) enregistre l'empreinte
de sa config dans `data/.stamps/<étape>.json` après un succès. Changer un seuil dans
`settings.yaml` rend l'étape périmée sans `--force`. Le tampon est effacé avant le build : une
étape qui échoue reste périmée.

### Reporté
- Performance : `retention_by` relit `animelist` pour le genre puis pour le studio (4 passes au
  lieu de 2). Acceptable aujourd'hui (étape marts de l'ordre de quelques minutes) ; à factoriser si
  le volume grandit.

## Alternatives écartées
- Épisode critique incluant l'épisode 0 : peu informatif (voir ci-dessus).
- Kaplan-Meier complet avec censure : plus juste statistiquement, mais demande de traiter
  Watching/On Hold comme censurés avec un épisode courant fiable — piste pour plus tard.
- Charger les 107 M lignes brutes dans Postgres pour calculer en SQL : inutile et lourd ; Spark
  reste le moteur de calcul, Postgres sert les résultats.
