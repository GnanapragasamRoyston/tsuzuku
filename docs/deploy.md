# Déploiement de Tsuzuku (phase 11)

Choix et justifications : [ADR 014](decisions/014-deploiement.md). Ce guide dit **quoi faire,
dans quel ordre**. Aucun secret n'est jamais écrit dans un fichier, un commit ou un message.

## 0. Une seule fois : comptes (Royston)
1. **Google Cloud** : créer un projet (ex. `tsuzuku-prod`) et lui associer un compte de
   facturation (carte demandée ; l'offre gratuite doit suffire, une alerte à 5 € est posée).
2. **Neon** : créer un projet, région **AWS Europe Central (Francfort)**, Postgres 16. Garder
   l'URL de connexion (bouton « Connect ») pour l'étape 2, sans la coller nulle part.
3. **Vercel** : se connecter avec GitHub, importer le dépôt, **Root Directory = `frontend`**.
   L'adresse vient du nom du projet ; `tsuzuku.vercel.app` étant déjà pris par un autre site,
   Vercel a attribué `tsuzuku-eight.vercel.app` (renommable dans Settings → Domains).
4. Installer `gcloud` puis `gcloud auth login`, et `gh auth login` (variables du dépôt).

## 1. Infrastructure GCP
Toujours à blanc d'abord, puis pour de vrai :
```bash
export PROJECT_ID=tsuzuku-prod
bash infra/gcp/bootstrap.sh base            # affiche les commandes
DRY_RUN=0 bash infra/gcp/bootstrap.sh base  # les exécute
DRY_RUN=0 bash infra/gcp/bootstrap.sh budget    # alerte e-mail à 50, 90, 100 % de 5 €
DRY_RUN=0 bash infra/gcp/bootstrap.sh secrets   # URL Neon saisie masquée ; JWT et relais générés
DRY_RUN=0 bash infra/gcp/bootstrap.sh github    # variables du dépôt pour deploy.yml
```

## 2. Données
```bash
make migrate && make db-publish TARGET_DATABASE_URL="$(read -rsp 'URL Neon : ' u; echo "$u")"
```
Puis, pour les œuvres ajoutées plus tard en production :
`DATABASE_URL=<URL Neon> make embeddings` (saisie masquée de la même façon).

## 3. Vercel (variables du projet, environnement Production)
- `API_URL` : URL du service Cloud Run (`gcloud run services describe tsuzuku-api
  --region europe-west3 --format 'value(status.url)'`, après le premier déploiement) ;
- `PROXY_SECRET` : `gcloud secrets versions access latest --secret proxy-secret`, copié
  directement dans le champ Vercel.

## 4. Premier déploiement
Pousser sur `main` (ou lancer `deploy` à la main dans l'onglet Actions), puis :
```bash
DRY_RUN=0 bash infra/gcp/bootstrap.sh schedulers   # ingestion quotidienne et hebdomadaire
DRY_RUN=0 bash infra/gcp/bootstrap.sh monitoring   # sonde /health/ready toutes les 15 min
bash infra/gcp/uptime_alert.sh                      # e-mail si la sonde échoue (5 min)
```


## 5. Power BI (phase 13, ADR 016)
Les vues du schéma `bi` arrivent toutes seules : le job de migration applique
`views_powerbi.sql` puis la migration Alembic `0004`. Le reste se fait une fois, depuis WSL, URL
Neon saisie masquée (jamais `db-publish` : il viderait les listes des comptes) :
```bash
NEON="$(read -rsp 'URL Neon : ' u; echo "$u")"
DATABASE_URL="$NEON" make anime-tags   # tags AniList des animes du mart (segment Isekai)
DATABASE_URL="$NEON" make embeddings   # les tags entrent dans le texte embarqué (ADR 013)
DATABASE_URL="$NEON" make bi-role      # rôle tsuzuku_bi, mot de passe BI_DB_PASSWORD du .env
DATABASE_URL="$NEON" make bi-report    # reports/powerbi_summary.json (« database »: production)
```
Puis construire le tableau de bord : [powerbi/GUIDE.md](../powerbi/GUIDE.md).

## Vérifications après chaque mise en ligne
- `https://tsuzuku-eight.vercel.app` : accueil, inscription, recos, fiche ;
- `curl <URL API>/media/popular?kind=anime` doit répondre **403** (appel direct refusé) ;
- journaux : `gcloud run services logs read tsuzuku-api --region europe-west3`.

## Dépannage
| Symptôme | Cause probable |
|---|---|
| 403 partout depuis le site | `PROXY_SECRET` différent entre Vercel et Secret Manager |
| `/health/ready` en 503, `models: unavailable` | `MODELS_URI` faux ou droits du bucket |
| Routes du catalogue en 500 après une mise à jour | job de migration en échec (voir ses journaux) |
| Images qui ne s'affichent plus | quota d'optimisation Vercel atteint (5 000 par mois) |
