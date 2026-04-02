#!/usr/bin/env python3
"""
F1 25 Lap Time Tracker

Listens for F1 25 UDP telemetry on port 20777 and serves a live
dashboard at http://localhost:5000

In-game setup (one time):
Settings → Telemetry Settings
UDP Telemetry   : On
UDP Format      : 2023  (or 2024 if listed)
UDP IP Address  : 127.0.0.1
UDP Port        : 20777
Broadcast Mode  : Off

Run:
python f1_lap_tracker.py

Then open http://localhost:5000 in your browser.

Requirements:
pip install flask
"""

import struct
import socket
import threading
import json
import time
import sqlite3
import csv
import io
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

# ── Shared state ─────────────────────────────────────────────────────────────

state_lock = threading.Lock()
state = {
    "session": {
        "track": "Unknown",
        "session_type": "Unknown",
        "weather": "Unknown",
        "started_at": None,
    },
    "current_lap": 1,
    "best_lap_ms": None,
    "best_lap_num": None,
    "laps": [],          # list of lap dicts
    "last_sector": [None, None, None],  # current lap sector times ms
    "session_history": [],   # past sessions
    "current_session_id": None,
    "current_compound": None,
    "track_pb_ms": None,
    "track_pb_time": None,
    "track_pb_compound": None,
    "udp_connected": False,
    "player_position": 0,
    "total_laps": 0,
}

TRACK_IDS = {
    0:"Melbourne", 1:"Paul Ricard", 2:"Shanghai", 3:"Sakhir (Bahrain)",
    4:"Catalunya", 5:"Monaco", 6:"Montreal", 7:"Silverstone", 8:"Hockenheim",
    9:"Hungaroring", 10:"Spa", 11:"Monza", 12:"Singapore", 13:"Suzuka",
    14:"Abu Dhabi", 15:"Texas (COTA)", 16:"Brazil", 17:"Austria",
    18:"Sochi", 19:"Mexico", 20:"Baku (Azerbaijan)", 21:"Sakhir Short",
    22:"Silverstone Short", 23:"Texas Short", 24:"Suzuka Short",
    25:"Hanoi", 26:"Zandvoort", 27:"Imola", 28:"Portimão", 29:"Jeddah",
    30:"Miami", 31:"Las Vegas", 32:"Lusail (Qatar)", 33:"Interlagos Short"
}

SESSION_TYPES = {
    0:"Unknown", 1:"Practice 1", 2:"Practice 2", 3:"Practice 3",
    4:"Short Practice", 5:"Qualifying 1", 6:"Qualifying 2", 7:"Qualifying 3",
    8:"Short Qualifying", 9:"OSQ", 10:"Race", 11:"Race 2",
    12:"Race 3", 13:"Time Trial"
}

WEATHER_IDS = {0:"Clear", 1:"Light Cloud", 2:"Overcast", 3:"Light Rain",
               4:"Heavy Rain", 5:"Storm"}

VISUAL_COMPOUNDS = {7:"Inter", 8:"Wet", 16:"Soft", 17:"Medium", 18:"Hard"}

# ── SQLite persistence ────────────────────────────────────────────────────────

DB_PATH = "f1_laps.db"

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            track        TEXT,
            session_type TEXT,
            weather      TEXT,
            started_at   TEXT,
            ended_at     TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS laps (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   INTEGER NOT NULL,
            lap_num      INTEGER,
            lap_time_ms  INTEGER,
            lap_time     TEXT,
            s1_ms        INTEGER,
            s2_ms        INTEGER,
            s3_ms        INTEGER,
            invalid      INTEGER,
            timestamp    TEXT,
            compound     TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS personal_bests (
            track        TEXT NOT NULL,
            session_type TEXT NOT NULL,
            lap_time_ms  INTEGER NOT NULL,
            lap_time     TEXT NOT NULL,
            compound     TEXT,
            set_at       TEXT,
            session_id   INTEGER,
            PRIMARY KEY (track, session_type)
        )
    """)
    # Migrations for existing databases
    for col in [
        "ALTER TABLE laps ADD COLUMN compound TEXT",
        "ALTER TABLE laps ADD COLUMN is_track_pb INTEGER DEFAULT 0",
    ]:
        try:
            con.execute(col)
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()

def db_create_session(track, session_type, weather, started_at):
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        "INSERT INTO sessions (track, session_type, weather, started_at) VALUES (?,?,?,?)",
        (track, session_type, weather, started_at)
    )
    session_id = cur.lastrowid
    con.commit()
    con.close()
    return session_id

def db_update_session(session_id, track, session_type, weather):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE sessions SET track=?, session_type=?, weather=? WHERE id=?",
        (track, session_type, weather, session_id)
    )
    con.commit()
    con.close()

def db_close_session(session_id):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE sessions SET ended_at=? WHERE id=?",
        (datetime.now().isoformat(), session_id)
    )
    con.commit()
    con.close()

def db_save_lap(session_id, lap):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO laps
           (session_id, lap_num, lap_time_ms, lap_time, s1_ms, s2_ms, s3_ms, invalid, timestamp, compound)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (session_id, lap["lap_num"], lap["lap_time_ms"], lap["lap_time"],
         lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], int(lap["invalid"]),
         lap["timestamp"], lap.get("compound"))
    )
    con.commit()
    con.close()

def db_get_track_pb(track, session_type):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM personal_bests WHERE track=? AND session_type=?",
        (track, session_type)
    ).fetchone()
    con.close()
    return dict(row) if row else None

def db_upsert_track_pb(track, session_type, lap_time_ms, lap_time, compound, session_id, set_at):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT OR REPLACE INTO personal_bests
           (track, session_type, lap_time_ms, lap_time, compound, session_id, set_at)
           VALUES (?,?,?,?,?,?,?)""",
        (track, session_type, lap_time_ms, lap_time, compound, session_id, set_at)
    )
    con.commit()
    con.close()

def db_get_all_pbs():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM personal_bests ORDER BY track, session_type"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def ms_to_laptime(ms):
    if ms is None or ms <= 0:
        return "–:–.—"
    total_sec = ms / 1000.0
    minutes = int(total_sec // 60)
    seconds = int(total_sec % 60)
    millis = int(ms % 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"

def delta_str(ms, best_ms):
    if ms is None or best_ms is None:
        return ""
    diff = ms - best_ms
    if diff == 0:
        return "BEST"
    sign = "+" if diff > 0 else "-"
    diff = abs(diff) / 1000.0
    return f"{sign}{diff:.3f}s"

# ── UDP Packet Parsing (F1 25 format) ────────────────────────────────────────

HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def parse_header(data):
    if len(data) < HEADER_SIZE:
        return None
    vals = struct.unpack_from(HEADER_FORMAT, data, 0)
    return {
        "packet_format": vals[0],
        "game_year": vals[1],
        "game_major": vals[2],
        "game_minor": vals[3],
        "packet_version": vals[4],
        "packet_id": vals[5],
        "session_uid": vals[6],
        "session_time": vals[7],
        "frame_id": vals[8],
        "overall_frame_id": vals[9],
        "player_car_index": vals[10],
        "secondary_player_car_index": vals[11],
    }

# Packet ID 1 – Session Data

def parse_session_packet(data, player_idx):
    try:
        # F1 25 PacketSessionData layout after header:
        # +0  weather (uint8)
        # +1  trackTemperature (int8)
        # +2  airTemperature (int8)
        # +3  totalLaps (uint8)
        # +4  trackLength (uint16)
        # +6  sessionType (uint8)
        # +7  trackId (int8, signed — -1 = unknown)
        base = HEADER_SIZE
        weather_val    = struct.unpack_from("<B", data, base + 0)[0]
        total_laps_val = struct.unpack_from("<B", data, base + 3)[0]
        session_type   = struct.unpack_from("<B", data, base + 6)[0]
        track_id       = struct.unpack_from("<b", data, base + 7)[0]  # signed

        track_name    = TRACK_IDS.get(track_id, f"Track {track_id}")
        weather_name  = WEATHER_IDS.get(weather_val, "Unknown")
        session_name  = SESSION_TYPES.get(session_type, "Unknown")

        create_session = False
        started_at = None
        current_session_id = None
        load_pb = False

        with state_lock:
            old_track        = state["session"]["track"]
            old_session_type = state["session"]["session_type"]
            state["session"]["weather"]      = weather_name
            state["session"]["session_type"] = session_name
            state["session"]["track"]        = track_name
            state["total_laps"]              = total_laps_val
            state["udp_connected"]           = True
            if state["session"]["started_at"] is None:
                started_at = datetime.now().isoformat()
                state["session"]["started_at"] = started_at
                create_session = True
            current_session_id = state["current_session_id"]
            # Reload PB whenever track or session type changes to a known value
            if track_name != "Unknown" and (track_name != old_track or session_name != old_session_type):
                load_pb = True

        if create_session:
            new_id = db_create_session(track_name, session_name, weather_name, started_at)
            with state_lock:
                state["current_session_id"] = new_id
        elif current_session_id is not None:
            db_update_session(current_session_id, track_name, session_name, weather_name)

        if load_pb:
            pb = db_get_track_pb(track_name, session_name)
            with state_lock:
                if pb:
                    state["track_pb_ms"]       = pb["lap_time_ms"]
                    state["track_pb_time"]     = pb["lap_time"]
                    state["track_pb_compound"] = pb.get("compound")
                else:
                    state["track_pb_ms"]       = None
                    state["track_pb_time"]     = None
                    state["track_pb_compound"] = None
    except Exception:
        pass

# Packet ID 2 – Lap Data

LAP_DATA_SIZE = 57  # F1 25 per-car lap data size

def parse_lap_data_packet(data, player_idx):
    try:
        base = HEADER_SIZE + (player_idx * LAP_DATA_SIZE)
        if len(data) < base + LAP_DATA_SIZE:
            return
        # F1 25 LapData layout:
        # +0  lastLapTimeInMS (uint32)
        # +4  currentLapTimeInMS (uint32)
        # +8  sector1TimeMSPart (uint16)
        # +10 sector1TimeMinutesPart (uint8)
        # +11 sector2TimeMSPart (uint16)
        # +13 sector2TimeMinutesPart (uint8)
        # +14 deltaToCarInFrontMSPart (uint16)
        # +16 deltaToCarInFrontMinutesPart (uint8)
        # +17 deltaToRaceLeaderMSPart (uint16)
        # +19 deltaToRaceLeaderMinutesPart (uint8)
        # +20 lapDistance (float)
        # +24 totalDistance (float)
        # +28 safetyCarDelta (float)
        # +32 carPosition (uint8)
        # +33 currentLapNum (uint8)
        # +34 pitStatus (uint8)
        # +35 numPitStops (uint8)
        # +36 sector (uint8)   0=s1, 1=s2, 2=s3
        # +37 currentLapInvalid (uint8)
        (last_lap_ms, cur_lap_ms,
         s1_ms, s1_min,
         s2_ms, s2_min) = struct.unpack_from("<IIHBHB", data, base)

        position    = struct.unpack_from("<B", data, base + 32)[0]
        cur_lap_num = struct.unpack_from("<B", data, base + 33)[0]
        sector      = struct.unpack_from("<B", data, base + 36)[0]  # 0=s1,1=s2,2=s3
        invalid     = struct.unpack_from("<B", data, base + 37)[0]

        s1_total_ms = s1_min * 60000 + s1_ms if s1_min >= 0 else s1_ms
        s2_total_ms = s2_min * 60000 + s2_ms if s2_min >= 0 else s2_ms

        save_session_id = None
        lap_record = None
        save_pb_data = None

        with state_lock:
            state["udp_connected"] = True
            state["player_position"] = position
            prev_lap = state["current_lap"]
            state["current_lap"] = cur_lap_num

            # New lap completed
            if last_lap_ms > 0 and cur_lap_num > prev_lap:
                lap_record = {
                    "lap_num": prev_lap,
                    "lap_time_ms": last_lap_ms,
                    "lap_time": ms_to_laptime(last_lap_ms),
                    "invalid": bool(invalid),
                    "s1_ms": s1_total_ms if s1_total_ms > 0 else None,
                    "s2_ms": s2_total_ms if s2_total_ms > 0 else None,
                    "s3_ms": (last_lap_ms - s1_total_ms - s2_total_ms) if (s1_total_ms > 0 and s2_total_ms > 0) else None,
                    "timestamp": datetime.now().isoformat(),
                    "compound": state["current_compound"],
                    "is_track_pb": False,
                }
                lap_record["s1"] = ms_to_laptime(lap_record["s1_ms"])
                lap_record["s2"] = ms_to_laptime(lap_record["s2_ms"])
                lap_record["s3"] = ms_to_laptime(lap_record["s3_ms"])

                state["laps"].append(lap_record)

                # Update session best (valid laps only)
                if not invalid and last_lap_ms > 10000:
                    if state["best_lap_ms"] is None or last_lap_ms < state["best_lap_ms"]:
                        state["best_lap_ms"] = last_lap_ms
                        state["best_lap_num"] = prev_lap

                    # Check & update track PB
                    if state["track_pb_ms"] is None or last_lap_ms < state["track_pb_ms"]:
                        state["track_pb_ms"]       = last_lap_ms
                        state["track_pb_time"]     = ms_to_laptime(last_lap_ms)
                        state["track_pb_compound"] = state["current_compound"]
                        lap_record["is_track_pb"]  = True
                        save_pb_data = (
                            state["session"]["track"],
                            state["session"]["session_type"],
                            last_lap_ms,
                            ms_to_laptime(last_lap_ms),
                            state["current_compound"],
                            state["current_session_id"],
                            datetime.now().isoformat(),
                        )

                save_session_id = state["current_session_id"]

            # Annotate all laps with delta (use track PB as reference when available)
            ref_ms = state["track_pb_ms"] if state["track_pb_ms"] is not None else state["best_lap_ms"]
            for lap in state["laps"]:
                if lap.get("is_track_pb"):
                    lap["delta"] = "PB!"
                else:
                    lap["delta"] = delta_str(lap["lap_time_ms"], ref_ms)
                lap["is_best"] = lap["lap_num"] == state["best_lap_num"]

        if save_session_id is not None:
            db_save_lap(save_session_id, lap_record)
        if save_pb_data is not None:
            db_upsert_track_pb(*save_pb_data)
    except Exception:
        pass

# Packet ID 7 – Car Status Data

CAR_STATUS_SIZE = 55  # F1 25 per-car car status size

def parse_car_status_packet(data, player_idx):
    try:
        # visualTyreCompound sits at byte +26 within each car's CarStatusData block
        base = HEADER_SIZE + (player_idx * CAR_STATUS_SIZE)
        if len(data) < base + CAR_STATUS_SIZE:
            return
        visual_compound = struct.unpack_from("<B", data, base + 26)[0]
        compound_name = VISUAL_COMPOUNDS.get(visual_compound)
        with state_lock:
            state["current_compound"] = compound_name
    except Exception:
        pass

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 20777))
    sock.settimeout(2.0)
    print("🎮  UDP listener active on port 20777")
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            header = parse_header(data)
            if not header:
                continue
            pid = header["packet_id"]
            pidx = header["player_car_index"]
            if pid == 1:
                parse_session_packet(data, pidx)
            elif pid == 2:
                parse_lap_data_packet(data, pidx)
            elif pid == 7:
                parse_car_status_packet(data, pidx)
        except socket.timeout:
            pass
        except Exception:
            pass

# ── HTTP Server (dashboard) ───────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>F1 Lap Tracker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
  :root {
    --red: #e10600;
    --red-dim: #8b0400;
    --header-tint: #0d0000;
    --logo-glow: rgba(225,6,0,.4);
    --bg: #0a0a0a;
    --panel: #111114;
    --border: #222228;
    --text: #e8e8e8;
    --muted: #666;
    --gold: #ffd700;
    --green: #00d68f;
    --purple: #c77dff;
  }

/* ── Team themes ─────────────────────────────────────────────────────────── */
body.theme-redbull {
  --red:#3671C6; --red-dim:#1e3a80; --header-tint:#030614;
  --logo-glow:rgba(54,113,198,.4);
  --bg:#060810; --panel:#0d1020; --border:#1e2540;
}
body.theme-ferrari {
  --red:#e8002d; --red-dim:#9c001e; --header-tint:#0d0005;
  --logo-glow:rgba(232,0,45,.4);
  --bg:#0d0606; --panel:#160a0a; --border:#2e1414;
}
body.theme-mercedes {
  --red:#00d2be; --red-dim:#008c7e; --header-tint:#030d0c;
  --logo-glow:rgba(0,210,190,.4);
  --bg:#060d0c; --panel:#0c1614; --border:#1c3330;
}
body.theme-mclaren {
  --red:#ff8000; --red-dim:#b35a00; --header-tint:#0d0700;
  --logo-glow:rgba(255,128,0,.4);
  --bg:#0d0800; --panel:#161008; --border:#301e08;
}
body.theme-aston {
  --red:#00e060; --red-dim:#007a38; --header-tint:#020d06;
  --logo-glow:rgba(0,224,96,.4);
  --bg:#050d07; --panel:#0a140c; --border:#162a1a;
}
body.theme-alpine {
  --red:#0093cc; --red-dim:#005e85; --header-tint:#02080f;
  --logo-glow:rgba(0,147,204,.4);
  --bg:#060a10; --panel:#0c1220; --border:#1c2840;
}
body.theme-williams {
  --red:#37bedd; --red-dim:#1a7a94; --header-tint:#020d10;
  --logo-glow:rgba(55,190,221,.4);
  --bg:#060c10; --panel:#0c1520; --border:#1c3040;
}
body.theme-racingbulls {
  --red:#6692ff; --red-dim:#2244cc; --header-tint:#04061a;
  --logo-glow:rgba(102,146,255,.4);
  --bg:#070810; --panel:#0f1125; --border:#202545;
}
body.theme-sauber {
  --red:#52e252; --red-dim:#2a8c2a; --header-tint:#020d02;
  --logo-glow:rgba(82,226,82,.4);
  --bg:#050e05; --panel:#0a1609; --border:#163018;
}
body.theme-haas {
  --red:#e8182a; --red-dim:#9e0a18; --header-tint:#0d0205;
  --logo-glow:rgba(232,24,42,.4);
  --bg:#0d0809; --panel:#1a1214; --border:#342428;
}
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
  }

/* scan-line overlay */
body::before {
content: '';
position: fixed; inset: 0;
background: repeating-linear-gradient(0deg,
transparent, transparent 2px,
rgba(0,0,0,.08) 2px, rgba(0,0,0,.08) 4px);
pointer-events: none;
z-index: 999;
}

header {
display: flex;
align-items: center;
justify-content: space-between;
padding: 16px 24px;
border-bottom: 2px solid var(--red);
background: linear-gradient(90deg, var(--header-tint) 0%, var(--panel) 40%);
}
.logo {
font-family: 'Orbitron', sans-serif;
font-weight: 900;
font-size: 1.4rem;
letter-spacing: .15em;
color: var(--red);
text-shadow: 0 0 20px var(--logo-glow);
}
.logo span { color: #fff; }
.status-dot {
width: 10px; height: 10px; border-radius: 50%;
background: var(--muted);
display: inline-block; margin-right: 8px;
transition: background .3s;
}
.status-dot.live { background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.status-text { font-size: .75rem; color: var(--muted); }
.status-text.live { color: var(--green); }

.grid {
display: grid;
grid-template-columns: 1fr 1fr 1fr;
grid-template-rows: auto auto;
gap: 12px;
padding: 16px;
max-width: 1200px;
margin: 0 auto;
}

.panel {
background: var(--panel);
border: 1px solid var(--border);
border-radius: 4px;
padding: 16px;
position: relative;
overflow: hidden;
}
.panel::before {
content: '';
position: absolute; top: 0; left: 0; right: 0; height: 2px;
background: var(--red);
}
.panel-title {
font-family: 'Orbitron', sans-serif;
font-size: .6rem;
letter-spacing: .2em;
color: var(--muted);
text-transform: uppercase;
margin-bottom: 12px;
}

/* BIG NUMBER panels */
.big-num {
font-family: 'Orbitron', sans-serif;
font-size: 2.4rem;
font-weight: 700;
color: var(--text);
line-height: 1;
margin-bottom: 4px;
}
.big-num.gold { color: var(--gold); text-shadow: 0 0 20px rgba(255,215,0,.3); }
.big-num.red { color: var(--red); }
.sub-label { font-size: .7rem; color: var(--muted); }

/* Sector strips */
.sectors {
display: grid;
grid-template-columns: 1fr 1fr 1fr;
gap: 8px;
}
.sector {
background: #0d0d10;
border: 1px solid var(--border);
border-radius: 3px;
padding: 10px 8px;
text-align: center;
}
.sector-label { font-size: .6rem; color: var(--muted); margin-bottom: 4px; letter-spacing: .15em; }
.sector-time { font-family: 'Orbitron', sans-serif; font-size: .95rem; color: var(--text); }
.sector-time.purple { color: var(--purple); }

/* Session info */
.info-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #1a1a1e; font-size: .8rem; }
.info-row:last-child { border-bottom: none; }
.info-key { color: var(--muted); }
.info-val { color: var(--text); text-align: right; }

/* Lap table */
.lap-table-wrap { overflow-y: auto; max-height: 340px; }
table { width: 100%; border-collapse: collapse; font-size: .78rem; }
thead th {
font-family: 'Orbitron', sans-serif;
font-size: .55rem;
letter-spacing: .15em;
color: var(--muted);
text-align: left;
padding: 6px 8px;
border-bottom: 1px solid var(--border);
position: sticky; top: 0;
background: var(--panel);
}
tbody tr { border-bottom: 1px solid #181820; transition: background .15s; }
tbody tr:hover { background: #1a1a22; }
tbody tr.best-lap { background: rgba(255,215,0,.06); }
tbody tr.track-pb-lap { background: rgba(199,125,255,.07); }
tbody tr.invalid { opacity: .4; }
td { padding: 7px 8px; }
td.lap-num { color: var(--muted); font-size: .7rem; }
td.lap-time { font-family: 'Orbitron', sans-serif; font-size: .85rem; color: var(--text); }
td.lap-time.best { color: var(--gold); }
td.delta { font-size: .75rem; }
td.delta.positive { color: #ff6b6b; }
td.delta.best-text { color: var(--gold); font-weight: bold; }
td.delta.pb-text { color: var(--purple); font-weight: bold; }
td.sector { color: #9999bb; font-size: .72rem; }
.invalid-pill {
background: rgba(225,6,0,.2);
color: var(--red);
font-size: .6rem;
padding: 1px 5px;
border-radius: 2px;
}

/* Lap span full width */
.span-full { grid-column: 1 / -1; }

/* No data state */
.waiting {
text-align: center;
padding: 32px;
color: var(--muted);
}
.waiting .big-icon { font-size: 2.5rem; margin-bottom: 12px; }
.waiting p { font-size: .8rem; line-height: 1.8; }
.waiting code { color: var(--red); background: #1a0000; padding: 1px 5px; border-radius: 2px; }

/* Buttons */
.btn {
background: transparent;
border: 1px solid var(--border);
color: var(--muted);
font-family: 'Share Tech Mono', monospace;
font-size: .7rem;
padding: 5px 12px;
cursor: pointer;
border-radius: 3px;
letter-spacing: .08em;
transition: all .2s;
text-decoration: none;
display: inline-block;
}
.btn:hover { border-color: var(--red); color: var(--red); }
.btn-danger:hover { background: rgba(225,6,0,.1); }
.btn-green { border-color: #1a3a2a; color: var(--green); }
.btn-green:hover { border-color: var(--green); background: rgba(0,214,143,.08); color: var(--green); }

/* Past sessions */
.sessions-wrap { padding: 0 16px 16px; max-width: 1200px; margin: 0 auto; }
.export-link {
  color: var(--green);
  text-decoration: none;
  font-size: .72rem;
  border: 1px solid #1a3a2a;
  padding: 2px 8px;
  border-radius: 3px;
  transition: all .2s;
}
.export-link:hover { background: rgba(0,214,143,.1); border-color: var(--green); }

/* Tyre compound pills */
.cpill {
font-family: 'Orbitron', sans-serif;
font-size: .6rem;
font-weight: 700;
padding: 2px 6px;
border-radius: 3px;
letter-spacing: .05em;
border: 1px solid transparent;
}
.cpill-S { background:rgba(255,50,50,.15);  color:#ff5555; border-color:rgba(255,50,50,.35); }
.cpill-M { background:rgba(255,210,0,.15);  color:#ffd700; border-color:rgba(255,210,0,.35); }
.cpill-H { background:rgba(210,210,210,.12);color:#cccccc; border-color:rgba(200,200,200,.3); }
.cpill-I { background:rgba(0,200,90,.15);   color:#00c85a; border-color:rgba(0,200,90,.35); }
.cpill-W { background:rgba(60,130,255,.15); color:#5599ff; border-color:rgba(60,130,255,.35); }

/* Theme selector */
.theme-select {
background: var(--panel);
border: 1px solid var(--border);
color: var(--muted);
font-family: 'Share Tech Mono', monospace;
font-size: .7rem;
padding: 5px 8px;
border-radius: 3px;
cursor: pointer;
letter-spacing: .06em;
outline: none;
transition: border-color .2s, color .2s;
}
.theme-select:hover, .theme-select:focus { border-color: var(--red); color: var(--text); }
.theme-select option { background: #111; }

@media (max-width: 700px) {
.grid { grid-template-columns: 1fr 1fr; }
.big-num { font-size: 1.6rem; }
.span-full { grid-column: 1 / -1; }
}
</style>

</head>
<body>
<header>
  <div class="logo">F1<span> LAP TRACKER</span></div>
  <div style="display:flex;align-items:center;gap:16px;">
    <select id="theme-select" class="theme-select" onchange="applyTheme(this.value)">
      <option value="">F1 DEFAULT</option>
      <option value="redbull">RED BULL</option>
      <option value="ferrari">FERRARI</option>
      <option value="mercedes">MERCEDES</option>
      <option value="mclaren">MCLAREN</option>
      <option value="aston">ASTON MARTIN</option>
      <option value="alpine">ALPINE</option>
      <option value="williams">WILLIAMS</option>
      <option value="racingbulls">RACING BULLS</option>
      <option value="sauber">KICK SAUBER</option>
      <option value="haas">HAAS</option>
    </select>
    <button class="btn btn-green" onclick="exportCSV()">EXPORT CSV</button>
    <button class="btn btn-danger" onclick="clearSession()">CLEAR SESSION</button>
    <div>
      <span class="status-dot" id="dot"></span>
      <span class="status-text" id="status-text">Waiting for telemetry…</span>
    </div>
  </div>
</header>

<div class="grid" id="main-grid">
  <!-- filled by JS -->
</div>
<div id="pbs-section"></div>
<div id="sessions-section"></div>

<script>
// ── Theme ─────────────────────────────────────────────────────────────────────
function applyTheme(theme) {
  document.body.classList.remove(
    ...Array.from(document.body.classList).filter(c => c.startsWith('theme-'))
  );
  if (theme) document.body.classList.add('theme-' + theme);
  localStorage.setItem('f1-theme', theme || '');
}
(function() {
  const t = localStorage.getItem('f1-theme') || '';
  if (t) { applyTheme(t); document.getElementById('theme-select').value = t; }
})();

let lastData = null;

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    lastData = d;
    render(d);
  } catch(e) {}
}

async function clearSession() {
  await fetch('/api/clear', { method: 'POST' });
  fetchState();
  fetchPBs();
  fetchSessions();
}

function exportCSV() {
  window.location.href = '/api/export';
}

async function fetchPBs() {
  try {
    const r = await fetch('/api/pbs');
    const pbs = await r.json();
    renderPBs(pbs);
  } catch(e) {}
}

function renderPBs(pbs) {
  const el = document.getElementById('pbs-section');
  if (!pbs || pbs.length === 0) { el.innerHTML = ''; return; }
  let rows = '';
  for (const pb of pbs) {
    const setAt = pb.set_at ? pb.set_at.replace('T',' ').substring(0,19) : '—';
    rows += `<tr>
      <td>${pb.track}</td>
      <td style="color:var(--muted);font-size:.72rem">${pb.session_type || '—'}</td>
      <td class="lap-time" style="color:var(--purple)">${pb.lap_time}</td>
      <td>${compoundPill(pb.compound)}</td>
      <td style="color:var(--muted);font-size:.72rem">${setAt}</td>
    </tr>`;
  }
  el.innerHTML = `<div class="sessions-wrap">
    <div class="panel">
      <div class="panel-title">Personal Bests — All Time</div>
      <div class="lap-table-wrap">
        <table>
          <thead><tr>
            <th>TRACK</th><th>SESSION TYPE</th><th>TIME</th><th>TYRE</th><th>SET</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

async function fetchSessions() {
  try {
    const r = await fetch('/api/sessions');
    const sessions = await r.json();
    renderSessions(sessions);
  } catch(e) {}
}

function renderSessions(sessions) {
  const el = document.getElementById('sessions-section');
  if (!sessions || sessions.length === 0) { el.innerHTML = ''; return; }
  let rows = '';
  for (const s of sessions) {
    const started = s.started_at ? s.started_at.replace('T',' ').substring(0,19) : '—';
    const ended   = s.ended_at   ? s.ended_at.replace('T',' ').substring(0,19)   : '<span style="color:var(--green)">In Progress</span>';
    rows += `<tr>
      <td class="lap-num">${s.id}</td>
      <td>${s.track || '—'}</td>
      <td>${s.session_type || '—'}</td>
      <td>${s.weather || '—'}</td>
      <td style="color:var(--muted);font-size:.72rem">${started}</td>
      <td style="font-size:.72rem">${ended}</td>
      <td><a class="export-link" href="/api/sessions/${s.id}/export">CSV</a></td>
    </tr>`;
  }
  el.innerHTML = `<div class="sessions-wrap">
    <div class="panel">
      <div class="panel-title">Past Sessions</div>
      <div class="lap-table-wrap">
        <table>
          <thead><tr>
            <th>#</th><th>TRACK</th><th>TYPE</th><th>WEATHER</th><th>STARTED</th><th>ENDED</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

function fmt(v) { return v || '--:--.---'; }

function compoundPill(c) {
  if (!c) return '<span style="color:var(--muted)">—</span>';
  const map = { Soft:'S', Medium:'M', Hard:'H', Inter:'I', Wet:'W' };
  const abbr = map[c] || c[0];
  return `<span class="cpill cpill-${abbr}">${abbr}</span>`;
}

function render(d) {
  const dot = document.getElementById('dot');
  const stxt = document.getElementById('status-text');
  if (d.udp_connected) {
    dot.className = 'status-dot live';
    stxt.className = 'status-text live';
    stxt.textContent = 'LIVE TELEMETRY';
  } else {
    dot.className = 'status-dot';
    stxt.className = 'status-text';
    stxt.textContent = 'Waiting for telemetry…';
  }

  const grid = document.getElementById('main-grid');

  const bestTime = d.best_lap_ms ? fmt(msToLap(d.best_lap_ms)) : '--:--.---';

  // Current lap number
  const p1 = `<div class="panel">
    <div class="panel-title">Current Lap</div>
    <div class="big-num red">${d.current_lap}</div>
    <div class="sub-label">${d.total_laps > 0 ? 'of ' + d.total_laps : 'laps completed: ' + d.laps.length}</div>
  </div>`;

  // Best lap
  const p2 = `<div class="panel">
    <div class="panel-title">Best Lap ${d.best_lap_num ? '(Lap ' + d.best_lap_num + ')' : ''}</div>
    <div class="big-num gold">${bestTime}</div>
    <div class="sub-label">Personal best this session</div>
  </div>`;

  // Session info
  const pbRow = d.track_pb_time
    ? `<div class="info-row"><span class="info-key">TRACK PB</span><span class="info-val" style="color:var(--purple)">${d.track_pb_time}${d.track_pb_compound ? ' <span style="font-size:.65rem;color:var(--muted)">(' + d.track_pb_compound + ')</span>' : ''}</span></div>`
    : `<div class="info-row"><span class="info-key">TRACK PB</span><span class="info-val" style="color:var(--muted)">No record yet</span></div>`;
  const p3 = `<div class="panel">
    <div class="panel-title">Session</div>
    <div class="info-row"><span class="info-key">TRACK</span><span class="info-val">${d.session.track}</span></div>
    <div class="info-row"><span class="info-key">TYPE</span><span class="info-val">${d.session.session_type}</span></div>
    <div class="info-row"><span class="info-key">WEATHER</span><span class="info-val">${d.session.weather}</span></div>
    <div class="info-row"><span class="info-key">POSITION</span><span class="info-val">${d.player_position > 0 ? 'P' + d.player_position : '—'}</span></div>
    ${pbRow}
  </div>`;

  // Lap table
  let rows = '';
  if (d.laps.length === 0) {
    rows = `<tr><td colspan="8" class="waiting"><div class="big-icon">🏎</div>
      <p>No laps recorded yet.<br>
      Make sure UDP telemetry is <code>ON</code> in F1 25 settings<br>
      IP: <code>127.0.0.1</code> &nbsp; Port: <code>20777</code></p></td></tr>`;
  } else {
    const reversed = [...d.laps].reverse();
    for (const lap of reversed) {
      const isBest    = lap.is_best;
      const isTrackPB = lap.is_track_pb;
      const isInvalid = lap.invalid;
      const deltaClass = lap.delta === 'PB!'  ? 'pb-text'
                       : lap.delta === 'BEST' ? 'best-text'
                       : (lap.delta && lap.delta.startsWith('+')) ? 'positive' : '';
      const timeLabel = isTrackPB ? lap.lap_time + ' 🏆'
                      : isBest    ? lap.lap_time + ' ★'
                      : lap.lap_time;
      rows += `<tr class="${isBest ? 'best-lap' : ''} ${isTrackPB ? 'track-pb-lap' : ''} ${isInvalid ? 'invalid' : ''}">
        <td class="lap-num">${lap.lap_num}</td>
        <td>${compoundPill(lap.compound)}</td>
        <td class="lap-time ${isTrackPB ? 'best' : isBest ? 'best' : ''}">${timeLabel}</td>
        <td class="delta ${deltaClass}">${lap.delta || ''}</td>
        <td class="sector">${lap.s1 !== '--:--.---' ? lap.s1 : '—'}</td>
        <td class="sector">${lap.s2 !== '--:--.---' ? lap.s2 : '—'}</td>
        <td class="sector">${lap.s3 !== '--:--.---' ? lap.s3 : '—'}</td>
        ${isInvalid ? '<td><span class="invalid-pill">INVALID</span></td>' : '<td></td>'}
      </tr>`;
    }
  }

  const p4 = `<div class="panel span-full">
    <div class="panel-title" style="display:flex;justify-content:space-between;">
      <span>Lap History</span>
      <span style="color:var(--muted)">${d.laps.length} laps</span>
    </div>
    <div class="lap-table-wrap">
      <table>
        <thead><tr>
          <th>LAP</th><th>TYRE</th><th>TIME</th><th>DELTA</th><th>S1</th><th>S2</th><th>S3</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;

  grid.innerHTML = p1 + p2 + p3 + p4;
}

function msToLap(ms) {
  if (!ms || ms <= 0) return '--:--.---';
  const total = ms / 1000;
  const m = Math.floor(total / 60);
  const s = Math.floor(total % 60);
  const ms3 = Math.floor(ms % 1000);
  return `${m}:${String(s).padStart(2,'0')}.${String(ms3).padStart(3,'0')}`;
}

fetchState();
fetchPBs();
fetchSessions();
setInterval(fetchState, 1000);
setInterval(fetchPBs, 60000);
setInterval(fetchSessions, 30000);
</script>

</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # silence request logs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            with state_lock:
                payload = json.dumps(state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/sessions":
            con = sqlite3.connect(DB_PATH)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
            sessions = [dict(r) for r in rows]
            con.close()
            payload = json.dumps(sessions).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/pbs":
            pbs = db_get_all_pbs()
            payload = json.dumps(pbs).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/export":
            # Export current in-memory session as CSV
            with state_lock:
                laps_snapshot = list(state["laps"])
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Lap", "Tyre", "Time", "S1 (ms)", "S2 (ms)", "S3 (ms)", "Invalid", "Timestamp"])
            for lap in laps_snapshot:
                writer.writerow([lap["lap_num"], lap.get("compound", ""), lap["lap_time"],
                                  lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], lap["invalid"], lap["timestamp"]])
            csv_bytes = output.getvalue().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", 'attachment; filename="f1_current_session.csv"')
            self.send_header("Content-Length", len(csv_bytes))
            self.end_headers()
            self.wfile.write(csv_bytes)

        elif parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/export"):
            # Export a past session from DB as CSV  e.g. /api/sessions/3/export
            try:
                session_id = int(parsed.path.split("/")[3])
            except (IndexError, ValueError):
                self.send_response(400); self.end_headers(); return
            con = sqlite3.connect(DB_PATH)
            con.row_factory = sqlite3.Row
            laps = con.execute(
                "SELECT * FROM laps WHERE session_id=? ORDER BY lap_num", (session_id,)
            ).fetchall()
            con.close()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Lap", "Tyre", "Time", "S1 (ms)", "S2 (ms)", "S3 (ms)", "Invalid", "Timestamp"])
            for lap in laps:
                writer.writerow([lap["lap_num"], lap["compound"] or "", lap["lap_time"],
                                  lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], bool(lap["invalid"]), lap["timestamp"]])
            csv_bytes = output.getvalue().encode()
            fname = f"f1_session_{session_id}.csv"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", len(csv_bytes))
            self.end_headers()
            self.wfile.write(csv_bytes)

        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/clear":
            old_session_id = None
            with state_lock:
                old_session_id = state["current_session_id"]
                state["laps"].clear()
                state["best_lap_ms"] = None
                state["best_lap_num"] = None
                state["current_lap"] = 1
                state["session"]["started_at"] = None
                state["current_session_id"] = None
            if old_session_id is not None:
                db_close_session(old_session_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

def main():
    print("=" * 50)
    print("  F1 Lap Tracker")
    print("=" * 50)
    print()
    print("IN-GAME SETUP (F1 25):")
    print("  Settings → Telemetry Settings")
    print("    UDP Telemetry  : On")
    print("    UDP Format     : 2023 (or 2024)")
    print("    UDP IP Address : 127.0.0.1")
    print("    UDP Port       : 20777")
    print("    Broadcast Mode : Off")
    print()

    init_db()
    print(f"💾  Database → {os.path.abspath(DB_PATH)}")
    print()

    # Start UDP listener in background
    t = threading.Thread(target=udp_listener, daemon=True)
    t.start()

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", 5000), Handler)
    print("🌐  Dashboard → http://localhost:5000")
    print()
    print("Press Ctrl+C to stop.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
