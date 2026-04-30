# Fantasy F1 2026

A web app for a small group (2–5 players) to predict full 22-driver race finishing orders across the 2026 F1 season, with cumulative points on a season leaderboard.

## Features

- **Player management** — add named players to the league
- **Drag-and-drop picks** — arrange all 22 drivers in predicted finishing order per race
- **Admin result entry** — same drag-and-drop interface for the official result
- **Auto-scoring** — exact position: 25 pts · ±1: 10 pts · ±2: 5 pts · ±3: 2 pts · ±4+: 0 pts
- **Season leaderboard** — total points ranked, with expandable per-race breakdowns
- **F1-themed dark UI** — black/red, all 11 team colours
- **localStorage persistence** — no backend or account required

## 2026 Driver Lineup

22 drivers across 11 teams: McLaren, Mercedes, Red Bull, Ferrari, Aston Martin, Williams, Racing Bulls, Haas, Alpine, Audi, Cadillac.

## Local Development

```bash
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Hosting on Azure Static Web Apps

### One-time setup (Azure Portal)

1. Push this repo to GitHub
2. Go to **Azure Portal → Create a resource → Static Web App**
3. Fill in:
   - **Name**: `fantasy-f1-2026` (or similar)
   - **Plan type**: Free
   - **Deployment source**: GitHub — connect your account and select this repo + `main` branch
   - **Build preset**: React
   - **App location**: `/`
   - **Output location**: `dist`
4. Click **Review + create**

Azure generates a `AZURE_STATIC_WEB_APPS_API_TOKEN` secret in your GitHub repo automatically and triggers the first deployment via the included workflow at `.github/workflows/azure-static-web-apps.yml`.

After that, every push to `main` redeploys automatically.

### Estimated cost

| Resource | Cost |
|---|---|
| Azure Static Web Apps (Free tier) | **$0/month** |

---

## Upgrading to shared state (optional)

localStorage is per-browser, so players on separate devices won't see each other's picks. To share state across devices, add an Azure Functions API + Cosmos DB:

1. Create an `api/` folder alongside `src/` with Azure Functions endpoints for picks, results, and players
2. Uncomment `api_location: "api"` in the GitHub Actions workflow — Azure Static Web Apps deploys managed functions automatically
3. Swap the `storage.js` utility calls from localStorage to `fetch('/api/...')` calls
4. Provision Cosmos DB (serverless, ~$0–1/month for light use) — you can reuse an existing Cosmos DB account if you already have one

Total estimated cost for the full stack: **~$0–1/month**.
