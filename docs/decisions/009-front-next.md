# ADR 009 — Front Next.js : relais d'API, rendu, garde-fous du design

**Date** : 2026-11-21 · **Statut** : accepté (plan validé par Royston le 2026-11-21)

## Contexte
Phase 8 (SPEC § 8 et § 10) : accueil, inscription et connexion, onboarding, « Ma liste ».
Stack imposée par CLAUDE.md : Next.js (App Router, TypeScript), Tailwind, shadcn/ui, TanStack
Query, Vitest, Playwright. Direction visuelle validée : `docs/DESIGN.md` (« Journal de bord »).
Version installée : **Next.js 16.4** (Turbopack, Cache Components, Partial Prefetching activés
par défaut), Tailwind 4.3, React 19.3, Node 24 LTS (installé dans WSL par nvm).

## Décisions

### a) Le navigateur ne parle qu'au front : relais `/api/*`
`next.config.ts` relaie `/api/:path*` vers l'API FastAPI (`API_URL`, jamais exposée au
navigateur). Front et API ont donc la **même origine** :
- le cookie de session (`httpOnly`, `SameSite=Lax`, ADR 008) part tout seul ; le JavaScript ne
  voit jamais le jeton ;
- pas de CORS à ouvrir ;
- le risque noté dans l'ADR 008 (front Vercel et API Cloud Run sur deux sites, cookie Lax non
  envoyé) disparaît par construction.

Les pages publiques rendues côté serveur appellent `API_URL` directement (sans cookie).

**Écarté** : appels directs du navigateur vers l'API avec `credentials: "include"` (CORS avec
cookies, et cookie tiers bloqué dès que les domaines diffèrent).

**Limite connue, mesurée le 2026-11-21** : le relais de Next transmet un `X-Forwarded-For` reçu
mais n'y ajoute pas l'IP du visiteur. Sans plateforme devant le front, l'API voit `127.0.0.1`
pour tout le monde, et un client peut fournir son propre en-tête. uvicorn s'y fiait par défaut
(requêtes venant de 127.0.0.1) : changer d'« IP » à chaque requête contournait la limite de
tentatives (revue de sécurité de la phase 8). **Décision** : l'API ignore `X-Forwarded-For`
partout (`--no-proxy-headers` dans `make api` et l'image Docker, `proxy_headers=False` dans l'API
de test ; un test le vérifie). La limite par IP devient de fait une limite globale tant que le
front relaie : moins fine, mais impossible à contourner ; la limite par email reste entière.
Phase 11 : un seul en-tête de confiance (IP réelle posée par la plateforme et relayée avec un
secret partagé, ou API derrière un équilibreur de charge dont elle seule accepte l'en-tête).

### b) Rendu : serveur pour le public, navigateur pour le compte
- **Accueil** : Server Component, chaque section dans son propre `<Suspense>` (Cache Components
  : la coquille statique s'affiche tout de suite, les données arrivent en streaming). Une API
  lente ou en panne ne bloque que sa section ; la section « Saison » abandonne au bout de 4 s
  (Jikan en panne : l'API mettait jusqu'à 18 s à répondre).
- **Pages de compte** (onboarding, Ma liste, compte) : Client Components avec TanStack Query,
  qui lisent l'API avec le cookie. Après une action, « Ma liste » met à jour sa page en place
  (la ligne ne saute pas sous le pointeur) ; les autres onglets sont rechargés à l'ouverture.
- **`proxy.ts`** (l'ancien « middleware », renommé dans Next 16) : contrôle **optimiste** des
  pages de compte (présence du cookie → sinon `/connexion?suivant=…`). La vraie vérification
  reste l'API. Le paramètre `suivant` n'accepte que des chemins internes (redirection ouverte).

**Piège rencontré (attrapé par l'E2E en build de production)** : le préchargement des liens
(Partial Prefetching) avait mis en cache, quand on était visiteur, la redirection de « Ma liste »
vers la connexion ; après inscription, le routeur la rejouait. Corrigé : pas de préchargement des
liens vers les pages de compte, et `router.refresh()` à chaque changement de session.

### c) Le code ne peut pas s'écarter de DESIGN.md
- `globals.css` déclare les tokens de `DESIGN.md` en `@theme` et **supprime les valeurs par défaut
  de Tailwind** (`--color-*: initial`, etc.) : `bg-red-500` ou `rounded-xl` ne génèrent rien.
- Un test Vitest (`src/test/design-tokens.test.ts`) :
  - recalcule les 21 contrastes autorisés à partir de `globals.css` (un token changé sans
    revérification casse la CI) ;
  - refuse toute couleur hexadécimale, `rgb()`, police ou valeur Tailwind arbitraire dans `src/`
    (hors `globals.css` et `lib/tokens.ts`) ;
  - refuse les pas d'espacement et les rayons absents de l'échelle (une classe hors tokens ne
    casse pas le build, Tailwind ne génère juste rien : sans ce test, l'écart passerait
    inaperçu). Il a déjà bloqué deux écarts pendant la phase (marges de grille et zone de
    sécurité mobile absentes de l'échelle, ajoutées à DESIGN.md).
- Les composants façon shadcn/ui (bouton, champ, onglets) sont écrits dans le dépôt, sur Radix
  Tabs pour l'accessibilité des onglets, avec les seuls tokens.

### d) Sécurité et vie privée
- CSP stricte sans domaine tiers (`default-src 'self'`, `frame-ancestors 'none'`, pas
  d'`unsafe-eval` en production) ; `'unsafe-inline'` pour les scripts, car Next injecte des
  scripts en ligne et les nonces imposeraient un rendu dynamique de chaque page.
- Polices auto-hébergées par `next/font` (téléchargées au build) ; couvertures servies par
  l'optimiseur d'images de Next (le visiteur ne contacte ni Google ni les CDN d'images).
- Couvertures acceptées seulement depuis le CDN d'AniList (préfixe imposé au chargement en base)
  et de MyAnimeList (`remotePatterns`).

### e) Couvertures des animes
Le dataset 2020 n'a pas d'images et Jikan est en panne depuis la phase 6. Nouvelle tâche
`anime_covers` du DAG `anilist_catalog_sync` (et `make covers`) : couvertures manquantes
récupérées sur AniList **par idMal** (aucun identifiant deviné), par lots de 50, seulement là où
`cover_url` est vide. 1re exécution (2026-11-21) : **13 779 couvertures sur 16 214 animes**,
2 435 restent sans image (inconnues d'AniList) et gardent la jaquette de secours de DESIGN.md
(`reports/exploration_2026-11-20.json`, `anime_covers_first_run`).

### f) Tests de bout en bout réels
`backend/scripts/e2e_api.py` crée une base dédiée `tsuzuku_e2e` (schémas du pipeline +
migrations Alembic), un mini catalogue fictif et de mini modèles (mêmes helpers que les tests
backend), simule Jikan en panne, et lance la vraie API (port 8001). Playwright lance le front en
build de production (port 3001) et parcourt inscription → onboarding → recos → ajout à la liste
→ +1 épisode, avec axe-core (WCAG 2.2 AA) et un contrôle d'absence de débordement à 375 et
1440 px sur chaque écran. Les limites de débit sont élargies dans les réglages de test : tous les
tests passent par la même IP (voir a).

### g) Ajouts au périmètre de la phase 8
- `GET /media/popular?kind=…` (accueil, onboarding). Une popularité de 0 veut dire « non classé »
  chez MAL : traitée comme inconnue (elle faisait passer des titres non sortis en tête de la
  recherche).
- `/me/list` renvoie le nombre d'œuvres par statut (onglets « En cours · 3 »).
- `POST /me/list/{media_id}` : **création seule** (409 si l'œuvre est déjà dans la liste). Revue de
  la phase 8 : « Ajouter à ma liste » depuis une reco passait par le PUT, qui remplace l'entrée
  entière ; un bouton resté affiché après une navigation pouvait remettre à zéro progression et
  note. Le PUT reste pour les modifications (+1 ép., j'ai lâché), toujours construites à partir
  de l'entrée complète.
- `/media/search` accepte plusieurs `kind` (onglet « Manhwas et manhuas » de l'onboarding).
- Page « Compte » (déconnexion, export, suppression) et page de confidentialité : la SPEC les
  prévoit (§ 7-8) sans les attribuer à une phase.

## Conséquences
- 80 tests Vitest (logique, cache de « Ma liste », garde-fous du design), 4 parcours Playwright
  (axe-core avec les règles WCAG 2.2 AA et les bonnes pratiques, dont l'ordre des titres), CI
  `ci-frontend` (lint, types, tests, build, `npm audit`, E2E avec Postgres et captures en
  artefacts).
- Revues de la phase 8 (sécurité, React/accessibilité) : une redirection ouverte par tabulation
  (`?suivant=/%09/site`), l'écrasement d'entrée ci-dessus, un saut de niveau de titre, et des
  points d'accessibilité (focus perdu après une action, erreurs non annoncées) corrigés et
  couverts par des tests.
- La fiche œuvre, « Pour toi » en page entière et le profil public arrivent en phase 9 ; les
  jaquettes ne sont donc pas encore cliquables.
