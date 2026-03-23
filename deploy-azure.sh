#!/bin/bash
set -euo pipefail

# ============================================================================
# Intel Sweep — Azure Deployment
# Deploys to Azure Container Apps + Key Vault + Timer Trigger
# ============================================================================

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-intel-sweep-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
ACR_NAME="${AZURE_ACR_NAME:-intelsweepacr}"
VAULT_NAME="${AZURE_VAULT_NAME:-intel-sweep-vault}"
APP_NAME="intel-sweep"
ENV_NAME="intel-sweep-env"

echo "=== Intel Sweep Azure Deployment ==="
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Location:       ${LOCATION}"
echo ""

# --- 1. Create resource group ---
echo "Creating resource group..."
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

# --- 2. Create Container Registry ---
echo "Creating Container Registry..."
az acr create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --sku Basic \
  --admin-enabled true \
  --output none 2>/dev/null || true

ACR_LOGIN_SERVER=$(az acr show --name "${ACR_NAME}" --query loginServer --output tsv)

# --- 3. Store secrets in Key Vault ---
echo "Creating Key Vault and storing secrets..."
az keyvault create \
  --name "${VAULT_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none 2>/dev/null || true

_store_secret() {
  local name=$1 value=$2
  az keyvault secret set \
    --vault-name "${VAULT_NAME}" \
    --name "${name}" \
    --value "${value}" \
    --output none
}

[ -n "${SEARCH_API_KEY:-}" ]    && _store_secret "search-api-key" "${SEARCH_API_KEY}"
[ -n "${SCORING_API_KEY:-}" ]   && _store_secret "scoring-api-key" "${SCORING_API_KEY}"
[ -n "${SLACK_WEBHOOK_URL:-}" ] && _store_secret "slack-webhook-url" "${SLACK_WEBHOOK_URL}"

VAULT_URL="https://${VAULT_NAME}.vault.azure.net"

# --- 4. Build and push container ---
echo "Building container in ACR..."
az acr build \
  --registry "${ACR_NAME}" \
  --image "${APP_NAME}:latest" \
  --file Dockerfile \
  .

# --- 5. Create Container Apps environment ---
echo "Creating Container Apps environment..."
az containerapp env create \
  --name "${ENV_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none 2>/dev/null || true

# --- 6. Deploy Container App with scheduled job ---
echo "Deploying Container App..."
ACR_PASSWORD=$(az acr credential show --name "${ACR_NAME}" --query "passwords[0].value" --output tsv)

# Deploy as a job (scheduled) rather than a long-running app
az containerapp job create \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --environment "${ENV_NAME}" \
  --trigger-type "Schedule" \
  --cron-expression "0 7 * * *" \
  --image "${ACR_LOGIN_SERVER}/${APP_NAME}:latest" \
  --registry-server "${ACR_LOGIN_SERVER}" \
  --registry-username "${ACR_NAME}" \
  --registry-password "${ACR_PASSWORD}" \
  --cpu "0.25" \
  --memory "0.5Gi" \
  --replica-timeout 600 \
  --replica-retry-limit 1 \
  --env-vars \
    "SEARCH_API_KEY=secretref:search-api-key" \
    "SCORING_API_KEY=secretref:scoring-api-key" \
    "SLACK_WEBHOOK_URL=secretref:slack-webhook-url" \
    "AZURE_VAULT_URL=${VAULT_URL}" \
  --secrets \
    "search-api-key=keyvaultref:${VAULT_URL}/secrets/search-api-key,identityref:system" \
    "scoring-api-key=keyvaultref:${VAULT_URL}/secrets/scoring-api-key,identityref:system" \
    "slack-webhook-url=keyvaultref:${VAULT_URL}/secrets/slack-webhook-url,identityref:system" \
  --output none 2>/dev/null || \
echo "Container App job already exists. Update with 'az containerapp job update'."

echo ""
echo "=== Azure Deployment complete ==="
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Key Vault:      ${VAULT_URL}"
echo "Portal:         https://portal.azure.com/#@/resource/subscriptions/.../resourceGroups/${RESOURCE_GROUP}"
echo ""
echo "Manual trigger:"
echo "  az containerapp job start --name ${APP_NAME} --resource-group ${RESOURCE_GROUP}"
