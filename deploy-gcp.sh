#!/bin/bash
set -euo pipefail

# ============================================================================
# Intel Sweep — GCP Deployment
# Deploys to Cloud Run + Cloud Scheduler with Secret Manager
# ============================================================================

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="intel-sweep"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Intel Sweep GCP Deployment ==="
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo ""

# --- 1. Create service account ---
echo "Creating service account..."
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Intel Sweep Scanner" \
  --project="${PROJECT_ID}" 2>/dev/null || true

# Minimal IAM: Firestore access + Secret Manager
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/datastore.user" --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" --quiet

# --- 2. Store secrets ---
echo "Storing secrets in Secret Manager..."
_store_secret() {
  local name=$1 value=$2
  echo -n "${value}" | gcloud secrets create "${name}" \
    --data-file=- --project="${PROJECT_ID}" 2>/dev/null || \
  echo -n "${value}" | gcloud secrets versions add "${name}" \
    --data-file=- --project="${PROJECT_ID}"
}

if [ -n "${SEARCH_API_KEY:-}" ]; then
  _store_secret "intel-sweep-search-key" "${SEARCH_API_KEY}"
fi
if [ -n "${SCORING_API_KEY:-}" ]; then
  _store_secret "intel-sweep-scoring-key" "${SCORING_API_KEY}"
fi
if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  _store_secret "intel-sweep-slack-webhook" "${SLACK_WEBHOOK_URL}"
fi

# --- 3. Build and push container ---
echo "Building container..."
gcloud builds submit --tag "${IMAGE}" --project="${PROJECT_ID}"

# --- 4. Deploy to Cloud Run ---
echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --memory=256Mi \
  --cpu=1 \
  --max-instances=1 \
  --no-allow-unauthenticated \
  --ingress=internal \
  --set-secrets="SEARCH_API_KEY=intel-sweep-search-key:latest,SCORING_API_KEY=intel-sweep-scoring-key:latest,SLACK_WEBHOOK_URL=intel-sweep-slack-webhook:latest" \
  --project="${PROJECT_ID}"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo "Service deployed: ${SERVICE_URL}"

# --- 5. Create Cloud Scheduler jobs ---
echo "Creating scheduler jobs..."

# Daily competitors scan at 7am UTC
gcloud scheduler jobs create http "intel-sweep-competitors" \
  --schedule="0 7 * * *" \
  --uri="${SERVICE_URL}" \
  --http-method=POST \
  --message-body='{"topics": ["competitors", "market_signals"]}' \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email="${SA_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud scheduler jobs update http "intel-sweep-competitors" \
  --schedule="0 7 * * *" \
  --uri="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"

# Weekly tech patterns scan on Fridays
gcloud scheduler jobs create http "intel-sweep-tech" \
  --schedule="0 7 * * 5" \
  --uri="${SERVICE_URL}" \
  --http-method=POST \
  --message-body='{"topics": ["tech_patterns"]}' \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email="${SA_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud scheduler jobs update http "intel-sweep-tech" \
  --schedule="0 7 * * 5" \
  --uri="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"

echo ""
echo "=== Deployment complete ==="
echo "Service:   ${SERVICE_URL}"
echo "Scheduler: https://console.cloud.google.com/cloudscheduler?project=${PROJECT_ID}"
echo ""
echo "Test manually:"
echo "  gcloud scheduler jobs run intel-sweep-competitors --location=${REGION}"
