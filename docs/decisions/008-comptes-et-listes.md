# ADR 008 — Comptes, sessions et listes

**Date** : 2026-11-21 · **Statut** : accepté (choix validés par Royston le 2026-11-20)

## Contexte
Phase 7 (SPEC § 7 et § 10) : inscription et connexion par email + mot de passe, RGPD (export,
suppression), gestion de la liste (`/me/list`), migrations Alembic, tests. Les recos et le risque
de drop, servis en mode démo depuis la phase 5 (profil passé dans la requête), doivent maintenant
partir de la liste enregistrée.

## Décisions

### a) Alembic ne gère que le schéma `app`
`catalog` et `mart` appartiennent au pipeline (fichiers SQL, ADR 003), qui les crée et les
recharge. Les tables de l'API (`users`, `list_entry`, `onboarding_choice`) sont dans `app` et
**seulement** créées par les migrations Alembic (`backend/migrations`, `make migrate`).
- Deux filtres (`alembic_include_name` côté base, `alembic_include_object` côté modèles) empêchent
  Alembic de comparer `catalog` et `mart`, donc de proposer un jour de les modifier.
- La table de version d'Alembic vit dans `app`.
- La migration 0001 est écrite à la main ; un test vérifie qu'elle correspond exactement aux
  modèles SQLAlchemy (`compare_metadata` vide), un autre qu'elle se défait et se refait.
- Docker : un service `api-migrate` (même image) lance `alembic upgrade head` avant l'API, qui
  ne démarre que s'il a réussi. **Ordre** : `make up` → `make spark` (catalogue) → `make api-up`.
  Sans `catalog.media`, la migration s'arrête avec un message clair au lieu d'une erreur SQL.
- Piège rencontré : une requête lancée après le `commit` d'`env.py` ouvrait une transaction
  qu'Alembic prenait pour une transaction externe ; il ne validait jamais la migration, et les
  tables disparaissaient en silence. Les tests (base migrée par les vraies migrations) l'ont
  attrapé.

**Écarté** : un seul outil pour tout (Alembic sur `catalog`/`mart`). Le pipeline recharge les
marts par `TRUNCATE` + `COPY` depuis Spark ; deux propriétaires pour une même table, c'est deux
façons de la casser.

Table `users` et non `user` (SPEC § 5) : `user` est un mot réservé de Postgres, il faudrait des
guillemets dans chaque requête, vues Power BI comprises. L'avatar de la SPEC attend la phase 9.

### b) Intégrité en base, pas seulement dans Pydantic
Contraintes `CHECK` (statut, note de 1 à 10, `dropped_at` seulement si `dropped`, dates dans
l'ordre, pseudo `^[a-z0-9_]{3,20}$`, email en minuscules) et clés étrangères. Un script, une
migration de données ou un outil d'admin ne peut pas écrire une liste incohérente.
- `list_entry → catalog.media` en **`ON DELETE CASCADE`** : le pipeline retire parfois une œuvre
  absente de la source (148 romans en phase 6). L'entrée disparaît avec elle au lieu de bloquer
  le chargement. Vérifié : le catalogue est rechargé par **upsert** (ids stables), jamais par
  `TRUNCATE`, donc un rechargement normal n'efface pas les listes.
- `users → list_entry / onboarding_choice` en cascade : supprimer un compte efface tout.

### c) Mots de passe : argon2id
`argon2-cffi`, paramètres par défaut (profil RFC 9106). Longueur 10 à 128 caractères, sans règle
de composition (NIST SP 800-63B) ; le maximum borne le coût du hachage d'une entrée envoyée par
un inconnu. Rehachage à la connexion si les paramètres sont renforcés plus tard.
**Email inconnu** : on vérifie quand même contre un hash factice, pour que la durée de la réponse
ne révèle pas quels emails ont un compte. Même message d'erreur dans les deux cas.

### d) Session : JWT dans un cookie, révocation par `token_version`
- Jeton **JWT HS256** (PyJWT), 7 jours, qui ne contient que l'id du compte et sa
  `token_version` (un JWT est signé, pas chiffré). Algorithme imposé au décodage : un jeton
  `alg: none` est refusé.
- Cookie `tsuzuku_session` **`httpOnly`** (illisible par le JavaScript : un script injecté ne le
  vole pas), **`Secure`** (HTTPS seulement ; les navigateurs l'acceptent aussi sur
  `http://localhost`), **`SameSite=Lax`**.
- **Révocation** : la déconnexion incrémente `users.token_version` ; tout jeton émis avant porte
  l'ancienne valeur et devient invalide. Conséquence assumée : se déconnecter ferme **toutes** les
  sessions du compte.
- Secret `JWT_SECRET` dans `.env` (`make api-keys`, 64 caractères aléatoires, jamais affichés).
  Absent ou trop court : l'API démarre quand même (catalogue, démo, `/health`) et les routes de
  compte répondent 503.

**Écartés** : jeton dans `localStorage` (lisible par tout script de la page) ; JWT sans
révocation (une déconnexion ne protège pas d'un jeton copié) ; table de sessions en base (une
lecture de plus à chaque requête pour un besoin couvert par `token_version`).

### e) CSRF, CORS et erreurs de validation
Pas de jeton CSRF dédié : `SameSite=Lax` empêche un autre site d'envoyer le cookie avec un POST,
PUT ou DELETE ; CORS n'autorise que l'origine du front (`allow_credentials`) ; les corps sont du
JSON (un corps `text/plain` reçoit un 422). `CORS_ORIGINS` contenant `*` est **refusé au
démarrage** : avec les cookies, n'importe quel site pourrait lire `/me/export`.
Les réponses 422 ne renvoient que l'endroit et le motif de l'erreur, jamais la valeur saisie (par
défaut, FastAPI la recopie : un mot de passe mal placé repartait dans la réponse).

**Risque accepté** : `/auth/register` répond 409 si l'email est déjà pris, ce qui révèle qu'un
compte existe (la connexion, elle, ne le révèle pas). Limité à 5 essais par heure et par IP ;
la parade complète (réponse identique et confirmation par email) demande l'envoi d'emails, hors
périmètre.

### f) Limitation de débit en mémoire
Fenêtre glissante (`app/core/rate_limit.py`), seuils dans `settings.yaml` :
- connexion : 5 échecs / 5 min, comptés **par IP et par email** (un attaquant qui essaie beaucoup
  d'emails, ou un compte visé depuis plusieurs IP) ; une connexion réussie remet le compteur de
  l'email à zéro ;
- inscription : 5 essais / heure par IP.

Réponse 429 avec `Retry-After`. Vérifier et compter se font **atomiquement** (un seul verrou),
avant le calcul argon2 : sans ça, une rafale de requêtes simultanées passait toute la
vérification avant le premier comptage (revue de sécurité) ; un essai réussi est ensuite rendu.
`DELETE /me` est limité de la même façon : un cookie volé ne permet pas de deviner le mot de
passe sans limite. **Limite connue** : en mémoire du processus, remis à zéro au
redémarrage et non partagé entre instances ; derrière un proxy, l'IP vue est celle du proxy. À
revoir en phase 11 (Cloud Run) : stockage commun et IP du client transmise par le proxy.

### g) Liste, onboarding, recos
- `PUT /me/list/{media_id}` remplace l'entrée entière (sémantique de PUT), via
  `INSERT … ON CONFLICT DO UPDATE` : deux requêtes simultanées ne lèvent pas d'erreur de clé.
  `completed` remplit la progression avec le nombre d'épisodes ou de chapitres s'il est connu ;
  `dropped` sans `dropped_at` prend la progression, et `dropped_at` ne peut pas la dépasser.
  Au plus 5 000 œuvres par liste.
- Les écritures d'un même compte (liste, onboarding) verrouillent sa ligne `users`
  (`SELECT … FOR UPDATE`) : un double clic sur l'onboarding ne finit pas en 500, et des PUT
  simultanés ne dépassent pas la taille maximale.
- **Onboarding** : au moins **10 œuvres** (SPEC § 8, `onboarding_min_choices`), au-dessus de la
  règle des 5 titres aimés de l'ALS (ADR 006). Refaire l'onboarding remplace les choix.
- **Profil de reco** = choix d'onboarding (note par défaut de la fiche du modèle) + entrées
  notées (la note de la liste l'emporte ; une mauvaise note pèse comme préférence négative, comme
  en mode démo). **Toute la liste est exclue** des recos : on ne recommande pas ce qui est déjà
  vu, prévu ou abandonné.
- `/me/recommendations?kind=manga|manhwa|manhua` → **501** : recos par le contenu en phase 10,
  pas de faux résultat avant.
- `/me/drop-risk/{media_id}` : même service que la démo, liste lue en base.

### h) RGPD
- `GET /me/export` : profil, liste (critiques comprises) et choix d'onboarding en JSON
  téléchargeable. Le hash du mot de passe et `token_version` n'en font pas partie (données de
  sécurité, pas des données fournies par la personne).
- `DELETE /me` : mot de passe redemandé (un cookie volé ne suffit pas à effacer un compte), puis
  suppression en cascade. Rien n'est gardé.
- Journaux : seulement l'id du compte, jamais l'email ni le mot de passe (vérifié par un test et
  sur les logs du conteneur). Texte de la future page de confidentialité :
  [docs/privacy.md](../privacy.md).

### i) Reporté
`/users/{pseudo}` (profil public) passe en phase 9, avec la page qui l'affiche ; `follow` reste
optionnel (SPEC § 5).

## Conséquences
- 146 tests backend (94 nouveaux : auth, liste, recos depuis la base, RGPD, migrations, briques
  de sécurité, accès simultanés), sur une vraie base Postgres migrée par Alembic.
- Le front (phase 8) appelle l'API avec `credentials: "include"` ; il ne voit jamais le jeton.
- **À surveiller** :
  - phase 11 : si le front (Vercel) et l'API (Cloud Run) sont sur deux sites différents, un
    cookie `SameSite=Lax` n'est plus envoyé. Il faudra un domaine commun (sous-domaines) ou
    `SameSite=None` avec un jeton CSRF. Il faudra aussi un verrou si plusieurs instances lancent
    les migrations en même temps ;
  - avec la cascade, si un fichier source arrive tronqué au pipeline, les œuvres retirées
    emportent les entrées de liste. Un garde-fou sur le nombre d'œuvres retirées par chargement
    est à ajouter côté pipeline.
