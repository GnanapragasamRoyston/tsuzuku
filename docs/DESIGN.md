# DESIGN.md — Tsuzuku, direction « Journal de bord »

Source de vérité de tout le front (phases 8 et suivantes). Le code n'utilise que les tokens de la
section 8 : une couleur, une police, un espacement ou un rayon absent d'ici n'existe pas.
**Statut : validé par Royston le 2026-11-21.** Direction choisie parmi deux propositions (maquette :
<https://claude.ai/artifact/BegS6PrFj1rhKj7ebxGDH8>, planches « A · Accueil » et « A · Fiche »).

**Intention.** Tsuzuku se lit comme le carnet d'un fan : grands titres en serif, filets fins,
sections numérotées comme les pages d'un magazine. Les chiffres qui comptent (risque de drop,
notes, épisodes) sont composés comme des titres, pour se lire d'un coup d'œil. L'interface reste
discrète : la couleur signale, elle ne décore pas.

**Retours intégrés après la maquette (2026-11-21)** :
- *« Trop boîte et pointu »* : rayons adoucis (4, 6 et 10 px au lieu de 0 à 4 px) et moins de
  cadres. Les blocs sont séparés par l'espace et des filets, rarement par des boîtes fermées.
  **Écart assumé** avec la règle « 0 à 4 px maximum » de `PROMPT_DESIGN.md`, à la demande de
  Royston.
- *« Trop de corail »* : le corail a désormais un budget strict (§ 1.3). Les grands chiffres
  éditoriaux, les numéros de section et les liens sont en encre, plus en corail.

---

## 1. Palette

### 1.1 Couleurs

| Token | Hex | Rôle |
|---|---|---|
| `bg` | `#0D0E13` | fond principal (noir encre bleuté) |
| `surface` | `#15161D` | bandeaux, champs, panneaux |
| `raised` | `#1C1D26` | éléments posés sur une surface (menu ouvert, ligne survolée) |
| `hover` | `#23242F` | survol d'un élément interactif sur `surface` |
| `line` | `#2A2B36` | filets de séparation (décoratifs) |
| `line-strong` | `#707282` | bord des champs, des boutons secondaires, des cases (éléments d'interface) |
| `ink` | `#ECEAE4` | texte principal, grands chiffres, filet de titre de section |
| `ink-2` | `#A6A4A0` | texte secondaire, métadonnées, placeholders |
| `disabled` | `#5C5B59` | texte et bords désactivés (exemptés de contraste par WCAG) |
| `accent` | `#FF6B57` | corail du logo : **signal** uniquement (§ 1.3) |
| `accent-hover` | `#FF8573` | survol d'un bouton corail |
| `on-accent` | `#14142B` | texte posé sur le corail (bleu nuit du logo) |
| `good` | `#7DB4F0` | « bon signe » : risque faible, point de non-retour |
| `chart` | `#6E7182` | barres ordinaires de la courbe de drop |
| `jacket-wine` · `jacket-umber` · `jacket-moss` | `#3A1F2A` · `#3A2A1C` · `#26301F` | fond de la jaquette de secours (§ 5.1) |
| `jacket-teal` · `jacket-indigo` · `jacket-plum` | `#1A2F31` · `#1F2440` · `#2F2140` | fond de la jaquette de secours (§ 5.1) |

Bleu et corail plutôt que vert et rouge : ils restent distincts pour les daltoniens les plus
courants (deutéranopie, protanopie) et diffèrent aussi en luminosité.

### 1.2 Contrastes vérifiés (WCAG 2.2 AA)

Calculés avec la formule de luminance relative de WCAG (script : 26 paires le 2026-11-21, 38 avec les jaquettes le 2026-11-22). Seuils :
4,5:1 pour le texte, 3:1 pour le texte ≥ 24 px (ou ≥ 18,66 px gras) et les éléments d'interface.

| Premier plan | Fond | Ratio | Usage autorisé |
|---|---|---|---|
| `ink` | `bg` / `surface` / `raised` / `hover` | 16,02 / 14,99 / 13,93 / 12,79 | tout texte |
| `ink-2` | `bg` / `surface` / `raised` / `hover` | 7,75 / 7,25 / 6,73 / 6,18 | tout texte |
| `accent` | `bg` / `surface` / `raised` | 6,88 / 6,43 / 5,98 | texte de signal, marqueurs |
| `on-accent` | `accent` / `accent-hover` | 6,43 / 7,60 | libellé des boutons corail |
| `good` | `bg` / `surface` / `raised` | 8,87 / 8,30 / 7,71 | texte et marqueurs « bon signe » |
| `line-strong` | `bg` / `surface` / `raised` / `hover` | 4,06 / 3,79 / 3,53 / 3,24 | bords de champs et de contrôles (≥ 3:1) |
| `chart` | `bg` / `surface` | 3,99 / 3,73 | barres de données (≥ 3:1) |
| `ink` | les 6 `jacket-*` | 11,43 à 12,61 | titre de la jaquette de secours |
| `ink-2` | les 6 `jacket-*` | 5,52 à 6,09 | type et année de la jaquette de secours |

**Combinaisons interdites** :
- `ink` sur `accent` (2,33) : jamais de texte blanc sur le corail, toujours `on-accent` ;
- `accent` contre `chart` (1,72) et `good` contre `chart` (2,22) : la barre critique et la barre
  de non-retour ne se distinguent PAS par la couleur seule. Elles portent toujours un libellé
  (§ 5.6) ;
- `line` (1,37) ne délimite jamais un élément interactif : seulement des séparations ;
- `disabled` (2,84) uniquement pour un élément désactivé, jamais pour du texte à lire.

### 1.3 Budget du corail

Le corail sert à **signaler**. Sur un écran, il n'apparaît que pour :
1. **l'action principale**, une seule par écran (« Ajouter à ma liste », « Créer mon journal ») ;
2. **l'élément actif** de la navigation : un trait de 2 px sous l'onglet, pas un fond ;
3. **le risque de drop « à risque »** : le libellé et son marqueur. Le chiffre, lui, reste en
   `ink` ;
4. **l'épisode critique** sur la courbe ;
5. **les erreurs** (message de champ, échec d'enregistrement).

Jamais en corail : titres, mots mis en valeur, numéros de section, grands chiffres éditoriaux,
liens, survols, icônes, bordures de panneaux, fonds de section. Les actions secondaires sont en
contour `line-strong`.

Contrôle : si plus de **trois** zones corail sont visibles à la fois dans une fenêtre de 1440 px,
l'écran est revu.

### 1.4 Logo

Fichiers fournis par Royston, rangés dans `docs/design/brand/` (sources) et copiés dans
`frontend/public/brand/` (servis) à la création du front :

| Fichier | Usage |
|---|---|
| `tsuzuku-logo-dark.svg` | en-tête du site (fond sombre, mot en `#F2F2FA`), hauteur 40 à 48 px |
| `tsuzuku-logo-light.svg` | documents sur fond clair (README, export) |
| `tsuzuku-logo-dark-bg.svg/.png`, `tsuzuku-logo-light-bg.svg/.png` | aperçus de partage (Open Graph), captures |
| `tsuzuku-icon.svg` | favicon, en-tête mobile |
| `tsuzuku-icon-180.png` | `apple-touch-icon` |
| `tsuzuku-icon-192.png`, `tsuzuku-icon-512.png` | manifeste web (icônes d'application) |

Le mot « tsuzuku » n'est jamais recomposé dans une police du site : on utilise toujours le
fichier. Le carré corail du logo est la seule surface corail pleine autorisée hors boutons ; on
ne le recolore pas et on ne le déforme pas. Il n'entre pas dans le budget du corail (§ 1.3).

---

## 2. Typographie

Deux familles Google Fonts, chargées par `next/font/google` (auto-hébergées, sans requête vers
Google côté visiteur, donc sans traceur tiers) :

- **Fraunces** (serif éditoriale variable, axes `opsz` et `wght`) : titres, grands chiffres,
  numéros de section, notes.
- **Source Sans 3** (sans-serif humaniste d'Adobe, très lisible en petite taille, chiffres
  tabulaires disponibles) : texte, interface, formulaires, métadonnées.

### 2.1 Échelle

Rem calculés sur 16 px. Les tailles `display` et `figure` varient de façon fluide entre 375 et
1440 px (`clamp`).

| Token | Taille | Interligne | Police, graisse | Usage |
|---|---|---|---|---|
| `figure` | clamp(4.5rem → 7.5rem) | 0.9 | Fraunces 800 | LE chiffre d'un écran (risque de drop, stat d'affiche) |
| `display` | clamp(2.75rem → 4.75rem) | 1.02 | Fraunces 800, `letter-spacing: -0.02em` | titre d'accueil, titre d'une fiche |
| `h1` | 2.75rem (44) | 1.1 | Fraunces 700 | titre de page (Ma liste, Pour toi) |
| `h2` | 1.875rem (30) | 1.2 | Fraunces 600 | titre de section |
| `h3` | 1.5rem (24) | 1.25 | Fraunces 600 | sous-section, stat moyenne |
| `lead` | 1.1875rem (19) | 1.5 | Source Sans 3 400 | chapeau |
| `body` | 1.0625rem (17) | 1.55 | Source Sans 3 400 | texte courant |
| `ui` | 1rem (16) | 1.4 | Source Sans 3 600 | boutons, onglets, champs |
| `small` | 0.875rem (14) | 1.45 | Source Sans 3 400 | aide, légendes |
| `meta` | 0.8125rem (13) | 1.4 | Source Sans 3 600, capitales, `letter-spacing: 0.08em` | métadonnées (« TV · 12 ÉP. · 2014 ») |

Pas de texte sous 13 px. Pas d'italique en dehors de Fraunces (titres d'œuvre cités dans une
phrase : `<cite>` en Fraunces italique).

### 2.2 Règle des chiffres

- **Chiffre d'écran** (risque de drop, stat d'affiche) : Fraunces 800, `figure`, chiffres
  alignés et tabulaires (`font-variant-numeric: lining-nums tabular-nums`), couleur `ink`.
  Toujours accompagné d'un libellé en texte (« À risque », « Faible »).
- **Notes** : `8/10` en Fraunces 600 ; le « /10 » en `ink-2`, à 60 % de la taille.
- **Progression et compteurs dans les listes** : Source Sans 3 600 tabulaire
  (`tabular-nums`) : les colonnes « 7 / 24 » restent alignées d'une ligne à l'autre.
- Format français : espace fine insécable pour les milliers (`145 908`), virgule décimale
  (`2,8 %`), espace insécable avant `%`. Fait par `Intl.NumberFormat("fr-FR")`, jamais à la main.

---

## 3. Grille et rythme

### 3.1 Grille

| Largeur | Colonnes | Gouttière | Marge | Contenu max |
|---|---|---|---|---|
| mobile (< 768 px) | 4 | 16 px | 20 px | — |
| tablette (768–1023 px) | 8 | 24 px | 32 px | — |
| desktop (≥ 1024 px) | 12 | 24 px | 40 px | 1240 px, centré |

Breakpoints Tailwind : `md` = 768 px, `lg` = 1024 px, `xl` = 1280 px. On conçoit à 375 px puis on
élargit (mobile d'abord).

### 3.2 Espacements

Échelle fixe en multiples de 4 px, **aucune autre valeur** :

`0 · 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 · 128` (tokens `0`, `1`, `2`, `3`, `4`, `6`, `8`,
`12`, `16`, `24`, `32`).

Rythme vertical : 64 px entre sections sur desktop, 48 px sur mobile ; 96 px sous le titre
d'accueil. Dans un composant : 8 à 16 px.

**Marges de grille** (§ 3.1) : `5` = 20 px (mobile) et `10` = 40 px (desktop), plus `safe` =
zone de sécurité du bas d'écran sous la barre de navigation mobile, et `nav` = hauteur de cette
barre (64 px + zone de sécurité), pour poser un élément fixé en bas juste au-dessus. `9` = 36 px
(logo mobile).

**Tailles de composants** (ajoutées au début de la phase 8, mêmes multiples de 4) : `11` = 44 px
(cible tactile minimale), `18` = 72 px (barre de navigation desktop), `22` = 88 px (jaquette dans
une ligne de liste), `40` = 160 px (jaquette en rangée). Largeurs maximales : `page` = 1240 px,
`prose` = 560 px (texte courant), `form` = 480 px (formulaires).

### 3.3 Rayons

| Token | Valeur | Usage |
|---|---|---|
| `none` | 0 | filets, courbe de drop, tableaux |
| `sm` | 4 px | barres de progression, étiquettes, cases à cocher |
| `md` | 6 px | boutons, champs, jaquettes, onglets |
| `lg` | 10 px | panneaux, menus déroulants, boîtes de dialogue |
| `full` | 9999 px | avatar et pastille de focus de l'icône seulement |

### 3.4 Profondeur

Pas d'ombre portée diffuse. La hiérarchie vient du fond (`bg` → `surface` → `raised`) et des
filets. Seule exception : un menu ou un dialogue ouvert reçoit
`0 8px 24px rgb(0 0 0 / 0.45)`, pour se détacher de ce qu'il recouvre.

---

## 4. Éditorial ou stable

| Écran | Mode | Ce qui peut varier |
|---|---|---|
| Accueil | éditorial | alternance de sections : titre à gauche avec grand vide à droite, rangée de jaquettes, grille asymétrique (une jaquette double + quatre simples), bandeau d'affiche pleine largeur avec un chiffre `figure` |
| Pour toi | éditorial | une reco « à la une » en grand, puis des rangées ; sections numérotées N° 01, N° 02 |
| Profil public | éditorial | grands chiffres de stats, genres favoris en liste typographique |
| Ma liste | **stable** | toujours : onglets de statut → liste de lignes identiques ; rien ne bouge d'une visite à l'autre |
| Fiche œuvre | **stable** | toujours dans cet ordre : en-tête (jaquette, titre, méta, ajout) → risque de drop → courbe → communauté |
| Onboarding | **stable** | filtres → grille régulière → barre de progression fixe en bas |
| Formulaires (inscription, connexion, paramètres) | **stable** | une colonne, 480 px max, libellés au-dessus des champs |

Un écran stable n'utilise ni asymétrie, ni chiffre `figure` décoratif, ni bandeau d'affiche.

---

## 5. Composants signature

États communs à tous les éléments interactifs :

| État | Rendu |
|---|---|
| repos | voir chaque composant |
| survol | changement de couleur de fond (`surface` → `hover`) ou de texte (`ink-2` → `ink`), ou soulignement ; jamais d'agrandissement ni d'ombre |
| focus clavier | contour `2px solid ink`, décalé de 2 px (`outline-offset: 2px`), rayon du composant ; visible seulement au clavier (`:focus-visible`) |
| désactivé | texte et bord `disabled`, fond inchangé, `cursor: not-allowed`, attribut `disabled` (ou `aria-disabled` + raison en texte à côté) |
| chargement | squelette : bloc `surface` à la forme du contenu, sans texte ; bouton : libellé remplacé par « Un instant… », `aria-busy="true"`, largeur figée |

### 5.1 Jaquette (2:3)
- `aspect-ratio: 2 / 3`, rayon `md`, bord `1px line`, image `object-fit: cover`. `alt=""` : le
  titre est toujours écrit à côté de la jaquette, il serait sinon lu deux fois par les lecteurs
  d'écran (revue de la phase 8). Une jaquette seule, sans titre visible, porterait le titre en
  `alt`.
- **Sans image** (dataset 2020, image absente ou en erreur) : une composition voulue, pas une
  erreur. Fond d'un des six tons `jacket-*` ; en haut, type et année en `meta` `ink-2`
  (« MANHWA · 2018 ») ; en bas, un filet `ink` de 2 px sur 24 px puis le titre en Fraunces 600
  `h3` (coupé à 3 lignes). Le ton vient de la couleur dominante fournie par AniList, ramenée au
  ton de teinte la plus proche (jamais affichée brute) ; sans couleur, le titre choisit le ton,
  toujours le même pour une œuvre (`lib/jacket.ts`). Même taille que l'image : la grille ne saute
  pas. Dans une ligne de liste (88 px) : type seul en haut, titre en `small`.
- Survol (si c'est un lien) : bord `line-strong`, titre souligné sous la jaquette.
- Chargement : squelette `surface` 2:3.
- Tailles : 160 px de large en rangée desktop, 2 colonnes sur mobile, 88 px dans une ligne de liste.

### 5.2 Ligne de liste (Ma liste)
- Grille : jaquette 88 px · titre et méta · progression, actions sous la progression (toutes les
  barres ont la même largeur d'une ligne à l'autre).
- Progression : « 7 / 24 ép. » tabulaire + barre de 4 px (rayon `sm`, fond `line`, remplissage
  `ink-2`). Lâché : barre figée, libellé « Lâché à l'ép. 3 ».
- Actions : « +1 ép. » (bouton secondaire, une seule frappe) et « J'ai lâché » (bouton discret).
  Au dernier épisode, « +1 ép. » propose « Marquer comme terminé ».
- Rappel facultatif sous la progression, en `small` : « Encore 3 épisodes avant le point de non-retour. »
  (en `good` une fois le point passé).
- Survol de la ligne : fond `hover`. Ligne entière jamais cliquable : le titre est le lien.

### 5.3 Note
- Affichage : `8/10` (§ 2.2). Pas d'étoiles.
- Saisie : groupe de 10 boutons radio stylés en segments (rayon `md` aux extrémités), libellé
  « Ta note ». Sélection : fond `raised`, chiffre en `ink`, bord `ink`. Une note vide se dit
  « Pas encore noté ».

### 5.4 Indicateur de risque de drop
Trois états, **toujours chiffre + libellé**, jamais la couleur seule :

| Statut API | Chiffre | Libellé et marqueur |
|---|---|---|
| `ok`, probabilité ≥ seuil | `figure` en `ink` | « À risque », trait vertical de 4 px en `accent` à gauche du libellé |
| `ok`, probabilité < seuil | `figure` en `ink` | « Risque faible », trait en `good` |
| `insufficient_data` | aucun chiffre | « Pas encore assez de données » + raison en `ink-2` |

Toujours sous le chiffre : « Seuil du modèle : 24 % » et une phrase d'explication. Format
compact (ligne de liste, carte de reco) : chiffre en `h3` + libellé.

### 5.5 Courbe de drop par épisode
- Barres verticales, une par épisode atteint (0 = « avant de commencer »), couleur `chart`,
  rayon `none`, axe bas `1px ink`, pas d'axe vertical (valeurs écrites au-dessus des barres sur
  desktop, au survol et au focus sur mobile).
- **Épisode critique** : barre `accent` + libellé texte sous le graphique (« Épisode 1 —
  critique. 21 % des drops tombent ici. »).
- **Point de non-retour** : barre `good` + libellé texte (« Épisode 7 — point de non-retour. »).
- Accessibilité : `role="img"` et `aria-label` résumant pic et repères, plus un tableau
  équivalent masqué visuellement (`sr-only`).
- Au-delà de 26 épisodes : regroupement par tranches (1–5, 6–10…) pour garder des barres
  lisibles sur mobile.
- Valeurs au-dessus des barres sur desktop **jusqu'à 13 barres** ; au-delà elles se
  chevaucheraient et passent au survol, comme sur mobile (ajouté en phase 9). Le tableau `sr-only`
  donne toujours toutes les valeurs.
- Chargement : squelette `surface` de la hauteur du graphique.

### 5.6 Onglets
- Texte `ui` en `ink-2`, actif en `ink` avec trait de 2 px `accent` dessous ; compteur
  tabulaire (« En cours · 3 »).
- Rôles ARIA `tablist` / `tab` / `tabpanel`, flèches gauche/droite pour changer d'onglet.
- Mobile : défilement horizontal, sans barre visible, onglet actif ramené dans la vue.

### 5.7 Boutons
| Variante | Repos | Survol |
|---|---|---|
| primaire (une par écran) | fond `accent`, texte `on-accent` 600, rayon `md` | fond `accent-hover` |
| secondaire | fond transparent, bord `1px line-strong`, texte `ink` | fond `hover` |
| discret | texte `ink` souligné, sans fond | texte `ink`, soulignement plus épais |
| destructif (supprimer le compte) | bord `1px accent`, texte `accent` | fond `hover` |

Hauteur min 44 px, padding horizontal 16 à 24 px. Bouton icône seule : 44 × 44 px,
`aria-label` obligatoire.

### 5.8 Champs
- Libellé au-dessus (`small` 600 `ink-2`), champ `surface`, bord `1px line-strong`, rayon `md`,
  hauteur 44 px, texte `body` `ink`, placeholder `ink-2` (un exemple, jamais le libellé).
- Survol : bord `ink-2`. Focus : contour § 5. Erreur : bord `accent` + message dessous en `accent`
  `small`, relié par `aria-describedby`, précédé de « Erreur : » pour les lecteurs d'écran.
- Aide permanente sous le champ en `ink-2` (« 10 caractères minimum »).

### 5.9 Navigation
- **Desktop** : barre haute de 72 px, logo complet à gauche (`tsuzuku-logo-dark.svg`, 48 px de
  haut, lien vers l'accueil avec `aria-label="Tsuzuku, accueil"`), liens texte `ui` (Découvrir, Ma liste,
  Pour toi), lien actif `ink` + trait `accent` 2 px, compte à droite (menu `lg`). Pour un
  visiteur, « Créer mon journal » en bouton **secondaire** : l'action principale corail est dans
  la page (une seule par écran, § 1.3).
- **Mobile** : barre basse fixe de 64 px + zone de sécurité (`env(safe-area-inset-bottom)`),
  4 entrées icône + libellé (Découvrir, Ma liste, Pour toi, Profil ; Profil mène à Compte, d'où un
  lien ouvre le profil public ; Connexion pour un visiteur), fond `surface`, filet
  `line` en haut ; actif : icône et libellé `ink` + trait 2 px `accent` au-dessus. En haut de
  page : le logo complet à 36 px de haut (l'icône seule sous 360 px de large).
- Lien d'évitement « Aller au contenu » en premier élément focusable.

---

## 6. Mouvement

- Durées : 150 ms (survol, focus), 200 ms (onglets, menus), 250 ms maximum (dialogues,
  apparition d'une ligne).
- Courbe : `cubic-bezier(0.2, 0, 0, 1)` (sortie douce), sans rebond ni dépassement.
- Propriétés animées : `opacity`, `color`, `background-color`, `border-color`, `transform`
  (translation de 4 à 8 px pour une apparition) ; jamais `width`/`height` ni d'agrandissement.
- La barre de progression glisse vers sa nouvelle valeur après « +1 ép. » (200 ms).
- `prefers-reduced-motion: reduce` : durées ramenées à 0 ms, squelettes sans pulsation.

---

## 7. Ton éditorial

Tutoiement, phrases courtes, vocabulaire de fan (épisode, arc, drop, lâcher, manhwa, binge).
Pas de formule marketing, pas de point d'exclamation en série, pas d'emoji. On dit ce qui se
passe et ce que la personne peut faire.

Exemples de micro-textes :

| Où | Texte |
|---|---|
| bouton principal, fiche | Ajouter à ma liste |
| bouton, ligne de liste | +1 ép. |
| bouton, ligne de liste | J'ai lâché |
| état vide, Ma liste › Lâché | Rien de lâché pour l'instant. Tu tiens bon. |
| état vide, Ma liste › En cours | Rien en cours. Trouve ta prochaine série dans Pour toi. |
| onboarding, compteur | Encore 4 titres et tes recos sont prêtes. |
| alerte d'épisode critique, ligne de liste | Prochain épisode : le 25. C'est là que la plupart lâchent Death Note. |
| point de non-retour passé | Tu as passé l'épisode 7 : la plupart vont au bout. |
| erreur réseau | Impossible d'enregistrer. Vérifie ta connexion et réessaie. |
| erreur de connexion | Email ou mot de passe incorrect. |
| trop de tentatives | Trop d'essais. Réessaie dans 5 minutes. |
| risque sans données | Pas encore assez de données pour les manhwas. On ne va pas inventer un chiffre. |
| fiche, sous la jaquette | Proposer une jaquette |
| proposition envoyée | Merci, on la vérifie avant de l'afficher. |

---

## 8. Traduction technique

Tailwind CSS v4 (configuration en CSS par `@theme`, version installée par Next.js) et
shadcn/ui, dont les variables sont reliées aux mêmes tokens. **Les valeurs par défaut de
Tailwind sont supprimées** (`--color-*: initial`, etc.) : `bg-red-500`, `rounded-xl` ou `p-5`
n'existent pas, seule la palette ci-dessous compile.

`frontend/src/app/globals.css` :

```css
@import "tailwindcss";

@theme {
  /* Couleurs : uniquement celles de DESIGN.md § 1 */
  --color-*: initial;
  --color-bg: #0D0E13;
  --color-surface: #15161D;
  --color-raised: #1C1D26;
  --color-hover: #23242F;
  --color-line: #2A2B36;
  --color-line-strong: #707282;
  --color-ink: #ECEAE4;
  --color-ink-2: #A6A4A0;
  --color-disabled: #5C5B59;
  --color-accent: #FF6B57;
  --color-accent-hover: #FF8573;
  --color-on-accent: #14142B;
  --color-good: #7DB4F0;
  --color-chart: #6E7182;
  --color-transparent: transparent;

  /* Polices : variables posées par next/font (layout.tsx) */
  --font-*: initial;
  --font-display: var(--font-fraunces), Georgia, serif;
  --font-body: var(--font-source-sans), system-ui, sans-serif;

  /* Tailles § 2.1 */
  --text-*: initial;
  --text-figure: clamp(4.5rem, 3.2rem + 5.6vw, 7.5rem);
  --text-figure--line-height: 0.9;
  --text-display: clamp(2.75rem, 2rem + 3.2vw, 4.75rem);
  --text-display--line-height: 1.02;
  --text-h1: 2.75rem;    --text-h1--line-height: 1.1;
  --text-h2: 1.875rem;   --text-h2--line-height: 1.2;
  --text-h3: 1.5rem;     --text-h3--line-height: 1.25;
  --text-lead: 1.1875rem; --text-lead--line-height: 1.5;
  --text-body: 1.0625rem; --text-body--line-height: 1.55;
  --text-ui: 1rem;       --text-ui--line-height: 1.4;
  --text-small: 0.875rem; --text-small--line-height: 1.45;
  --text-meta: 0.8125rem; --text-meta--line-height: 1.4;

  /* Espacements § 3.2 : seuls ces pas existent */
  --spacing-*: initial;
  --spacing-0: 0px;   --spacing-1: 4px;   --spacing-2: 8px;   --spacing-3: 12px;
  --spacing-4: 16px;  --spacing-6: 24px;  --spacing-8: 32px;  --spacing-12: 48px;
  --spacing-16: 64px; --spacing-24: 96px; --spacing-32: 128px;

  /* Rayons § 3.3 */
  --radius-*: initial;
  --radius-none: 0;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 10px;
  --radius-full: 9999px;

  /* Breakpoints § 3.1 */
  --breakpoint-*: initial;
  --breakpoint-md: 768px;
  --breakpoint-lg: 1024px;
  --breakpoint-xl: 1280px;

  /* Mouvement § 6 */
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
  --duration-fast: 150ms;
  --duration-base: 200ms;
  --duration-slow: 250ms;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0ms !important;
    transition-duration: 0ms !important;
  }
}

:focus-visible {
  outline: 2px solid var(--color-ink);
  outline-offset: 2px;
}
```

**Garde-fous automatiques** (tests du front, lancés en CI) :
- un test qui parcourt `frontend/src` et échoue sur toute valeur arbitraire Tailwind de couleur,
  de rayon ou d'espacement (`bg-[#…]`, `rounded-[…]`, `p-[…]`), sur tout code hexadécimal hors
  de `globals.css`, et sur `font-family` en dur ;
- un test qui relit ce tableau de contrastes à partir des tokens de `globals.css` et échoue si
  une paire autorisée passe sous son seuil (un token modifié sans revérification casse la CI) ;
- les tests Playwright passent `axe-core` sur chaque écran (contrastes, rôles, libellés).

**Écart à signaler, jamais silencieux** : toute demande qui contredit ce document est signalée
avant d'être codée, avec deux options : adapter la demande ou mettre à jour `DESIGN.md`.
