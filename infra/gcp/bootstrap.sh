#!/usr/bin/env bash
# Mise en place Google Cloud de Tsuzuku (phase 11, ADR 014). Idempotent : relançable sans risque.
#
#   PROJECT_ID=… bash infra/gcp/bootstrap.sh <étape>
#   Étapes, dans l'ordre : base, budget, secrets, github, (1er déploiement), schedulers, monitoring
#
# À BLANC par défaut (DRY_RUN=1) : chaque commande est affichée, rien n'est exécuté. Relancer avec
# DRY_RUN=0 pour appliquer. Aucun secret n'est jamais affiché ni passé en argument de commande
# (il passerait dans l'historique et la liste des processus) : lecture masquée, puis stdin.
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID manquant (projet GCP créé par Royston)}"
REGION="${REGION:-europe-west3}"                    # Francfort, près de Neon eu-central-1
GITHUB_REPO="${GITHUB_REPO:-GnanapragasamRoyston/tsuzuku}"
FRONT_ORIGIN="${FRONT_ORIGIN:-https://tsuzuku.vercel.app}"
DRY_RUN="${DRY_RUN:-1}"
BUCKET="${PROJECT_ID}-tsuzuku-models"
cd "$(dirname "$0")/../.."

run() {
  printf '+'; printf ' %q' "$@"; printf '\n'
  [[ "$DRY_RUN" == "1" ]] || "$@"
}
exists() { [[ "$DRY_RUN" == "1" ]] && return 1; "$@" >/dev/null 2>&1; }
sa() { echo "$1@${PROJECT_ID}.iam.gserviceaccount.com"; }

base() {
  run gcloud config set project "$PROJECT_ID"
  run gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com \
    iamcredentials.googleapis.com sts.googleapis.com monitoring.googleapis.com \
    billingbudgets.googleapis.com storage.googleapis.com
  exists gcloud artifacts repositories describe tsuzuku --location "$REGION" ||
    run gcloud artifacts repositories create tsuzuku --repository-format docker --location "$REGION"
  # Seules les 3 dernières versions de chaque image sont gardées : le stockage (0,5 Go offert)
  # ne grossit pas à chaque déploiement.
  run gcloud artifacts repositories set-cleanup-policies tsuzuku --location "$REGION" \
    --policy infra/gcp/ar-cleanup.json --no-dry-run
  # Bucket des modèles servis : accès uniforme, jamais public.
  exists gcloud storage buckets describe "gs://$BUCKET" ||
    run gcloud storage buckets create "gs://$BUCKET" --location "$REGION" \
      --uniform-bucket-level-access --public-access-prevention
  run gcloud storage cp models/drop_model.joblib models/drop_model.json \
    models/reco_item_factors.parquet models/reco_model.json "gs://$BUCKET/models/"
  # Comptes de service à droits minimaux : un par usage.
  for name in tsuzuku-api tsuzuku-ingest tsuzuku-deployer tsuzuku-scheduler; do
    exists gcloud iam service-accounts describe "$(sa $name)" ||
      run gcloud iam service-accounts create "$name"
  done
  run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member "serviceAccount:$(sa tsuzuku-api)" --role roles/storage.objectViewer
  for role in roles/run.admin roles/artifactregistry.writer; do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition None \
      --member "serviceAccount:$(sa tsuzuku-deployer)" --role "$role"
  done
  for runtime in tsuzuku-api tsuzuku-ingest; do  # le déployeur « agit en tant que » ces comptes
    run gcloud iam service-accounts add-iam-policy-binding "$(sa $runtime)" \
      --member "serviceAccount:$(sa tsuzuku-deployer)" --role roles/iam.serviceAccountUser
  done
  # GitHub Actions → GCP sans clé : seul CE dépôt peut emprunter le compte de déploiement.
  exists gcloud iam workload-identity-pools describe github --location global ||
    run gcloud iam workload-identity-pools create github --location global
  exists gcloud iam workload-identity-pools providers describe github --location global \
      --workload-identity-pool github ||
    run gcloud iam workload-identity-pools providers create-oidc github --location global \
      --workload-identity-pool github --issuer-uri https://token.actions.githubusercontent.com \
      --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
      --attribute-condition "assertion.repository == '$GITHUB_REPO'"
  local number
  number=$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)' 2>/dev/null || echo NUMERO)
  run gcloud iam service-accounts add-iam-policy-binding "$(sa tsuzuku-deployer)" \
    --role roles/iam.workloadIdentityUser \
    --member "principalSet://iam.googleapis.com/projects/$number/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"
}

secret_from_stdin() {  # $1 = nom du secret ; la valeur arrive sur stdin
  exists gcloud secrets describe "$1" || run gcloud secrets create "$1" --replication-policy automatic
  if [[ "$DRY_RUN" == "1" ]]; then echo "+ gcloud secrets versions add $1 --data-file - (valeur masquée)"
  else gcloud secrets versions add "$1" --data-file -; fi
}

secrets() {
  read -r -s -p "URL de la base Neon (postgresql://…, ne s'affiche pas) : " database_url; echo
  printf '%s' "$database_url" | secret_from_stdin database-url
  # Générés ici, jamais affichés : 48 octets aléatoires (le JWT exige ≥ 32 caractères).
  python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | secret_from_stdin jwt-secret
  python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | secret_from_stdin proxy-secret
  for s in database-url jwt-secret proxy-secret; do
    run gcloud secrets add-iam-policy-binding "$s" \
      --member "serviceAccount:$(sa tsuzuku-api)" --role roles/secretmanager.secretAccessor
  done
  run gcloud secrets add-iam-policy-binding database-url \
    --member "serviceAccount:$(sa tsuzuku-ingest)" --role roles/secretmanager.secretAccessor
  echo "PROXY_SECRET pour Vercel : à copier par toi depuis ton terminal (jamais dans un fichier) :"
  echo "  gcloud secrets versions access latest --secret proxy-secret"
}

github() {
  local number provider
  number=$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)' 2>/dev/null || echo NUMERO)
  provider="projects/$number/locations/global/workloadIdentityPools/github/providers/github"
  run gh variable set GCP_PROJECT --body "$PROJECT_ID"
  run gh variable set GCP_REGION --body "$REGION"
  run gh variable set GCP_WIF_PROVIDER --body "$provider"
  run gh variable set GCP_DEPLOYER_SA --body "$(sa tsuzuku-deployer)"
  run gh variable set MODELS_URI --body "gs://$BUCKET/models"
  run gh variable set FRONT_ORIGIN --body "$FRONT_ORIGIN"
}

schedulers() {  # après le premier déploiement (les jobs doivent exister)
  for job in tsuzuku-jikan-daily tsuzuku-anilist-weekly; do
    run gcloud run jobs add-iam-policy-binding "$job" --region "$REGION" \
      --member "serviceAccount:$(sa tsuzuku-scheduler)" --role roles/run.invoker
  done
  local api="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs"
  # Mêmes horaires que les DAG Airflow (heure de Paris).
  for spec in "tsuzuku-jikan-daily|0 6 * * *" "tsuzuku-anilist-weekly|0 5 * * 1"; do
    local job=${spec%%|*} cron=${spec#*|}
    exists gcloud scheduler jobs describe "$job" --location "$REGION" ||
      run gcloud scheduler jobs create http "$job" --location "$REGION" --schedule "$cron" \
        --time-zone Europe/Paris --http-method POST --uri "$api/$job:run" \
        --oauth-service-account-email "$(sa tsuzuku-scheduler)"
  done
}

budget() {
  # Alerte de budget : 5 €, e-mail aux administrateurs de facturation à 50, 90 et 100 %.
  # Elle PRÉVIENT, elle ne coupe rien : en cas d'abus, désactiver la facturation du projet.
  local account
  account=$(gcloud billing projects describe "$PROJECT_ID" --format 'value(billingAccountName)' \
    2>/dev/null | sed 's|billingAccounts/||')
  if [[ "$DRY_RUN" != "1" ]] && gcloud billing budgets list --billing-account "$account" \
      --format 'value(displayName)' 2>/dev/null | grep -qx tsuzuku; then
    echo "Budget « tsuzuku » déjà en place."
    return
  fi
  run gcloud billing budgets create --billing-account "${account:-COMPTE}" \
    --display-name tsuzuku --budget-amount 5EUR --filter-projects "projects/$PROJECT_ID" \
    --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
}

monitoring() {
  local host
  host=$(gcloud run services describe tsuzuku-api --region "$REGION" --format 'value(status.url)' \
    2>/dev/null | sed 's|https://||' || echo HOTE_DE_L_API)
  run gcloud monitoring uptime create tsuzuku-api-ready --resource-type uptime-url \
    --resource-labels "host=$host,project_id=$PROJECT_ID" --path /health/ready --protocol https \
    --period 15 --timeout 10
  echo "Canal d'alerte e-mail et règle « sonde en échec » : voir docs/deploy.md (console Monitoring)."
}

case "${1:-}" in
  base | budget | secrets | github | schedulers | monitoring) "$1" ;;
  *) echo "Usage : $0 base|budget|secrets|github|schedulers|monitoring" >&2; exit 2 ;;
esac
[[ "$DRY_RUN" == "1" ]] && echo "(à blanc : rien n'a été exécuté ; DRY_RUN=0 pour appliquer)"
