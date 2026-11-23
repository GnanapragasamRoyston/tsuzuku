# Déploiement de Tsuzuku (phase 11)

Choix et justifications : [ADR 014](decisions/014-deploiement.md). Ce guide dit **quoi faire,
dans quel ordre**. Aucun secret n'est jamais écrit dans un fichier, un commit ou un message.

## 0. Une seule fois : comptes (Royston)
1. **Google Cloud** : créer un projet (ex. `tsuzuku-prod`) et lui associer un compte de
   facturation (carte demandée ; l'offre gratuite doit suffire, une alerte à 5 € est posée).
2. **Neon** : créer un projet, région **AWS Europe Central (Francfort)**, Postgres 16. Garder
   l'URL de connexion (bouton « Connect ») pour l'étape 2, sans la coller nulle part.
3. **Vercel** : se connecter avec GitHub, importer le dépôt, **Root Directory = `frontend`**,
   nom du projet `tsuzuku` (→ `tsuzuku.vercel.app`). Ne pas déployer tout de suite.
4. Installer `gcloud` puis `gcloud auth login`, et `gh auth login` (variables du dépôt).

## 1. Infrastructure GCP
Toujours à blanc d'abord, puis pour de vrai :
```bash
export PROJECT_ID=tsuzuku-prod
bash infra/gcp/bootstrap.sh base            # affiche les commandes
DRY_RUN=0 bash infra/gcp/bootstrap.sh base  # les exécute
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
BILLING_ACCOUNT=… ALERT_EMAIL=… DRY_RUN=0 bash infra/gcp/bootstrap.sh monitoring
```
Dans la console Monitoring : canal d'alerte e-mail + règle « sonde tsuzuku-api-ready en échec ».

## Vérifications après chaque mise en ligne
- `https://tsuzuku.vercel.app` : accueil, inscription, recos, fiche ;
- `curl <URL API>/media/popular?kind=anime` doit répondre **403** (appel direct refusé) ;
- journaux : `gcloud run services logs read tsuzuku-api --region europe-west3`.

## Dépannage
| Symptôme | Cause probable |
|---|---|
| 403 partout depuis le site | `PROXY_SECRET` différent entre Vercel et Secret Manager |
| `/health/ready` en 503, `models: unavailable` | `MODELS_URI` faux ou droits du bucket |
| Routes du catalogue en 500 après une mise à jour | job de migration en échec (voir ses journaux) |
| Images qui ne s'affichent plus | quota d'optimisation Vercel atteint (5 000 par mois) |
