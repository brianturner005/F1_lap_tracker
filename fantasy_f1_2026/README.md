# Fantasy F1 2026

A web app for a small group (2–5 players) to predict full 22-driver race finishing orders across the 2026 F1 season, with cumulative points on a season leaderboard.

All data is stored server-side — players just open the URL to submit picks from any device.

## Features

- **Player management** — add named players to the league
- **Drag-and-drop picks** — arrange all 22 drivers in predicted finishing order per race
- **Admin result entry** — same drag-and-drop interface for the official result
- **Auto-scoring** — exact: 25 pts · ±1: 10 pts · ±2: 5 pts · ±3: 2 pts · ±4+: 0 pts
- **Season leaderboard** — total points ranked, with expandable per-race breakdowns
- **Server-side storage** — Azure Cosmos DB via Azure Functions; no local data

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Tailwind + @dnd-kit/sortable |
| API | Python Azure Functions (v2 model) |
| Database | Azure Cosmos DB (serverless) |
| Hosting | Azure Static Web Apps (Free tier) |

## Local Development

```bash
# Terminal 1 — frontend
npm install
npm run dev

# Terminal 2 — Functions API
cp api/local.settings.json.example api/local.settings.json
# Fill in COSMOS_CONNECTION_STRING in local.settings.json
cd api && func start
```

Frontend runs on [http://localhost:5173](http://localhost:5173); the dev proxy forwards `/api/*` to the Functions on port 7071.

## Deploy to Azure

### Prerequisites

```bash
# macOS
brew install azure-cli jq
npm install -g azure-functions-core-tools@4
az login

# Ubuntu/Debian
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
sudo apt install jq
npm install -g azure-functions-core-tools@4
az login
```

### One-command deploy

```bash
cd infra
chmod +x deploy.sh
./deploy.sh <resource-group> <azure-region> <github-owner/repo>
# e.g.: ./deploy.sh fantasy-f1-rg eastus brianturner005/fantasy_f1_2026
```

The script:
1. Creates the resource group
2. Deploys Cosmos DB + Azure Static Web App via Bicep
3. Wires `COSMOS_CONNECTION_STRING` into the Static Web App's settings
4. Prints your site URL and the `AZURE_STATIC_WEB_APPS_API_TOKEN` to add to GitHub secrets

After adding the secret, every push to `main` triggers a full redeploy via the included GitHub Actions workflow.

## Estimated Cost

| Resource | Cost |
|---|---|
| Azure Static Web Apps (Free tier) | $0/month |
| Cosmos DB (serverless, light use) | ~$0–1/month |
| **Total** | **~$0–1/month** |
