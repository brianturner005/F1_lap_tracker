#!/usr/bin/env bash
# deploy.sh — provision Azure infrastructure and publish the Function App.
# Usage: ./infra/deploy.sh [resource-group] [location] [base-name]
set -euo pipefail

# ---------------------------------------------------------------------------
# Variables — override via positional args or environment variables
# ---------------------------------------------------------------------------
RESOURCE_GROUP="${1:-${RESOURCE_GROUP:-f1tracker-rg}}"
LOCATION="${2:-${LOCATION:-westeurope}}"
BASE_NAME="${3:-${BASE_NAME:-f1tracker}}"

# Azure OpenAI credentials for the AI debrief proxy (optional).
# Leave blank to skip — you can re-run deploy.sh later once quota is approved
# and the credentials will be added to the Function App settings.
AOAI_ENDPOINT="${AOAI_ENDPOINT:-}"
AOAI_KEY="${AOAI_KEY:-}"
AOAI_DEPLOYMENT="${AOAI_DEPLOYMENT:-gpt-4o-mini}"

if [[ -z "${AOAI_ENDPOINT}" ]]; then
  echo "ℹ️   Azure OpenAI endpoint not set — AI debrief will be disabled until you re-run this script with credentials."
  echo "     Set AOAI_ENDPOINT and AOAI_KEY env vars and re-run to enable it."
  echo ""
fi

# ⚠️  IMPORTANT: running this script re-deploys the Bicep template, which
# resets ALL Function App settings to the values passed here. If AOAI_ENDPOINT
# and AOAI_KEY are not exported before running, the existing credentials in
# Azure will be OVERWRITTEN with empty strings and the AI debrief will stop
# working.
#
# To push code changes ONLY (without touching app settings), use:
#   cd leaderboard_api && func azure functionapp publish <APP_NAME> --python
echo "⚠️  WARNING: This script will overwrite Azure Function App settings."
echo "     If you only want to publish code (not change settings), run instead:"
echo "     cd leaderboard_api && func azure functionapp publish \${BASE_NAME}-func --python"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BICEP_FILE="${SCRIPT_DIR}/main.bicep"
FUNC_SRC_DIR="${REPO_ROOT}/leaderboard_api"

echo "========================================================"
echo " Pitwall IQ — Community Leaderboard Deploy"
echo "========================================================"
echo " Resource Group : ${RESOURCE_GROUP}"
echo " Location       : ${LOCATION}"
echo " Base Name      : ${BASE_NAME}"
echo "========================================================"
echo ""

# ---------------------------------------------------------------------------
# 1. Ensure Azure CLI is logged in
# ---------------------------------------------------------------------------
echo "[1/5] Checking Azure CLI login..."
az account show --output none || {
  echo "ERROR: Not logged in to Azure. Run 'az login' first."
  exit 1
}
echo "      Logged in as: $(az account show --query 'user.name' -o tsv)"

# ---------------------------------------------------------------------------
# 2. Create resource group
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Creating resource group '${RESOURCE_GROUP}' in '${LOCATION}'..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none
echo "      Resource group ready."

# ---------------------------------------------------------------------------
# 3. Deploy Bicep template
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Deploying Bicep template (this may take a few minutes)..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${BICEP_FILE}" \
  --parameters baseName="${BASE_NAME}" location="${LOCATION}" \
               aoaiEndpoint="${AOAI_ENDPOINT}" aoaiKey="${AOAI_KEY}" aoaiDeployment="${AOAI_DEPLOYMENT}" \
  --output json)

echo "      Deployment complete."

# ---------------------------------------------------------------------------
# 4. Extract outputs
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Extracting deployment outputs..."

FUNC_APP_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.functionAppName.value')
FUNC_APP_URL=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.functionAppUrl.value')
COSMOS_ACCOUNT=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.cosmosAccountName.value')

if [[ -z "${FUNC_APP_NAME}" || "${FUNC_APP_NAME}" == "null" ]]; then
  echo "ERROR: Could not extract functionAppName from deployment output."
  echo "Raw output:"
  echo "${DEPLOY_OUTPUT}" | jq '.properties.outputs'
  exit 1
fi

echo "      Function App : ${FUNC_APP_NAME}"
echo "      Function URL : ${FUNC_APP_URL}"
echo "      Cosmos DB    : ${COSMOS_ACCOUNT}"

# ---------------------------------------------------------------------------
# 5. Publish function code
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Publishing function app code from '${FUNC_SRC_DIR}'..."
echo "      (Requires Azure Functions Core Tools — 'func' CLI)"

if ! command -v func &>/dev/null; then
  echo "ERROR: 'func' CLI not found. Install Azure Functions Core Tools:"
  echo "       https://learn.microsoft.com/azure/azure-functions/functions-run-local"
  exit 1
fi

(cd "${FUNC_SRC_DIR}" && func azure functionapp publish "${FUNC_APP_NAME}" --python)

echo ""
echo "      Publish complete."

# ---------------------------------------------------------------------------
# Retrieve the default function key for the submit endpoint
# ---------------------------------------------------------------------------
echo ""
echo "Retrieving default function host key..."
FUNC_KEY=$(az functionapp keys list \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${FUNC_APP_NAME}" \
  --query 'functionKeys.default' \
  -o tsv 2>/dev/null || echo "<retrieve-manually>")

# ---------------------------------------------------------------------------
# Done — print instructions
# ---------------------------------------------------------------------------
echo ""
echo "========================================================"
echo " Deployment successful!"
echo "========================================================"
echo ""
echo " Function App URL : ${FUNC_APP_URL}"
echo ""
echo " Set the following environment variables in your F1"
echo " lap tracker client before starting a session:"
echo ""
echo "   export F1_LEADERBOARD_URL=\"${FUNC_APP_URL}\""
echo "   export F1_LEADERBOARD_KEY=\"${FUNC_KEY}\""
echo ""
echo " The key is required for the POST /api/submit endpoint."
echo " You can also retrieve it from the Azure Portal under:"
echo "   ${FUNC_APP_NAME} > App keys > default"
echo ""
echo " Endpoints:"
echo "   POST  ${FUNC_APP_URL}/api/submit"
echo "         (header: x-functions-key: \$F1_LEADERBOARD_KEY)"
echo "   GET   ${FUNC_APP_URL}/api/leaderboard/{track}/{session_type}"
echo "   GET   ${FUNC_APP_URL}/api/tracks"
echo "========================================================"
