# ADR 016 — Power BI : schéma bi, rôle lecture seule, mode Import, anonymat k = 5

**Date** : 2026-11-28 · **Statut** : accepté (plan validé par Royston le 2026-11-28 : Neon, k = 5,
récupération des tags AniList des animes)

## Contexte
Phase 13 (SPEC § 11) : un tableau de bord Power BI en 6 pages. Vue d'ensemble, courbes de drop,
studios et genres (Isekai vs Shonen), saison en cours (Jikan), modèles, activité Tsuzuku. Royston
construit le `.pbix` à la main ; le dépôt fournit les vues SQL, les mesures DAX, un thème et le
guide. La production est sur Neon, facturé au temps de calcul (le serveur s'endort au repos).

## Décisions
- **Un schéma `bi` de vues**, seule surface lue par Power BI. Les noms et les colonnes restent
  stables même si les marts évoluent, et les définitions (taux de drop = lâchés / (lâchés +
  terminés), recalculé à partir des comptes, jamais une moyenne de taux) vivent à un seul endroit.
  - Vues sur `catalog` et `mart` : `pipeline/.../db/views_powerbi.sql`, appliqué après
    `schema_mart.sql` par le pipeline et par le job de migration du déploiement (propriété du
    pipeline, ADR 003).
  - Vues sur l'activité (`app`) : migration Alembic `0004`, propriété du backend (ADR 008).
  - `CREATE OR REPLACE VIEW` garde les droits accordés ; il ne peut qu'ajouter des colonnes en
    fin de liste (supprimer ou renommer une colonne demandera un `DROP VIEW` explicite).
  - Les marts sont vidés par `TRUNCATE`, jamais supprimés : les vues ne bloquent aucun
    rechargement (vérifié avant d'écrire les vues).
- **Rôle `tsuzuku_bi`** (`make bi-role`, mot de passe `BI_DB_PASSWORD` du `.env`) : `USAGE` sur
  `bi` et `SELECT` sur ses vues, rien d'autre. Une vue s'exécute avec les droits de son
  propriétaire, donc le rôle lit les agrégats sans pouvoir lire `app.users` ni les tables brutes.
  Sessions en lecture seule, requêtes limitées à 120 s. Testé : lecture de `bi` autorisée ;
  `app`, `catalog` et `mart` refusés ; droits conservés après un redéploiement.
- **Mode Import, pas DirectQuery** : en DirectQuery, chaque clic interroge Neon et le garde
  éveillé (temps de calcul facturé). En Import, un rafraîchissement réveille Neon quelques secondes ;
  les données changent au plus une fois par jour.
- **Anonymat de la page 6** : aucune vue `bi` n'expose d'identité (`user_id`, email, pseudo) ni
  de texte libre (critiques), ce qui est vérifié par un test sur `information_schema`. Aucune
  ligne n'est calculée sur moins de **k = 5 comptes** (`settings.yaml`, `powerbi.min_group_size`,
  recopié dans la migration ; un test vérifie le comportement avec la valeur du fichier). Avec
  peu de comptes, un compteur ou une médiane décrirait une personne précise. Pas de total
  d'entrées publié à côté des lignes par statut : la soustraction redonnerait un statut masqué
  (testé). Conséquence assumée : la page reste vide tant qu'il y a moins de 5 comptes.
- **Mot de passe du rôle** haché en SCRAM-SHA-256 côté client : seul le hachage part vers le
  serveur, un journal de requêtes ne peut pas le contenir (testé).
- **Vues réappliquées seulement si elles changent** : `CREATE OR REPLACE VIEW` pose un verrou
  exclusif même sans changement. L'empreinte SHA-256 de `views_powerbi.sql` est gardée en
  commentaire du schéma `bi` ; le pipeline et le job de migration ne refont rien si elle est
  identique et que toutes les vues existent. Sans cela, un rafraîchissement Power BI en cours
  ferait échouer le job d'ingestion du jour ou un déploiement (testé : un lecteur ouvert ne
  bloque plus rien).
- **Segment « Isekai » par les tags AniList** : le dataset MAL 2020 ne connaît pas ce genre, et
  aucun des animes du mart n'avait de tag. `make anime-tags` les récupère par `idMal` (lots de
  50, requêtes polies, mêmes règles que les mangas : pertinence ≥ 60, jamais de tag adulte) et
  garde l'identifiant AniList s'il n'appartient à aucune autre œuvre. Ponctuel : les animes du
  mart viennent tous du dataset 2020. « Shounen » vient du genre MAL. Un anime peut être dans les
  deux segments, et « Autres » = ni l'un ni l'autre. Tous les segments sont calculés sur la même
  population (les animes de `mart.critical_episode`).
- **`make bi-report`** écrit `reports/powerbi_summary.json` (lignes par vue, taux par segment,
  couverture des tags), repris par `make figures` : le README et le guide ne citent que ces
  chiffres.
- Écartés : connexion de Power BI aux tables brutes (noms instables, données personnelles
  accessibles) ; un entrepôt séparé (coût, synchronisation) ; le segment Isekai deviné par mots du
  synopsis (non vérifiable).

## Conséquences
- Les tags entrent dans le texte des embeddings (ADR 013) : `make embeddings` après
  `make anime-tags` (seuls les textes modifiés sont recalculés).
- Résultats mesurés le 2026-11-28 (base locale, `reports/powerbi_summary.json`) : 3 339 animes
  demandés à AniList, 3 312 trouvés, 3 236 avec au moins un tag retenu ; 200 animes isekai.
- Page 4 (Jikan) vide tant que l'API Jikan est en panne (depuis la phase 6) ; elle se remplira
  toute seule avec le job `jikan-daily`.
- Connexion Power BI ↔ Neon : SSL obligatoire. Si le connecteur PostgreSQL de Power BI refuse
  l'hôte Neon (SNI), le guide donne la parade (`options=endpoint=…`) et le repli sur la base
  locale.
