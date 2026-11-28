# Tableau de bord Power BI — guide de construction

Phase 13 (SPEC § 11, [ADR 016](../docs/decisions/016-power-bi.md)). Le dépôt fournit les vues SQL
(schéma `bi`), les mesures ([measures.dax](measures.dax)) et le thème ([theme.json](theme.json)).
Le fichier `.pbix` se construit à la main dans Power BI Desktop (Windows), en suivant ce guide.

Compter environ 2 à 3 heures pour les 6 pages.

## 0. Avant de commencer
- **Power BI Desktop** (gratuit, Microsoft Store), sous Windows.
- **Le rôle lecture seule `tsuzuku_bi`** existe sur Neon (`make bi-role`, voir
  [docs/deploy.md](../docs/deploy.md) § Power BI). Son mot de passe est `BI_DB_PASSWORD` dans le
  `.env` du dépôt : ne jamais le copier ailleurs que dans la fenêtre d'identifiants de Power BI.
- **Les chiffres de référence** sont dans [reports/powerbi_summary.json](../reports/powerbi_summary.json)
  (`make bi-report`). Ils servent à vérifier le tableau de bord à la fin (§ 6).

## 1. Connexion à Neon (mode Import)
1. Accueil → **Obtenir des données** → **Base de données PostgreSQL**.
2. **Serveur** : l'hôte Neon de la branche `production` (console Neon → *Connect* → champ *host*,
   de la forme `ep-…​.eu-central-1.aws.neon.tech`). **Base de données** : le nom affiché au même
   endroit.
3. **Mode de connectivité des données : Importer**, jamais DirectQuery. En DirectQuery, chaque
   clic interrogerait Neon et le garderait éveillé, donc du temps de calcul facturé (ADR 016).
4. Identifiants : onglet **Base de données**, utilisateur `tsuzuku_bi`, mot de passe
   `BI_DB_PASSWORD`. Laisser **chiffrer la connexion** coché : Neon exige SSL.
5. Si Power BI répond que « l'ID de l'endpoint n'est pas spécifié » : le connecteur n'envoie pas
   le nom d'hôte (SNI). Mettre dans le champ mot de passe `endpoint=<id>$<mot de passe>`, où
   `<id>` est le début de l'hôte (`ep-…`), comme l'explique la documentation Neon (*Connection
   errors*, « endpoint ID is not specified »).
6. Repli si Neon reste inaccessible : la base locale (`make up`), serveur `localhost:5433`, avec
   les mêmes vues et les mêmes marts. Seule la page 6 (activité réelle des comptes) n'a de sens
   qu'en production.

## 2. Tables à importer
Dans le navigateur, cocher les **15 vues du schéma `bi`**, puis **Charger** :

| Vue | Page | Contenu |
|---|---|---|
| `anime_drop` | 1, 2 | un anime avec données de drop par ligne : lâchés, terminés, taux, épisode critique |
| `anime_genre`, `anime_studio` | 3 | liaisons anime ↔ genres, anime ↔ studios |
| `anime_segment`, `segment_retention` | 3 | Isekai / Shounen / Autres (un anime peut être dans deux segments) |
| `drop_curve` | 2 | part des drops à chaque épisode, marqueurs critique et non-retour |
| `retention_by_genre`, `retention_by_studio` | 3 | rétention calculée par Spark (mart) |
| `daily_stats` | 4 | statistiques quotidiennes Jikan (vide tant que Jikan est en panne) |
| `model_metrics` | 5 | métriques des modèles, une ligne par (entraînement, métrique) |
| `app_totals`, `app_signups_weekly`, `app_status_counts`, `app_top_added`, `app_declared_drops` | 6 | activité des comptes, agrégée et anonyme |

**Renommer chaque table** sans le préfixe : `bi anime_drop` → `anime_drop`, etc. (clic droit →
Renommer, dans le volet Données). Les mesures de `measures.dax` utilisent ces noms courts.

## 3. Modèle (vue Modèle)
Relations, toutes **un-à-plusieurs**, filtrage **unidirectionnel** (de `anime_drop` vers les
autres) :

| De (côté 1) | Vers (côté plusieurs) |
|---|---|
| `anime_drop[media_id]` | `drop_curve[media_id]` |
| `anime_drop[media_id]` | `anime_genre[media_id]` |
| `anime_drop[media_id]` | `anime_studio[media_id]` |
| `anime_drop[media_id]` | `anime_segment[media_id]` |

Les autres tables restent **sans relation** : elles sont déjà agrégées. Supprimer toute relation
détectée automatiquement qui ne figure pas ici (Power BI en invente parfois sur `media_id`).

## 4. Mesures
1. Vue **Requête DAX** (icône à gauche) → coller tout [measures.dax](measures.dax).
2. Cliquer **Mettre à jour le modèle avec les modifications** (lien au-dessus de `DEFINE`). Les
   mesures apparaissent dans leurs tables.
   Si la version de Power BI ne propose pas ce lien, créer chaque mesure à la main : clic droit
   sur la table → **Nouvelle mesure** → coller le texte après `MEASURE table[`…`] =`.
3. Formats (Outils de mesure → Format) :
   - pourcentage avec 1 décimale : `Taux de drop`, `Taux de drop (classé)`,
     `Taux de complétion (classé)`, `Taux de drop du segment`, `du studio`, `du genre`,
     `Part des drops`, `Part cumulée` ;
   - nombre entier avec séparateur : `Lâchés`, `Terminés`, `Lâchés + terminés`, `Animes`,
     `Membres`, `Comptes` ;
   - 3 décimales : `ROC AUC (drop)`, `PR AUC (drop)`, `NDCG@10 (ALS)`, `Précision@10 (ALS)`.

## 5. Thème et pages
**Affichage → Thèmes → Parcourir les thèmes** → [theme.json](theme.json). Il reprend les couleurs
du site ([docs/DESIGN.md](../docs/DESIGN.md)) : fond encre, texte clair, barres grises. Le corail
est réservé aux **signaux** (épisode critique), le bleu aux « bons signes » (point de non-retour).
Page au format 16:9. En haut de chaque page, une zone de texte : le titre de la page et une
phrase qui dit ce qu'on y lit.

### Page 1 · Vue d'ensemble
- **3 cartes** : `Taux de drop`, `Animes`, `Lâchés + terminés`.
- **Barres horizontales « Les plus lâchés »** : axe `anime_drop[title]`, valeur
  `Taux de drop (classé)`. Volet Filtres → `title` → **N premiers : 10**, par `Taux de drop (classé)`.
- **Barres horizontales « Les plus tenus »** : même visuel avec `Taux de complétion (classé)`.
- Sous les deux classements, en petit : « Classés : animes avec au moins 1 000 statuts lâché ou
  terminé ». Le seuil est la mesure `Seuil de volume`, à changer à un seul endroit.

### Page 2 · Courbes de drop
- **Segment** (slicer) sur `anime_drop[title]`, sélection unique, avec recherche.
- **Graphique en courbes et histogramme groupé** : axe X `drop_curve[episode]`, colonnes
  `Part des drops`, ligne `Part cumulée`. Couleur des colonnes : Mise en forme → Colonnes →
  **fx** → *Valeur du champ* → `Couleur de barre`.
- **Cartes** : `Épisode critique`, `Point de non-retour` ; **carte texte** : `Phrase épisode critique`.
- **Légende écrite** sous le graphique : « Corail : épisode critique · Bleu : point de non-retour ».
  La couleur ne suffit jamais seule (DESIGN.md § 1.2).
- L'épisode 0 = lâché avant de commencer.

### Page 3 · Studios et genres
- **Barres « Isekai, Shounen, les autres »** : axe `segment_retention[segment]`, valeur
  `Taux de drop du segment` ; info-bulle : `nb_anime`, `Écart au taux global (points)`.
- Note sous le visuel : « Isekai = tag AniList, Shounen = genre MyAnimeList ; un anime peut être
  dans les deux. Animes avec données de drop uniquement. »
- **Barres « Studios »** : axe `retention_by_studio[studio]`, valeur `Taux de drop du studio`,
  filtre **N premiers : 15** par `nb_anime` (les studios les plus présents), tri par taux.
- **Barres « Genres »** : axe `retention_by_genre[genre]`, valeur `Taux de drop du genre`, trié.

### Page 4 · Saison en cours
- **Carte texte** : `Message saison vide` (affichée seulement sans données).
- **Courbes** : axe `daily_stats[snapshot_date]`, valeur `Membres`, légende `daily_stats[title]` ;
  filtre de page `in_season = Vrai`.
- **Tableau** : `title`, `Membres`, `Membres gagnés sur 7 jours`, `Lâchés (MAL)`.

### Page 5 · Modèles
- **Cartes** : `ROC AUC (drop)`, `PR AUC (drop)`, `Prévalence (drop)` ; `NDCG@10 (ALS)`,
  `Précision@10 (ALS)`.
- Phrase : « La PR AUC se lit face à la prévalence (part des drops dans le jeu de test) : c'est
  le score d'un modèle qui répondrait au hasard. »
- **Tableau** : `model_metrics[model_name]`, `model_metrics[metric]`, `Valeur` (dernier
  entraînement de chaque modèle).
- Facultatif : **courbes** `created_at` × `value`, filtrées sur `metric = test.roc_auc`, pour
  l'historique des entraînements du modèle de drop.

### Page 6 · Activité Tsuzuku
- **Carte texte** : `Message anonymat`. Tant qu'il y a moins de 5 comptes, les vues ne renvoient
  rien, et c'est voulu : aucun chiffre ne doit décrire une personne (ADR 016).
- **Cartes** : `Comptes`, `Comptes passés par l'onboarding`, `Entrées (statuts affichés)`,
  `Drops déclarés`. Il n'y a pas de « total des entrées » : il permettrait de retrouver, par
  soustraction, un statut masqué (ADR 016).
- **Barres** : `app_status_counts[status]` × `Entrées (statuts affichés)`.
- **Histogramme** : `app_signups_weekly[week]` × `nb_signups`.
- **Barres** : `app_top_added[title]` × `Comptes qui l'ont ajouté`, N premiers : 10.
- **Tableau** : `app_declared_drops` : `title`, `nb_accounts`, `median_dropped_at`,
  `critical_episode`, `Écart au critique MAL (épisodes)`. On y compare où les membres de Tsuzuku
  lâchent et l'épisode critique mesuré sur MyAnimeList.

## 6. Vérifier, enregistrer, partager
1. **Accueil → Actualiser** (Neon se réveille en quelques secondes).
2. **Vérifier** face à [reports/powerbi_summary.json](../reports/powerbi_summary.json) :
   - la carte `Taux de drop` (page 1) = `global_drop_rate` ;
   - `Animes` = `anime_with_drop_data` ;
   - les trois taux de la page 3 = `segments[].drop_rate`.
   Un écart signale une relation ou une mesure mal posée (§ 3, § 4).
3. **Enregistrer** sous `powerbi/tsuzuku.pbix`. Le fichier ne contient aucun mot de passe : Power
   BI les garde dans le gestionnaire d'identifiants de Windows. Il contient les données importées,
   qui sont toutes agrégées.
4. **Captures** dans `powerbi/screenshots/` (`01-vue-ensemble.png` … `06-activite.png`) : elles
   iront dans le README (phase 15).

## Limites connues
- Données d'interactions MyAnimeList arrêtées en 2020 : les animes récents n'ont pas de courbe
  de drop.
- Page 4 vide tant que l'API Jikan est en panne (depuis la phase 6).
- Page 6 vide sous 5 comptes (anonymat).
- `retention_by_genre` et `retention_by_studio` viennent de Spark (tous les animes avec au moins un
  statut lâché ou terminé, seuils de `settings.yaml`) ; les segments de la page 3 portent sur les
  animes de `anime_drop`. Ce ne sont pas exactement les mêmes populations : ne pas comparer un
  segment à un genre au dixième de point près.
