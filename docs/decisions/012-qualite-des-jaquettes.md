# ADR 012 — Qualité des jaquettes et titres affichés

**Date** : 2026-11-22 · **Statut** : accepté (plan validé par Royston le 2026-11-22)

## Contexte
Royston voulait de meilleures jaquettes, en pensant aux manhwas et webtoons de niche, et ajouter
MangaUpdates comme source. La mesure en base a changé le diagnostic :
- 100 % des mangas, manhwas et manhuas du catalogue (top 5 000 AniList) avaient une jaquette
  AniList ; les titres de niche sont **absents du catalogue**, pas sans jaquette ;
- 2 435 animes (dataset 2020) n'en avaient pas, et 15 affichaient l'image par défaut d'AniList ;
- toutes les jaquettes étaient en **230 × 322 px** : AniList renvoie sous le nom `large` son
  image moyenne, la grande s'appelle `extraLarge` (**460 × 643 px**, mesuré le 2026-11-22) ;
- les titres affichés étaient les romanisations (« Na Honjaman Level Up » au lieu de « Solo
  Leveling », « Shingeki no Kyojin » au lieu de « Attack on Titan »).

## Décisions

### a) Un lot « qualité » d'abord, MangaUpdates plus tard
Choix de Royston : MangaUpdates (rapprochement par titres, seuil de confiance, cas ambigus) et
l'élargissement du catalogue sont mis de côté. Sans élargissement, MangaUpdates ne remplirait
aujourd'hui aucune jaquette. Les faits vérifiés sur son API (recherche `POST /v1/series/search`,
titres associés seulement dans `GET /series/{id}`, pas de limite chiffrée, attribution
obligatoire, pas de drapeau adulte, domaine des images non documenté) sont gardés pour la suite.

### b) Les plus grandes images, jamais une URL devinée
Les requêtes AniList demandent `coverImage { extraLarge large color }` et gardent `extraLarge`.
Les jaquettes en base sont re-demandées à AniList par lots d'identifiants (aucune URL réécrite à
la main). `default.jpg` est traité comme « pas de jaquette ». Colonnes ajoutées à
`catalog.media` : `cover_source` (anilist, jikan, suggestion ; une jaquette a toujours une
origine, contrainte en base) et `cover_color` (couleur dominante AniList).

Priorités : une jaquette **validée par Royston** n'est jamais écrasée par une synchro ; Jikan ne
fait que compléter une jaquette absente (il ne remplace plus une grande image AniList).

### c) Titre anglais d'abord
Règle unique (`records.display_titles`, même logique dans Spark) : titre anglais s'il existe,
romaji en titre secondaire (toujours cherchable). S'ils ne diffèrent que par la ponctuation ou
les espaces (« Fullmetal Alchemist:Brotherhood »), l'original, mieux écrit, est gardé. Les
animes du dataset ont été mis à jour une fois en SQL (même règle, résultat identique au prochain
`make spark`) plutôt que de relancer Spark sur 109 M de lignes : 4 947 titres anglais, 1 646
doublons retirés.

### d) Jaquette de secours : une palette, pas des couleurs brutes
La couleur AniList est arbitraire : l'afficher casserait la palette et les contrastes vérifiés
(règle 13 de CLAUDE.md). Six tons sombres `jacket-*` sont ajoutés à DESIGN.md, contrastes
vérifiés par le test des tokens (ink ≥ 11,4:1, ink-2 ≥ 5,5:1). La teinte AniList choisit le ton
le plus proche ; sans couleur (ou grise), un hachage du titre, toujours le même pour une œuvre.

### e) « Proposer une jaquette » : modération, jamais de téléchargement
- `POST /media/{id}/cover-suggestions` : HTTPS, hôte **et** chemin dans une liste exacte
  (`settings.yaml`, mêmes domaines que les `remotePatterns` du front) ; ni identifiants, ni port,
  ni paramètres, ni `..` ; l'URL reconstruite doit être identique (pas d'encodage douteux).
- L'API **ne télécharge jamais** l'URL proposée : pas de SSRF possible. Rien ne s'affiche avant
  la validation de Royston ; ensuite l'optimiseur d'images de Next ne charge que ces domaines.
- Table `app.cover_suggestion` (migration 0003) : une même image une seule fois par personne et
  par œuvre, 10 propositions par jour, supprimée avec le compte, incluse dans l'export RGPD.
- Modération en ligne de commande (`make covers-review`, `covers-approve`, `covers-reject`) :
  pas de page d'administration web, donc pas de surface d'attaque en plus. La liste montre le
  pseudo, jamais l'email.
- **Écartés** : envoi de fichiers (stockage, contrôle du contenu des images) et téléchargement
  côté serveur pour vérifier l'image (SSRF, coût).

## Conséquences
- **Ordre de déploiement** (phase 11) : l'API lit `cover_color` et `cover_source`, créées par le
  schéma du pipeline (`schema_catalog.sql`, propriétaire du catalogue, ADR 003) et non par
  Alembic. Appliquer le schéma du pipeline (n'importe quelle tâche d'ingestion, ou `make spark`)
  **avant** de démarrer la nouvelle API, sinon les routes du catalogue répondent 500.
- `reports/covers_coverage.json` (`make covers-report`) : couverture par type, par source et par
  tranche de popularité (rangs MAL pour les animes, AniList pour les mangas : jamais mélangés).
- Tests : pipeline (titres, `extraLarge`, `default.jpg`, protection des jaquettes validées,
  rattrapage du schéma, rapport), backend (URL refusées, doublon, limite quotidienne, export,
  suppression, modération), front (ton de la jaquette, contrastes), E2E (proposition refusée puis
  acceptée).
