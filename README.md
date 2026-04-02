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
- **Clear session** — reset between stints without restarting the script
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

### Past Sessions panel

Below the lap table, all previously recorded sessions are listed with their track, type, weather, and start/end times. Each row has a **CSV** link to download that session’s lap data directly.

### CSV format

Exported files contain one row per lap with the following columns:

```
Lap, Time, S1 (ms), S2 (ms), S3 (ms), Invalid, Timestamp
```

-----

## API Endpoints

The app exposes a small REST API you can query directly:

| Endpoint | Method | Description |
|---|---|---|
| `/api/state` | GET | Current live session state as JSON |
| `/api/sessions` | GET | All past sessions as JSON |
| `/api/export` | GET | Current session laps as CSV download |
| `/api/sessions/<id>/export` | GET | Past session laps as CSV download |
| `/api/clear` | POST | Clear the current session |

-----

## How It Works

F1 25 broadcasts UDP packets on your local network containing real-time telemetry data. This app runs two threads simultaneously:

- **UDP listener** on port `20777` — parses incoming packets for session data (Packet ID 1) and lap data (Packet ID 2)
- **HTTP server** on port `5000` — serves the dashboard and API endpoints; the browser polls `/api/state` every second

Each completed lap is written to `f1_laps.db` (SQLite) immediately. A new session row is created the first time telemetry is received after startup or after a Clear Session.

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
- No data is sent externally. Everything runs locally.