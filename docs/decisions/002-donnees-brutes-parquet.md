# ADR 002 — Ingestion du dataset Kaggle : couches Parquet, schémas explicites, filtre adulte

**Date** : 2026-11-16 · **Statut** : accepté

## Contexte
Le dataset « Anime Recommendation Database 2020 » (Kaggle `hernan4444/anime-recommendation-database-2020`,
licence CC0-1.0, relevée via l'API Kaggle) fournit ~2,9 Go de CSV, dont `animelist.csv` (~2 Go).
Les phases 2 à 4 doivent le relire souvent ; il contient des contenus adultes à exclure partout
(SPEC § 2.1) et des valeurs sales (`"Unknown"` dans des colonnes numériques).

## Décisions
1. **Téléchargement fichier par fichier** (5 CSV) plutôt que l'archive complète : le dataset contient
   aussi 17 562 zips HTML inutiles. Idempotence par **taille** annoncée par l'API ; `manifest.json`
   garde le **sha256** de chaque fichier pour la traçabilité.
2. **Trois couches** :
   - `data/raw/` : CSV tels quels ;
   - `data/parquet/staging/` : typé, **non filtré**, fidèle à la source → base du rapport qualité ;
   - `data/parquet/clean/` : filtré → **seule entrée** des phases suivantes.
   Séparer staging et clean permet de mesurer exactement ce que chaque filtre retire.
3. **Parquet** : format colonnaire compressé ; une requête qui lit 2 colonnes ne lit que ces 2
   colonnes, et le schéma est stocké avec les données (plus de re-parsing du CSV).
4. **Schémas explicites** (pas d'`inferSchema`, qui imposerait une passe supplémentaire sur 109 M
   lignes et peut se tromper). `anime.csv` est lu en texte puis converti à la main car ses colonnes
   numériques contiennent `"Unknown"`. Mode `PERMISSIVE` : une valeur illisible devient null et
   est comptée par le rapport, jamais perdue en silence.
5. **Filtre adulte** : exclu si `Rating` commence par `Rx` **ou** si le genre contient `Hentai`
   (3 animes sont `Hentai` sans rating `Rx`). Un rating inconnu ne suffit pas à exclure.
6. **Orphelins exclus** : une interaction dont l'`anime_id` est absent d'`anime.csv` est retirée,
   car on ne peut pas prouver que l'œuvre est tout public. Implémenté par une **semi-jointure
   broadcast** sur les ids autorisés : un seul filtre couvre adulte + orphelin, sans shuffle des
   109 M lignes.
7. **Colonnes agrégées d'`anime.csv` conservées** (`dropped`, `completed`, `score_*`...) pour
   l'EDA et Power BI, mais **interdites comme features** du modèle de drop : elles résument
   l'issue qu'on cherche à prédire (fuite de la cible). Un ADR dédié en phase 3 le formalisera.
8. **Échantillon de dev par hachage d'utilisateur** (`xxhash64(user_id, seed)`) : on garde tout
   l'historique des utilisateurs tirés, le résultat ne dépend ni du partitionnement ni de la
   machine, et animelist/rating_complete gardent les mêmes utilisateurs.

## Alternatives écartées
- **pandas** : 109 M lignes ne tiennent pas confortablement en RAM (règle du projet).
- **Charger directement dans Postgres** : inutile pour du batch analytique ; Postgres ne recevra
  que les marts agrégés (phase 2).
- **`df.sample()`** pour l'échantillon : tire des lignes et non des utilisateurs, non reproductible
  si le partitionnement change.
- **Anti-jointure sur la liste des adultes** : laisserait passer les orphelins.
