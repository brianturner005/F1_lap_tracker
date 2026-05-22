#!/usr/bin/env bash
# Deploys the Fantasy F1 API backend to Azure.
# Usage: ./deploy.sh <resource-group> <azure-region>
# Example: ./deploy.sh fantasy-f1-rg eastus
set -euo pipefail

RESOURCE_GROUP="${1:?Usage: $0 <resource-group> <azure-region>}"
LOCATION="${2:?Usage: $0 <resource-group> <azure-region>}"

echo "==> Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "==> Deploying Cosmos DB + Function App via Bicep..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters baseName=fantasy-f1 location="$LOCATION" \
  --output json)

FUNC_NAME=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.functionAppName.value')
FUNC_URL=$(echo  "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.functionAppUrl.value')

echo "==> Publishing Azure Functions..."
cd "$(dirname "$0")/../api"
func azure functionapp publish "$FUNC_NAME" --python

echo ""
echo "==> Done!"
echo ""
echo "  API URL: $FUNC_URL"
echo ""
echo "==> Set this in your .env.local and EAS secrets:"
echo "    EXPO_PUBLIC_API_URL=$FUNC_URL"
