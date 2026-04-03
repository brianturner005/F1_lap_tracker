# Pitwall IQ

A lightweight local lap time tracker for **F1 25** (and F1 24/23) on PC. Captures lap times, sector splits, and session data automatically via the game's built-in UDP telemetry — no mods or third-party middleware required.

-----

## Features

- **Auto-capture** — lap times recorded the instant you cross the finish line
- **Sector splits** — S1, S2, and S3 times per lap
- **Best lap tracking** — personal best highlighted in gold with delta for every other lap
- **Invalid lap flagging** — track limits violations marked clearly
- **Session info** — track name, session type (Race, Qualifying, Practice, etc.), and weather pulled live from telemetry
- **Session storage** — every session and lap is automatically saved to a local SQLite database (`f1_laps.db`) so your data persists between runs
- **Past sessions panel** — browse all previous sessions directly in the dashboard
- **CSV export** — download the current session or any past session as a CSV file
- **Team themes** — choose a colour theme for all 10 F1 2025 constructors from a dropdown in the header; preference is saved in the browser
- **Tyre compound tracking** — compound (Soft/Medium/Hard/Inter/Wet) recorded per lap with colour-coded pills in the lap table
- **Personal bests** — all-time best lap per track and session type stored in the database; persists across restarts and sessions
- **AI lap debrief** — opt-in feature that sends your session data to Azure OpenAI and returns a race-engineer-style written debrief covering pace, sectors, tyres, and recommendations
- **Community leaderboard** — opt-in feature to compare your track PBs with other players via a self-hosted Azure backend; top-25 panel in the dashboard
- **Browser dashboard** — works on your laptop or any device on the same local network

-----

## Requirements

- Python 3.8+

No third-party packages required — everything uses the Python standard library.

> SQLite is part of Python's standard library. The optional AI debrief and community leaderboard features use `urllib` (also stdlib) to call Azure.

-----

## Setup

### 1. In-game telemetry (one-time)

In F1 25, go to **Settings → Telemetry Settings** and configure:

|Setting       |Value         |
|--------------|--------------|
|UDP Telemetry |**On**        |
|UDP Format    |**2025**      |
|UDP IP Address|**127.0.0.1** |
|UDP Port      |**20777**     |
|Broadcast Mode|**Off**       |

### 2. Run the tracker

```bash
python F1_lap_tracker.py
```

On first run a `f1_laps.db` file is created in the same directory. The console will print its full path.

### 3. Open the dashboard

Navigate to **http://localhost:5000** in any browser while the script is running.

-----

## Usage

Start the script before or after launching F1 25 — order doesn't matter. Once the game starts broadcasting telemetry (typically when you enter a session), the dashboard status indicator will switch to **LIVE TELEMETRY** and laps will begin populating automatically.

### Buttons & controls

| Control | What it does |
|---|---|
| **Theme dropdown** | Switch between F1 default and all 10 team colour themes. Choice is remembered in the browser. |
| **AI Debrief** | Request a race-engineer debrief from Azure OpenAI for the current session (shown only when AI is configured). |
| **Export CSV** | Download the current session's laps as a `.csv` file. |
| **Clear Session** | Resets the live lap table and starts a fresh session in the database. Previous session data is kept. |
| **Leaderboard toggle** | Enable or disable sharing your PBs with the community leaderboard (opt-in only). |
| **Display name** | Set the name shown next to your times on the community leaderboard. |

### Lap table

Each lap row shows:

| Column | Description |
|---|---|
| **LAP** | Lap number |
| **TYRE** | Compound pill — `S` Soft (red), `M` Medium (yellow), `H` Hard (white), `I` Inter (green), `W` Wet (blue) |
| **TIME** | Lap time. `★` = session best. `🏆` = new all-time track PB. |
| **DELTA** | Gap to track PB (purple `PB!` if this lap set a new record); falls back to session best if no prior PB exists for the track |
| **S1 / S2 / S3** | Sector split times |

### AI Debrief panel

When Azure OpenAI is configured, an **AI DEBRIEF** button appears in the header. Click it at any point during or after a session to get a written debrief styled like a race engineer briefing. The debrief covers:

- Overall pace and consistency
- Sector-by-sector weaknesses
- Tyre compound performance across the stint
- Best lap analysis
- One actionable recommendation for the next session

The panel appears below the leaderboard and can be dismissed at any time. Generating a debrief takes a few seconds while the model processes your lap data.

### Personal Bests panel

A **Personal Bests** table lists your all-time best lap for every track and session type you have driven. Records are keyed on track + session type, so a Monaco Qualifying PB and a Monaco Race PB are stored separately. The panel shows the time, tyre compound, and the date the record was set.

The **Session** panel also shows the current track's all-time PB for quick reference while driving.

### Community Leaderboard panel

When the leaderboard is configured, a **Community Leaderboard** panel appears showing the top 25 times for the current track and session type. Your own time is highlighted. The panel refreshes automatically when you set a new PB or switch tracks.

Times are only submitted if you explicitly enable the **Leaderboard opt-in** toggle in the header. You can set a display name (defaults to `Anonymous`) that appears next to your times. Your identity is a randomly generated UUID stored locally in `f1_laps.db` — no account or email is required.

### Past Sessions panel

All previously recorded sessions are listed with their track, type, weather, and start/end times. Each row has a **CSV** link to download that session's lap data directly.

### CSV format

Exported files contain one row per lap with the following columns:

```
Lap, Tyre, Time, S1 (ms), S2 (ms), S3 (ms), Invalid, Timestamp
```

-----

## API Endpoints

The app exposes a small REST API you can query directly:

| Endpoint | Method | Description |
|---|---|---|
| `/api/state` | GET | Current live session state as JSON |
| `/api/sessions` | GET | All past sessions as JSON |
| `/api/pbs` | GET | All-time personal bests per track as JSON |
| `/api/export` | GET | Current session laps as CSV download |
| `/api/sessions/<id>/export` | GET | Past session laps as CSV download |
| `/api/clear` | POST | Clear the current session |
| `/api/ai-config` | GET | Returns `{"enabled": bool}` — whether AI debrief is configured |
| `/api/debrief` | POST | Generate an AI debrief for the current session |
| `/api/leaderboard` | GET | Proxy to the community leaderboard API (requires `F1_LEADERBOARD_URL`) |
| `/api/lb-settings` | POST | Update leaderboard opt-in and display name |

-----

## How It Works

F1 25 broadcasts UDP packets on your local network containing real-time telemetry data. This app runs two threads simultaneously:

- **UDP listener** on port `20777` — parses three packet types:
  - Packet ID 1 (Session Data) — track, session type, weather
  - Packet ID 2 (Lap Data) — lap times and sector splits
  - Packet ID 7 (Car Status) — tyre compound
- **HTTP server** on port `5000` — serves the dashboard and API endpoints; the browser polls `/api/state` every second

Each completed lap is written to `f1_laps.db` (SQLite) immediately. If the lap beats the all-time best for that track and session type, the `personal_bests` table is updated at the same time.

-----

## AI Lap Debrief (optional)

The AI debrief feature uses **Azure OpenAI** to generate a post-session analysis. No data leaves your machine unless you configure this feature.

### What you need in Azure

1. An **Azure OpenAI** resource
2. A **model deployment** (GPT-4o recommended) within that resource

See [Deploying to Azure](#deploying-to-azure) below for step-by-step instructions.

### Configure the tracker

Set these three environment variables before starting the tracker:

**Linux / macOS:**
```bash
export AZURE_OPENAI_ENDPOINT="https://<your-resource-name>.openai.azure.com"
export AZURE_OPENAI_KEY="<your-api-key>"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"   # or your deployment name
python F1_lap_tracker.py
```

**Windows (PowerShell):**
```powershell
$env:AZURE_OPENAI_ENDPOINT = "https://<your-resource-name>.openai.azure.com"
$env:AZURE_OPENAI_KEY      = "<your-api-key>"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
python F1_lap_tracker.py
```

Once set, the **AI DEBRIEF** button will appear in the dashboard header.

### Estimated cost

A single debrief call sends roughly 500–800 tokens and receives ~400 tokens back.

| Model | Cost per debrief (approx) |
|---|---|
| GPT-4o | ~$0.005 |
| GPT-4o mini | ~$0.0003 |

For casual use (a few sessions a week) the monthly cost is a few cents. GPT-4o mini is a perfectly capable choice if you want to minimise cost.

-----

## Community Leaderboard (optional)

The community leaderboard is an **opt-in** feature backed by a self-hosted Azure Functions API + Cosmos DB. You must deploy the backend yourself — the tracker will work perfectly without it.

### Architecture

```
F1 25 UDP → F1_lap_tracker.py → f1_laps.db (local)
                              ↓ (on new PB, if opted in)
                   Azure Functions (leaderboard_api/)
                              ↓
                   Azure Cosmos DB (NoSQL, serverless)
                              ↑
              /api/leaderboard proxy (browser → localhost)
```

### Deploy the backend

Requirements: Azure CLI, Azure Functions Core Tools, `jq`.

```bash
cd infra
chmod +x deploy.sh
./deploy.sh <resource-group-name> <azure-region>
# e.g.: ./deploy.sh f1tracker-rg eastus
```

The script will:
1. Create the resource group
2. Deploy Cosmos DB, Function App, and Storage Account via Bicep
3. Publish the Python Azure Function
4. Print the two environment variables you need

### Configure the tracker

```bash
export F1_LEADERBOARD_URL="https://<your-func>.azurewebsites.net/api"
export F1_LEADERBOARD_KEY="<your-function-key>"
python F1_lap_tracker.py
```

Once set:
1. Open the dashboard at `http://localhost:5000`
2. Enter a display name in the header (optional, defaults to `Anonymous`)
3. Toggle **Leaderboard opt-in** to start sharing your PBs

### Who needs to deploy

Only **one person** in your group needs to run the deploy. Everyone else just sets the same `F1_LEADERBOARD_URL` and `F1_LEADERBOARD_KEY` values the host shares with them — no Azure account required for participants.

### Estimated Azure cost

| Resource | Estimated monthly cost |
|---|---|
| Cosmos DB (serverless) | ~$0–$1 for light use |
| Azure Functions (Y1/consumption) | Free for light use |
| Storage Account | < $0.10 |
| **Total** | **< $2/month** for a small group |

-----

## Deploying to Azure

### Prerequisites

Install the following tools:

| Tool | Install |
|---|---|
| Azure CLI | https://learn.microsoft.com/en-us/cli/azure/install-azure-cli |
| Azure Functions Core Tools | `npm install -g azure-functions-core-tools@4` |
| `jq` (Linux/macOS) | `sudo apt install jq` / `brew install jq` |

Log in to Azure:
```bash
az login
```

---

### Option A — AI Debrief only (Azure OpenAI)

This is the simpler option. No infrastructure files needed — just two Azure portal clicks.

**Step 1: Create an Azure OpenAI resource**

1. Go to the [Azure Portal](https://portal.azure.com) → **Create a resource** → search **Azure OpenAI**
2. Fill in:
   - **Subscription**: your subscription
   - **Resource group**: create new, e.g. `pitwall-iq-rg`
   - **Region**: pick one that has GPT-4o availability (e.g. `East US`, `Sweden Central`)
   - **Name**: e.g. `pitwall-iq-openai`
   - **Pricing tier**: Standard S0
3. Click **Review + Create** → **Create**

> Azure OpenAI requires capacity approval in some regions. East US and Sweden Central typically have GPT-4o available immediately.

**Step 2: Deploy a model**

1. Once the resource is created, open it and click **Go to Azure OpenAI Studio** (or navigate to `https://oai.azure.com`)
2. Click **Deployments** → **+ Deploy model**
3. Select **gpt-4o** (or **gpt-4o-mini** for lower cost)
4. Set a **Deployment name** — this is your `AZURE_OPENAI_DEPLOYMENT` value (e.g. `gpt-4o`)
5. Click **Deploy**

**Step 3: Get your credentials**

Back in the Azure Portal, open your OpenAI resource:
- **Endpoint**: shown on the Overview page — copy the URL (e.g. `https://pitwall-iq-openai.openai.azure.com`)
- **API Key**: go to **Keys and Endpoint** → copy **KEY 1**

**Step 4: Set the environment variables**

```bash
export AZURE_OPENAI_ENDPOINT="https://pitwall-iq-openai.openai.azure.com"
export AZURE_OPENAI_KEY="<KEY 1 from portal>"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
python F1_lap_tracker.py
```

The **AI DEBRIEF** button will now appear in the dashboard.

---

### Option B — Community Leaderboard (Azure Functions + Cosmos DB)

Run the automated deploy script included in this repo:

```bash
cd infra
chmod +x deploy.sh
./deploy.sh pitwall-iq-rg eastus
```

This deploys everything via Bicep (Cosmos DB, Function App, Storage Account) and prints the two env vars you need. Share those with friends and everyone can see the same leaderboard.

---

### Option C — Both AI Debrief and Community Leaderboard

Deploy Option B first (which creates a resource group), then create the Azure OpenAI resource in the same resource group via the portal (Option A, Step 1 — choose the existing resource group). Set all five environment variables before starting the tracker.

-----

## Troubleshooting

**Dashboard shows "Waiting for telemetry…"**

- Confirm UDP Telemetry is set to **On** in-game
- Confirm the IP is `127.0.0.1` and port is `20777`
- Make sure you're in an active session (not the main menu)

**AI Debrief button doesn't appear**

- Check that `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_KEY` are set in the same terminal you started the tracker from
- The endpoint must start with `https://` and end with `.openai.azure.com`
- Confirm your model deployment name matches `AZURE_OPENAI_DEPLOYMENT` exactly (case-sensitive)

**AI Debrief returns an error**

- `AuthenticationError` — API key is wrong or expired; regenerate it in the portal under **Keys and Endpoint**
- `DeploymentNotFound` — your `AZURE_OPENAI_DEPLOYMENT` name doesn't match what's in Azure OpenAI Studio
- `RateLimitError` — you've hit the model's token-per-minute quota; wait a moment and try again

**Track name shows "Track [number]" or sector times look wrong**

- Codemasters occasionally adjusts packet offsets between game releases. Try switching the in-game UDP Format between 2023 and 2024 if both options are available.

**Port already in use**

- Another app (SimHub, Crew Chief, etc.) may already be listening on port `20777`. Close it, or configure F1 25 to send to a different port and update the `bind` call in the script accordingly.

-----

## Notes

- This app is built for **F1 25** but is compatible with F1 2023 and F1 2024 using the same UDP format.
- Console versions (PlayStation, Xbox) can also broadcast telemetry to a PC on the same network — set the UDP IP to your PC's local IP instead of `127.0.0.1` and ensure both devices are on the same network.
- No data is sent externally unless you configure the optional Azure features. The tracker works fully offline without them.
