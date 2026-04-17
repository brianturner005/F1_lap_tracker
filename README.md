# Pitwall IQ

A lightweight local lap time tracker for **F1 25** (and F1 24/23) on PC. Captures lap times, sector splits, live telemetry, and race results automatically via the game's built-in UDP telemetry — no mods or third-party middleware required.

-----

## Features

- **Auto-capture** — lap times recorded the instant you cross the finish line
- **Sector splits** — S1, S2, and S3 times per lap with mini-best highlighting (best sector per session highlighted purple)
- **Best lap tracking** — personal best highlighted in gold with delta for every other lap
- **Invalid lap flagging** — track limits violations marked clearly
- **Session info** — track name, session type (Race, Qualifying, Practice, etc.), and weather pulled live from telemetry
- **Session storage** — every session and lap is automatically saved to a local SQLite database (`f1_laps.db`) so your data persists between runs
- **Toast notifications** — pop-up alerts for new track PBs and sector bests
- **Lap comparison overlay** — select any two laps from the table to compare their speed, inputs, and G-force side-by-side
- **Live track map** — animated car position with sector colouring or speed heatmap; browse any previous lap with the arrow navigation
- **Live telemetry charts** — speed trace, throttle & brake inputs, and a G-force circle updated in real time
- **Career stats tab** — tracks race results (position, points, grid, fastest lap) across every session; shows wins, podiums, points total, and DNFs
- **Past sessions panel** — browse all previous sessions directly in the dashboard (collapsible)
- **CSV export** — download the current session or any past session as a CSV file
- **Team themes** — choose a colour theme for all 10 F1 2025 constructors from a dropdown in the header; preference is saved in the browser
- **Tyre compound tracking** — compound (Soft/Medium/Hard/Inter/Wet) recorded per lap with colour-coded pills in the lap table
- **Personal bests** — all-time best lap per track and session type stored in the database; persists across restarts and sessions (collapsible)
- **AI lap debrief** — click AI DEBRIEF at any time to get a race-engineer-style written analysis of your session; built-in, no API key required (10 debriefs/day)
- **Community leaderboard** — compare your track PBs with other Pitwall IQ users; built-in, no configuration required
- **One-click launchers** — double-click to start on Windows, macOS, or Linux; browser opens automatically
- **Browser dashboard** — works on your laptop or any device on the same local network

-----

## Requirements

- Python 3.8+

No third-party packages required — everything uses the Python standard library.

> SQLite is part of Python's standard library. The AI debrief and community leaderboard features use `urllib` (also stdlib) to communicate with the shared Pitwall IQ backend.

-----

## Quick Start

### 1. In-game telemetry (one-time)

In F1 25, go to **Settings → Telemetry Settings** and configure:

| Setting        | Value         |
|----------------|---------------|
| UDP Telemetry  | **On**        |
| UDP Format     | **2025**      |
| UDP IP Address | **127.0.0.1** |
| UDP Port       | **20777**     |
| Broadcast Mode | **Off**       |

### 2. Launch the app

**Windows** — double-click `launch_windows.bat`

**macOS** — run once to set up, then double-click to launch every time:
```bash
bash setup_shortcut.sh
```
Then double-click `launch_mac.command` in Finder. (First launch: right-click → Open if macOS blocks it.)

**Linux** — run once to install a desktop shortcut, then launch from your app menu:
```bash
bash setup_shortcut.sh
```
Or just run directly:
```bash
python3 F1_lap_tracker.py
```

All launchers automatically open **http://localhost:5000** in your default browser once the server is ready.

-----

## Usage

Start the launcher before or after launching F1 25 — order doesn't matter. Once the game starts broadcasting telemetry (typically when you enter a session), the dashboard status indicator will switch to **LIVE TELEMETRY** and data will begin populating automatically.

### Header controls

| Control | What it does |
|---|---|
| **Theme dropdown** | Switch between F1 default and all 10 team colour themes. Choice is remembered in the browser. |
| **AI DEBRIEF** | Request a race-engineer debrief for the current session. Built-in — no configuration needed. |
| **Export CSV** | Download the current session's laps as a `.csv` file. |
| **Clear Session** | Resets the live lap table and starts a fresh session in the database. Previous session data is kept. |
| **SUBMIT PBs toggle** | Enable or disable sharing your PBs with the community leaderboard (opt-in only). |
| **Display name** | Set the name shown next to your times on the community leaderboard. |

### Session tab

The default view. Shows the live lap table, telemetry charts, track map, personal bests, and past sessions.

#### Lap table

Each lap row shows:

| Column | Description |
|---|---|
| **LAP** | Lap number. Click any row to select it for lap comparison (slots A or B). |
| **TYRE** | Compound pill — `S` Soft (red), `M` Medium (yellow), `H` Hard (white), `I` Inter (green), `W` Wet (blue) |
| **TIME** | Lap time. `★` = session best. `🏆` = new all-time track PB. |
| **DELTA** | Gap to track PB (purple `PB!` if this lap set a new record); falls back to session best if no prior PB exists |
| **S1 / S2 / S3** | Sector split times. Best sector each session is highlighted with a purple cell background. |

#### Telemetry charts

Displayed below the lap table. Updated live every 250 ms:

- **Speed trace** — km/h across the lap distance, coloured by sector
- **Throttle & Brake** — green = throttle, red = brake input (0–100%)
- **G-Force circle** — lateral vs. longitudinal G, dots coloured by sector; inner ring = 2G reference

Use the track map **← →** buttons to review any previous lap's telemetry. In **comparison mode**, the selected lap (A) is shown in blue/green/red on top of the reference lap (B) in orange/amber.

#### Track map

Live animated car position plotted from motion telemetry. Two display modes:

| Mode | Description |
|---|---|
| **S1/S2/S3** | Trace coloured by sector (blue/yellow/red) |
| **SPEED** | Heatmap from slow (blue) to fast (red) |

Use the **← →** arrows beneath the map to step through previous laps. Click **LIVE** to return to the real-time view.

#### Lap comparison

Click a lap row to assign it to slot **A**, then click another to assign slot **B**. The comparison bar shows both lap numbers and the telemetry panel switches to overlay mode. Click **CLEAR** to exit comparison and return to live view.

#### Personal Bests panel

Lists your all-time best lap for every track and session type you have driven. Records are keyed on track + session type (Monaco Qualifying and Monaco Race are separate). Shows time, tyre compound, and date. Collapsible.

#### Past Sessions panel

All previously recorded sessions with their track, type, weather, and start/end times. Each row has a **CSV** link to download that session's lap data directly. Collapsible.

### Career tab

Click **CAREER** in the tab bar to switch to the career view. Shows a summary across all your race sessions:

| Stat | Description |
|---|---|
| **Races** | Total race sessions finished |
| **Wins** | P1 finishes |
| **Podiums** | Top 3 finishes |
| **Points** | Cumulative points scored |
| **Fast Laps** | Fastest lap awards |
| **DNFs** | Did Not Finish count |

Below the summary, a full results table lists every race with grid position, finishing position (gold/silver/bronze coloured), points, and best lap. An **FL** badge marks races where you set the fastest lap.

A toast notification appears automatically when a race result is recorded (e.g. *Race finished: P3 · 15 pts*).

### AI Debrief panel

Click **AI DEBRIEF** in the header at any point during or after a session. The debrief covers:

- Overall pace and consistency
- Sector-by-sector weaknesses
- Tyre compound performance across the stint
- Best lap analysis
- One actionable recommendation for the next session

The debrief is generated via a shared backend — no API key or Azure account needed. Limit is 10 debriefs per player per day. The panel can be dismissed at any time.

### Community Leaderboard panel

Shown in the sidebar beneath the track map. Displays the top 25 times for the current track and session type. Your own time is highlighted. The panel refreshes automatically when you set a new PB or switch tracks.

Times are only submitted if you explicitly enable the **SUBMIT PBs** toggle. You can set a display name (defaults to `Anonymous`). Your identity is a randomly generated UUID stored locally in `f1_laps.db` — no account or email is required.

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
| `/api/career` | GET | Career stats summary and race results history |
| `/api/export` | GET | Current session laps as CSV download |
| `/api/sessions/<id>/export` | GET | Past session laps as CSV download |
| `/api/lap-trace/<sid>/<lap>` | GET | Raw trace data for a specific lap |
| `/api/clear` | POST | Clear the current session |
| `/api/ai-config` | GET | Returns `{"enabled": bool}` — whether AI debrief is available |
| `/api/debrief` | POST | Generate an AI debrief for the current session |
| `/api/leaderboard` | GET | Proxy to the community leaderboard API |
| `/api/lb-settings` | POST | Update leaderboard opt-in and display name |

-----

## How It Works

F1 25 broadcasts UDP packets on your local network containing real-time telemetry data. This app runs two threads simultaneously:

- **UDP listener** on port `20777` — parses six packet types:
  - Packet ID 0 (Motion) — car position (X/Z) and G-forces for the track map and G-force circle
  - Packet ID 1 (Session Data) — track, session type, weather
  - Packet ID 2 (Lap Data) — lap times and sector splits
  - Packet ID 3 (Event) — fastest lap detection (FTLP event)
  - Packet ID 6 (Car Telemetry) — speed, throttle, brake, and gear for telemetry charts
  - Packet ID 7 (Car Status) — tyre compound
  - Packet ID 8 (Final Classification) — race finishing position, points, and result status
- **HTTP server** on port `5000` — serves the dashboard and API endpoints; the browser polls `/api/state` every second

Each completed lap is written to `f1_laps.db` (SQLite) immediately. If the lap beats the all-time best for that track and session type, the `personal_bests` table is updated at the same time. When a Final Classification packet arrives at the end of a race, the result is written to the `race_results` table.

-----

## AI Lap Debrief

The AI debrief feature is built in and works out of the box — no Azure account or API key required. Each player gets 10 debriefs per UTC day via the shared Pitwall IQ backend.

If you want to host your own backend (unlimited debriefs, your own OpenAI deployment), see [HOSTING.md](HOSTING.md).

-----

## Community Leaderboard

The community leaderboard is built in and works out of the box — no configuration required. Toggle **SUBMIT PBs** in the header to start sharing your times. Your PBs are only submitted when you explicitly opt in.

If you want to host a private leaderboard for your own group, see [HOSTING.md](HOSTING.md).

-----

## Troubleshooting

**Dashboard shows "Waiting for telemetry…"**

- Confirm UDP Telemetry is set to **On** in-game
- Confirm the IP is `127.0.0.1` and port is `20777`
- Make sure you're in an active session (not the main menu)

**AI Debrief button doesn't appear**

- The button shows only when at least one lap has been recorded in the current session
- If it still doesn't appear, check the browser console for errors — the `/api/ai-config` endpoint should return `{"enabled": true}`

**AI Debrief returns an error**

- `429 Too Many Requests` — you've used all 10 debriefs for today; resets at midnight UTC
- Other errors — check your internet connection; the shared backend requires outbound HTTPS access

**Track name shows "Track [number]" or sector times look wrong**

- Codemasters occasionally adjusts packet offsets between game releases. Try switching the in-game UDP Format to 2023 or 2024 if 2025 gives incorrect data.

**Port already in use**

- Another app (SimHub, Crew Chief, etc.) may already be listening on port `20777`. Close it, or configure F1 25 to send to a different port and update the `bind` call in the script accordingly.

**macOS says "launch_mac.command cannot be opened"**

- Right-click the file in Finder and choose **Open**, then confirm in the dialog. You only need to do this once.

-----

## Notes

- This app is built for **F1 25** but is compatible with F1 2023 and F1 2024 using the same UDP format.
- Console versions (PlayStation, Xbox) can also broadcast telemetry to a PC on the same network — set the UDP IP to your PC's local IP instead of `127.0.0.1` and ensure both devices are on the same network.
- No lap or session data is sent externally unless you enable the leaderboard opt-in toggle. The AI debrief sends only session metadata and lap times (no personal information) to the shared backend.
