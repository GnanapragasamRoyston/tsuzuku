# ADR 011 — Front, partie 2 : fiche œuvre, Pour toi, profil public

**Date** : 2026-11-22 · **Statut** : accepté (plan validé par Royston le 2026-11-22)

## Contexte
Phase 9 (SPEC § 8 et § 10) : fiche œuvre avec risque de drop et courbe, page « Pour toi »,
profil public. C'est la promesse de Tsuzuku rendue visible : prévenir avant le drop. La phase 8
avait laissé les jaquettes non cliquables et reporté `/users/{pseudo}` (ADR 008 § i).

## Décisions

### a) Profil public : opt-in, une seule 404
- Colonne `app.users.profile_public`, **fausse par défaut** (migration 0002 ; les comptes
  existants restent privés). Réglage par `PATCH /me` (booléen strict, aucun autre champ) et une
  case dans « Compte ». Choix de Royston : un profil montre la liste notée et le taux de drop ;
  l'exposer sans consentement explicite irait contre la minimisation (RGPD).
- `GET /users/{pseudo}` répond **la même 404** pour un pseudo inconnu, mal formé ou privé : on
  ne peut pas tester si un compte existe (énumération). Le front affiche la page introuvable.
- Contenu : agrégats (compteurs, épisodes vus, taux de drop), 5 genres, 10 dernières notes, mois
  d'inscription. Jamais l'email, les critiques ni les dates d'activité. `Cache-Control:
  no-store` : un profil refermé disparaît tout de suite.
- Taux de drop perso caché sous 3 œuvres terminées ou lâchées (`settings.yaml`) : « 100 % » après
  un seul drop ne dirait rien. Choix produit, pas une mesure.
- **Écartés** (choix de Royston) : avatar (upload d'image = surface d'attaque et stockage ; un
  monogramme le remplace) et abonnements entre profils (`follow`, optionnel dans la SPEC).

### b) Fiche œuvre : serveur pour le catalogue, îlots client pour le compte
- Server Component (`/media/{id}` sans cookie, `cache()` partagé entre `generateMetadata` et la
  page), ordre imposé par DESIGN.md § 4. L'ajout, la note et le risque de drop dépendent du
  compte : îlots client (`account-panels.tsx`) avec TanStack Query. Nouvelle route
  `GET /me/list/{media_id}` pour savoir si l'œuvre est dans la liste sans paginer toute la liste.
- La note passe par le PUT existant, construit sur l'entrée complète (`toUpdate`) : jamais de
  progression ou de critique effacée par accident (même règle qu'en phase 8).
- `/media/{id}` renvoie aussi le dernier relevé Jikan (`latest_stats`), vide tant que Jikan est
  en panne : la section « Communauté » le dit au lieu d'inventer.

### c) Courbe de drop sans bibliothèque
Barres en CSS (`components/drop-curve.tsx`), logique pure et testée à part (`lib/drop-curve.ts` :
trous comblés, tranches de 5 au-delà de 26 épisodes, épisode 0 toujours seul, repère critique
prioritaire). **Écartés** : Recharts, Chart.js ou D3 — du JavaScript envoyé au navigateur pour
une seule rangée de barres, et un rendu à adapter aux tokens. Accessibilité : `role="img"` avec un
résumé, plus un tableau `sr-only` de toutes les valeurs.

### d) Next 16 : en-tête sous Suspense
Les premières routes dynamiques (`/oeuvre/[id]`, `/profil/[pseudo]`) ont fait échouer le build :
avec Cache Components, un `usePathname()` hors `<Suspense>` bloque le pré-rendu. L'en-tête du
layout est donc dans un `<Suspense>` dont le repli est une barre vide de même hauteur (pas de saut).

## Conséquences
- Backend : 175 tests (migration, `PATCH /me`, entrée seule, profil public / privé / inconnu,
  isolation entre comptes, absence d'email, relevé Jikan). Front : 88 tests Vitest ; 5 parcours
  Playwright, dont reco → fiche → note → profil rendu public → Pour toi, avec axe-core (WCAG 2.2 AA)
  et contrôle de débordement à 375 et 1440 px sur chaque nouvel écran.
- La revue de code a relevé 4 défauts importants, corrigés : Compte inaccessible sur mobile une
  fois le profil ouvert (l'entrée « Profil » mène désormais à Compte), risque de drop non rechargé
  après une note, lien vers le profil affiché avant l'enregistrement, courbe illisible au-delà de
  quelques centaines d'épisodes (tranches qui grandissent : 26 barres au plus).
- Le parcours E2E a attrapé deux vrais défauts : la case « profil public » attendait le réseau
  pour se cocher (rendue optimiste, avec retour arrière en cas d'échec), et un pseudo sans espace
  élargissait la page en mobile (coupure autorisée).
- La base E2E reçoit une courbe de drop **fictive** par anime (jamais montrée comme réelle).
- Reste pour plus tard : recos manga/manhwa (phase 10, la page Pour toi le dit), rappel de
  l'épisode critique dans les lignes de Ma liste (§ 5.2, facultatif).
