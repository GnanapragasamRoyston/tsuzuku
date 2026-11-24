#!/usr/bin/env bash
# Alerte e-mail quand la sonde /health/ready échoue (phase 11, ADR 014). Idempotent.
#   PROJECT_ID=tsuzuku-prod bash infra/gcp/uptime_alert.sh
# L'adresse est celle du compte gcloud connecté, lue au moment de l'exécution : elle n'est
# écrite dans aucun fichier du dépôt.
set -euo pipefail
: "${PROJECT_ID:?PROJECT_ID manquant}"
API="https://monitoring.googleapis.com/v3/projects/$PROJECT_ID"
token=$(gcloud auth print-access-token)
email=$(gcloud config get-value account 2>/dev/null)
call() { curl -sS --fail-with-body -H "Authorization: Bearer $token" -H "Content-Type: application/json" "$@"; }

check=$(gcloud monitoring uptime list-configs --project "$PROJECT_ID" \
  --filter 'displayName=tsuzuku-api-ready' --format 'value(name)' | head -1)
check_id=${check##*/}
[[ -n "$check_id" ]] || { echo "Sonde tsuzuku-api-ready introuvable (bootstrap.sh monitoring)" >&2; exit 1; }

channel=$(call "$API/notificationChannels" | python3 -c "
import json, sys
for c in json.load(sys.stdin).get('notificationChannels', []):
    if c.get('displayName') == 'tsuzuku-email':
        print(c['name']); break")
if [[ -z "$channel" ]]; then
  channel=$(call -X POST "$API/notificationChannels" -d "$(python3 -c "
import json, sys
print(json.dumps({'type': 'email', 'displayName': 'tsuzuku-email',
                  'labels': {'email_address': sys.argv[1]}}))" "$email")" \
    | python3 -c "import json, sys; print(json.load(sys.stdin)['name'])")
  echo "Canal e-mail créé."
fi

exists=$(call "$API/alertPolicies" | python3 -c "
import json, sys
print(any(p.get('displayName') == 'tsuzuku-api-indisponible'
          for p in json.load(sys.stdin).get('alertPolicies', [])))")
if [[ "$exists" == "True" ]]; then echo "Règle d'alerte déjà en place."; exit 0; fi

# Alerte si la sonde échoue depuis au moins 2 régions pendant 5 minutes (un échec isolé d'une
# région n'est pas une panne). Démarrage à froid inclus : la sonde a 10 s de délai.
call -X POST "$API/alertPolicies" -d "$(python3 -c "
import json, sys
check, channel = sys.argv[1], sys.argv[2]
print(json.dumps({
  'displayName': 'tsuzuku-api-indisponible',
  'combiner': 'OR',
  'notificationChannels': [channel],
  'documentation': {'content': 'La sonde /health/ready de l API échoue. Voir docs/deploy.md (Dépannage).',
                    'mimeType': 'text/markdown'},
  'conditions': [{
    'displayName': 'Sonde /health/ready en échec',
    'conditionThreshold': {
      'filter': 'metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" '
                'AND resource.type=\"uptime_url\" AND metric.label.check_id=\"%s\"' % check,
      'comparison': 'COMPARISON_GT', 'thresholdValue': 1, 'duration': '300s',
      'trigger': {'count': 1},
      'aggregations': [{'alignmentPeriod': '1200s', 'perSeriesAligner': 'ALIGN_NEXT_OLDER',
                        'crossSeriesReducer': 'REDUCE_COUNT_FALSE',
                        'groupByFields': ['resource.label.project_id']}],
    }}],
}))" "$check_id" "$channel")" >/dev/null
echo "Règle d'alerte créée."
