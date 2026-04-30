#!/usr/bin/env bash
# Usage: ./deploy.sh <resource-group> <azure-region> [github-owner/repo]
# Example: ./deploy.sh fantasy-f1-rg eastus brianturner005/fantasy_f1_2026
set -euo pipefail

RESOURCE_GROUP="${1:?Usage: $0 <resource-group> <azure-region> [github-owner/repo]}"
LOCATION="${2:?Usage: $0 <resource-group> <azure-region> [github-owner/repo]}"
GITHUB_REPO="${3:-}"

echo "==> Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "==> Deploying Bicep template..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters baseName=fantasy-f1 location="$LOCATION" githubRepo="$GITHUB_REPO" \
  --output json)

SITE_URL=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.staticWebAppUrl.value')
DEPLOY_TOKEN=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.deploymentToken.value')

echo ""
echo "==> Deployment complete!"
echo ""
echo "  Site URL:  $SITE_URL"
echo ""
echo "==> Add this secret to your GitHub repo:"
echo "    Name:  AZURE_STATIC_WEB_APPS_API_TOKEN"
echo "    Value: $DEPLOY_TOKEN"
echo ""
echo "    GitHub → Settings → Secrets and variables → Actions → New repository secret"
