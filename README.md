# F1 Lap Tracker

A lightweight local lap time tracker for **F1 25** (and F1 24/23) on PC. Captures lap times, sector splits, and session data automatically via the game’s built-in UDP telemetry — no mods or third-party middleware required.

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
- **Community leaderboard** — opt-in feature to compare your track PBs with other players via a self-hosted Azure backend; top-25 panel in the dashboard
- **Browser dashboard** — works on your laptop or any device on the same local network

-----

## Requirements

- Python 3.8+
- Flask

```bash
pip install flask
```

> SQLite is part of Python’s standard library — no extra install needed.

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
python f1_lap_tracker.py
```

On first run a `f1_laps.db` file is created in the same directory. The console will print its full path.

### 3. Open the dashboard

Navigate to **http://localhost:5000** in any browser while the script is running.

-----

## Usage

Start the script before or after launching F1 25 — order doesn’t matter. Once the game starts broadcasting telemetry (typically when you enter a session), the dashboard status indicator will switch to **LIVE TELEMETRY** and laps will begin populating automatically.

### Buttons & controls

| Control | What it does |
|---|---|
| **Theme dropdown** | Switch between F1 default and all 10 team colour themes. Choice is remembered in the browser. |
| **Export CSV** | Download the current session’s laps as a `.csv` file. |
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

### Personal Bests panel

Above the Past Sessions panel, a **Personal Bests** table lists your all-time best lap for every track and session type you have driven. Records are keyed on track + session type, so a Monaco Qualifying PB and a Monaco Race PB are stored separately. The panel shows the time, tyre compound, and the date the record was set.

The **Session** panel also shows the current track’s all-time PB for quick reference while driving.

### Community Leaderboard panel

When the leaderboard is configured, a **Community Leaderboard** panel appears showing the top 25 times for the current track and session type. Your own time is highlighted. The panel refreshes automatically when you set a new PB or switch tracks.

Times are only submitted if you explicitly enable the **Leaderboard opt-in** toggle in the header. You can set a display name (defaults to `Anonymous`) that appears next to your times. Your identity is a randomly generated UUID stored locally in `f1_laps.db` — no account or email is required.

### Past Sessions panel

Below the Personal Bests panel, all previously recorded sessions are listed with their track, type, weather, and start/end times. Each row has a **CSV** link to download that session’s lap data directly.

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
| `/api/leaderboard` | GET | Proxy to the community leaderboard API (requires `F1_LEADERBOARD_URL`) |
| `/api/leaderboard/submit` | POST | Submit a PB to the community leaderboard |
| `/api/leaderboard/settings` | GET/POST | Get or update leaderboard opt-in and display name |

-----

## How It Works

F1 25 broadcasts UDP packets on your local network containing real-time telemetry data. This app runs two threads simultaneously:

- **UDP listener** on port `20777` — parses three packet types:
  - Packet ID 1 (Session Data) — track, session type, weather
  - Packet ID 2 (Lap Data) — lap times and sector splits
  - Packet ID 7 (Car Status) — tyre compound
- **HTTP server** on port `5000` — serves the dashboard and API endpoints; the browser polls `/api/state` every second

Each completed lap is written to `f1_laps.db` (SQLite) immediately. If the lap beats the all-time best for that track and session type, the `personal_bests` table is updated at the same time. A new session row is created the first time telemetry is received after startup or after a Clear Session.

If leaderboard submission is enabled, a background thread posts the new PB to the Azure Functions API. The leaderboard panel is refreshed after a successful submit, and also polls for updates when you change tracks.

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

Set the two variables printed by `deploy.sh` before starting the tracker:

```bash
export F1_LEADERBOARD_URL="https://<your-func>.azurewebsites.net/api"
export F1_LEADERBOARD_KEY="<your-function-key>"
python F1_lap_tracker.py
```

Or on Windows (PowerShell):

```powershell
$env:F1_LEADERBOARD_URL = "https://<your-func>.azurewebsites.net/api"
$env:F1_LEADERBOARD_KEY = "<your-function-key>"
python F1_lap_tracker.py
```

Once the variables are set:
1. Open the dashboard at `http://localhost:5000`
2. Enter a display name in the header (optional, defaults to `Anonymous`)
3. Toggle **Leaderboard opt-in** to start sharing your PBs

### Estimated Azure cost

Using serverless/consumption tiers throughout:

| Resource | Free tier covers | Estimated monthly cost |
|---|---|---|
| Cosmos DB (serverless) | 1 000 RU/s, 25 GB | ~$0–$1 for light use |
| Azure Functions (Y1) | 1M executions/month | Free for light use |
| Storage Account | First 5 GB | < $0.10 |
| **Total** | | **< $2/month** for a small group |

-----

## Troubleshooting

**Dashboard shows “Waiting for telemetry…”**

- Confirm UDP Telemetry is set to **On** in-game
- Confirm the IP is `127.0.0.1` and port is `20777`
- Make sure you’re in an active session (not the main menu)

**Track name shows “Track [number]” or sector times look wrong**

- Codemasters occasionally adjusts packet offsets between game releases. Try switching the in-game UDP Format between 2023 and 2024 if both options are available. The packet parser may need a minor offset tweak for new game versions.

**Port already in use**

- Another app (SimHub, Crew Chief, etc.) may already be listening on port `20777`. Close it, or configure F1 25 to send to a different port and update the `bind` call in the script accordingly.

-----

## Notes

- This app is built for **F1 25** but is compatible with F1 2023 and F1 2024 using the same UDP format.
- Console versions (PlayStation, Xbox) can also broadcast telemetry to a PC on the same network — set the UDP IP to your PC’s local IP instead of `127.0.0.1` and ensure both devices are on the same network.
- No data is sent externally unless you explicitly deploy the optional Azure leaderboard backend and enable the opt-in toggle. The tracker works fully offline without it.