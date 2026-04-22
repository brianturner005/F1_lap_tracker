#!/usr/bin/env python3
"""
Pitwall IQ — F1 Lap Time Tracker

Listens for F1 25 UDP telemetry on port 20777 and serves a live
dashboard at http://localhost:5000

In-game setup (one time):
Settings → Telemetry Settings
UDP Telemetry   : On
UDP Format      : 2025
UDP IP Address  : 127.0.0.1
UDP Port        : 20777
Broadcast Mode  : Off

Run:
python F1_lap_tracker.py

Then open http://localhost:5000 in your browser.

Requirements: none (uses Python stdlib only)
"""

import struct
import socket
import threading
import json
import time
import sqlite3
import csv
import io
import argparse
import logging
import urllib.error
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

log = logging.getLogger(__name__)

VERSION = "0.9.0"

# ── Leaderboard config ───────────────────────────────────────────────────────
# Default URL is the shared Pitwall IQ backend — no configuration needed.
# Override by setting F1_LEADERBOARD_URL if you host your own instance.
LEADERBOARD_URL = os.environ.get(
    "F1_LEADERBOARD_URL",
    "https://f1tracker-func-6v3lqkyuhxwkc.azurewebsites.net",
).strip().strip('"\'').rstrip("/")
# Normalise: strip trailing /api so the URL works whether or not the user
# included it (the code appends /api/lb-submit etc. itself).
if LEADERBOARD_URL.endswith("/api"):
    LEADERBOARD_URL = LEADERBOARD_URL[:-4]

# ── AI debrief proxy URL ──────────────────────────────────────────────────────
# Points to the Pitwall IQ Azure Function that proxies AI debrief requests.
# Users need no API keys — the function holds them server-side.
# Set PITWALL_PROXY_URL env var to override (e.g. for local dev).
PITWALL_PROXY_URL = os.environ.get(
    "PITWALL_PROXY_URL",
    "https://f1tracker-func-6v3lqkyuhxwkc.azurewebsites.net",
).rstrip("/")

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
    "leaderboard_opt_in": False,
    "display_name": "Anonymous",
    "player_id": None,
    "leaderboard": None,       # cached community leaderboard response
    "leaderboard_enabled": False,  # True when LEADERBOARD_URL is set
    "lb_error": None,              # set when the server rejects a submission
    "udp_connected": False,
    "player_position": 0,
    "total_laps": 0,
    "last_recorded_lap_ms": 0,  # tracks last lap time we saved, to catch final lap
    "car_pos": {"x": 0.0, "z": 0.0},  # current world position
    "car_speed": 0,                    # current speed km/h
    "car_throttle": 0.0,               # throttle input 0.0–1.0
    "car_brake": 0.0,                  # brake input 0.0–1.0
    "car_gear": 0,                     # current gear (-1=R, 0=N, 1–8)
    "car_steer": 0.0,                  # steering input -1.0 (left) to 1.0 (right)
    "car_rpm": 0,                      # engine RPM
    "rev_lights_pct": 0,               # rev lights 0–100 (from game)
    "g_lat": 0.0,                      # lateral g-force
    "g_lon": 0.0,                      # longitudinal g-force
    "current_sector": 0,               # 0=S1, 1=S2, 2=S3
    "lap_trace": [],                   # [{x,z,speed,throttle,brake,gear,gLat,gLon,sector}] current lap
    "track_outline": [],               # reference trace from last completed lap
    "career_stats": {"races":0,"wins":0,"podiums":0,"points":0,"fastest_laps":0,"dnfs":0},
    "race_result": None,               # populated when Final Classification packet (ID 8) arrives
    "player_fastest_lap": False,       # set True when FTLP event fires for the player
    "race_result_saved_sid": None,     # session ID for which race result was already saved
    "tyre_wear":         [None, None, None, None],  # [RL, RR, FL, FR] float % from Car Damage packet
    "tyre_damage":       [None, None, None, None],  # [RL, RR, FL, FR] uint8 % structural damage
    "front_wing_damage": [None, None],              # [left, right] uint8 % front wing damage
    "tyre_age_laps":     None,                      # laps on current tyre set (from Car Status)
    "fuel_in_tank":      None,                      # current fuel load kg (from Car Status)
    "fuel_capacity":     None,                      # tank capacity kg (from Car Status)
    "fuel_remaining_laps": None,                    # estimated laps of fuel remaining (from Car Status)
    "update_available":  None,                      # set to version string when update is downloaded
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

# Maps game track name → SVG filename (without .svg extension)
TRACK_SVG = {
    "Melbourne":        "australia",
    "Shanghai":         "china",
    "Sakhir (Bahrain)": "bahrain",
    "Sakhir Short":     "bahrain",
    "Catalunya":        "spain",
    "Monaco":           "monaco",
    "Montreal":         "canada",
    "Silverstone":      "silverstone",
    "Silverstone Short":"silverstone",
    "Hungaroring":      "hungary",
    "Spa":              "spa",
    "Monza":            "monza",
    "Singapore":        "singapore",
    "Suzuka":           "japan",
    "Suzuka Short":     "japan",
    "Abu Dhabi":        "abudhabi",
    "Texas (COTA)":     "usa",
    "Texas Short":      "usa",
    "Brazil":           "brazil",
    "Interlagos Short": "brazil",
    "Austria":          "austria",
    "Mexico":           "mexico",
    "Baku (Azerbaijan)":"azerbaijan",
    "Zandvoort":        "netherlands",
    "Imola":            "imola",
    "Portimão":         "portugal",
    "Jeddah":           "saudi_arabia",
    "Miami":            "miami",
    "Las Vegas":        "las_vegas",
    "Lusail (Qatar)":   "qatar",
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

FINAL_CLASS_SIZE = 45   # bytes per car in PacketFinalClassificationData
RESULT_STATUS    = {0:"Invalid",1:"Inactive",2:"Active",3:"Finished",4:"DNF",5:"DSQ",6:"N/C",7:"Retired"}

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
            trace        TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    # Migrations — each ALTER TABLE is a no-op if the column already exists
    for col_ddl in (
        "ALTER TABLE laps ADD COLUMN trace TEXT",
        "ALTER TABLE laps ADD COLUMN tyre_wear TEXT",
        "ALTER TABLE laps ADD COLUMN tyre_damage TEXT",
    ):
        try:
            con.execute(col_ddl)
        except Exception as e:
            log.debug("DB migration (expected on existing DB): %s", e)
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
    con.execute("""
        CREATE TABLE IF NOT EXISTS race_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER,
            track         TEXT,
            session_type  TEXT,
            position      INTEGER,
            grid_pos      INTEGER,
            points        INTEGER,
            num_laps      INTEGER,
            result_status INTEGER,
            best_lap_ms   INTEGER,
            best_lap      TEXT,
            total_time_s  REAL,
            fastest_lap   INTEGER DEFAULT 0,
            recorded_at   TEXT
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

def db_save_lap(session_id, lap, trace=None, tyre_wear=None, tyre_damage=None):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO laps
           (session_id, lap_num, lap_time_ms, lap_time, s1_ms, s2_ms, s3_ms,
            invalid, timestamp, compound, trace, tyre_wear, tyre_damage)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, lap["lap_num"], lap["lap_time_ms"], lap["lap_time"],
         lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], int(lap["invalid"]),
         lap["timestamp"], lap.get("compound"),
         json.dumps(trace) if trace else None,
         json.dumps(tyre_wear) if tyre_wear else None,
         json.dumps(tyre_damage) if tyre_damage else None)
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

def db_save_race_result(session_id, track, session_type, position, grid_pos,
                        points, num_laps, result_status, best_lap_ms, best_lap,
                        total_time_s, fastest_lap):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO race_results
           (session_id, track, session_type, position, grid_pos, points, num_laps,
            result_status, best_lap_ms, best_lap, total_time_s, fastest_lap, recorded_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, track, session_type, position, grid_pos, points, num_laps,
         result_status, best_lap_ms, best_lap, total_time_s, int(fastest_lap),
         datetime.now().isoformat()),
    )
    con.commit()
    con.close()

def db_get_career_stats():
    con = sqlite3.connect(DB_PATH)
    row = con.execute("""
        SELECT
            COUNT(*)                                                      AS races,
            SUM(CASE WHEN position = 1  AND result_status IN (2,3) THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN position <= 3 AND result_status IN (2,3) THEN 1 ELSE 0 END) AS podiums,
            SUM(points)                                                        AS points,
            SUM(fastest_lap)                                                   AS fastest_laps,
            SUM(CASE WHEN result_status IN (4,7) THEN 1 ELSE 0 END)           AS dnfs
        FROM race_results
    """).fetchone()
    con.close()
    if row:
        return {"races": row[0] or 0, "wins": row[1] or 0, "podiums": row[2] or 0,
                "points": row[3] or 0, "fastest_laps": row[4] or 0, "dnfs": row[5] or 0}
    return {"races": 0, "wins": 0, "podiums": 0, "points": 0, "fastest_laps": 0, "dnfs": 0}

def db_get_recent_races(limit=30):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM race_results ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

# ── Config table (player identity & leaderboard prefs) ───────────────────────

def init_config():
    """Create config table, generate player_id if needed, return config dict."""
    import uuid as _uuid
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    row = con.execute("SELECT value FROM config WHERE key='player_id'").fetchone()
    if row:
        player_id = row[0]
    else:
        player_id = str(_uuid.uuid4())
        con.execute("INSERT INTO config (key,value) VALUES ('player_id',?)", (player_id,))
    def _get(k, d):
        r = con.execute("SELECT value FROM config WHERE key=?", (k,)).fetchone()
        return r[0] if r else d
    opt_in      = _get("leaderboard_opt_in", "0") == "1"
    display_name = _get("display_name", "Anonymous")
    con.commit()
    con.close()
    return {"player_id": player_id, "leaderboard_opt_in": opt_in, "display_name": display_name}

def db_save_config(key, value):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (key, str(value)))
    con.commit()
    con.close()

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
            state["session"]["weather"] = weather_name
            # Don't overwrite a known session type with "Unknown" — the game
            # sends sessionType=0 transiently during formation lap / pre-race.
            if session_name != "Unknown" or old_session_type == "Unknown":
                state["session"]["session_type"] = session_name
            effective_session_name = state["session"]["session_type"]
            state["session"]["track"]   = track_name
            state["total_laps"]         = total_laps_val
            state["udp_connected"]      = True
            if state["session"]["started_at"] is None:
                started_at = datetime.now().isoformat()
                state["session"]["started_at"] = started_at
                create_session = True
            current_session_id = state["current_session_id"]
            # Reload PB whenever track or session type changes to a known value
            if track_name != "Unknown" and (track_name != old_track or effective_session_name != old_session_type):
                load_pb = True

        if create_session:
            new_id = db_create_session(track_name, effective_session_name, weather_name, started_at)
            with state_lock:
                state["current_session_id"] = new_id
        elif current_session_id is not None:
            db_update_session(current_session_id, track_name, effective_session_name, weather_name)

        if load_pb:
            pb = db_get_track_pb(track_name, effective_session_name)
            with state_lock:
                if pb:
                    state["track_pb_ms"]       = pb["lap_time_ms"]
                    state["track_pb_time"]     = pb["lap_time"]
                    state["track_pb_compound"] = pb.get("compound")
                else:
                    state["track_pb_ms"]       = None
                    state["track_pb_time"]     = None
                    state["track_pb_compound"] = None
            # Refresh leaderboard immediately when track becomes known
            if LEADERBOARD_URL:
                threading.Thread(target=_lb_refresh, daemon=True).start()
    except Exception as e:
        log.debug("parse_session_data: %s", e)

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

            # Cache sector times continuously — the game resets them at the lap
            # boundary, so we must read them during the lap, not at lap-end.
            if s1_total_ms > 0:
                state["last_sector"][0] = s1_total_ms
            if s2_total_ms > 0:
                state["last_sector"][1] = s2_total_ms

            state["current_sector"] = sector

            prev_lap = state["current_lap"]
            state["current_lap"] = cur_lap_num

            # New lap completed.
            # Primary trigger: lap counter incremented (mid-race laps).
            # Secondary trigger: last_lap_ms changed to an unseen value —
            # catches the FINAL lap, where cur_lap_num never increments
            # because there is no next lap to start.
            _new_by_lap_num = cur_lap_num > prev_lap
            _new_by_time    = (last_lap_ms > 0
                                and last_lap_ms != state["last_recorded_lap_ms"])
            if last_lap_ms > 0 and (_new_by_lap_num or _new_by_time):
                s1_val = state["last_sector"][0]
                s2_val = state["last_sector"][1]
                state["last_sector"] = [None, None, None]  # reset for new lap

                lap_record = {
                    "lap_num": prev_lap,
                    "lap_time_ms": last_lap_ms,
                    "lap_time": ms_to_laptime(last_lap_ms),
                    "invalid": bool(invalid),
                    "s1_ms": s1_val,
                    "s2_ms": s2_val,
                    "s3_ms": (last_lap_ms - s1_val - s2_val) if (s1_val and s2_val) else None,
                    "timestamp": datetime.now().isoformat(),
                    "compound": state["current_compound"],
                    "is_track_pb": False,
                }
                lap_record["s1"] = ms_to_laptime(lap_record["s1_ms"])
                lap_record["s2"] = ms_to_laptime(lap_record["s2_ms"])
                lap_record["s3"] = ms_to_laptime(lap_record["s3_ms"])

                state["last_recorded_lap_ms"] = last_lap_ms
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

        # Save current lap trace as track outline reference, then reset for next lap
        saved_trace = None
        saved_tyre_wear = saved_tyre_damage = None
        if save_session_id is not None:
            with state_lock:
                if state["lap_trace"]:
                    saved_trace = list(state["lap_trace"])
                    state["track_outline"] = saved_trace
                state["lap_trace"] = []
                saved_tyre_wear   = list(state.get("tyre_wear")   or [None] * 4)
                saved_tyre_damage = list(state.get("tyre_damage") or [None] * 4)

        # Compute aggregate telemetry stats from the trace and store in lap record
        if saved_trace:
            n = len(saved_trace)
            max_spd   = max(p["speed"]                    for p in saved_trace)
            avg_spd   = sum(p["speed"]                    for p in saved_trace) / n
            avg_thr   = sum(p["throttle"]                 for p in saved_trace) / n * 100
            ft_pct    = sum(1 for p in saved_trace if p["throttle"] >= 0.95) / n * 100
            avg_brk   = sum(p["brake"]                    for p in saved_trace) / n * 100
            hb_pct    = sum(1 for p in saved_trace if p["brake"] >= 0.5)  / n * 100
            max_g     = max(abs(p.get("gLat", 0))         for p in saved_trace)
            avg_gear  = sum(p.get("gear", 0)              for p in saved_trace) / n
            max_steer = max(abs(p.get("steer", 0))        for p in saved_trace)
            lap_record["telem"] = {
                "max_speed":         round(max_spd),
                "avg_speed":         round(avg_spd),
                "avg_throttle":      round(avg_thr),
                "full_throttle_pct": round(ft_pct),
                "avg_brake":         round(avg_brk),
                "heavy_brake_pct":   round(hb_pct),
                "max_g_lat":         round(max_g, 2),
                "avg_gear":          round(avg_gear, 1),
                "max_steer":         round(max_steer, 2),
            }
            # Capture tyre wear at lap completion (FL, FR, RL, RR) — only store non-None values
            tw = state.get("tyre_wear", [None, None, None, None])
            for idx, key in ((2, "tyre_wear_fl"), (3, "tyre_wear_fr"), (0, "tyre_wear_rl"), (1, "tyre_wear_rr")):
                if tw[idx] is not None:
                    lap_record["telem"][key] = round(tw[idx])

        if save_session_id is not None:
            db_save_lap(save_session_id, lap_record, trace=saved_trace,
                        tyre_wear=saved_tyre_wear, tyre_damage=saved_tyre_damage)
        if save_pb_data is not None:
            db_upsert_track_pb(*save_pb_data)
            with state_lock:
                _opt_in  = state.get("leaderboard_opt_in", False)
                _pid     = state.get("player_id", "")
                _name    = state.get("display_name", "Anonymous")
            if _opt_in and LEADERBOARD_URL:
                _lb_post({
                    "player_id":    _pid,
                    "display_name": _name,
                    "track":        save_pb_data[0],
                    "session_type": save_pb_data[1],
                    "lap_time_ms":  save_pb_data[2],
                    "lap_time":     save_pb_data[3],
                    "compound":     save_pb_data[4],
                    "submitted_at": save_pb_data[6],
                })
    except Exception as e:
        log.debug("parse_lap_data: %s", e)

# Packet ID 7 – Car Status Data / Packet ID 10 – Car Damage Data

CAR_STATUS_SIZE    = 55  # F1 25 per-car car status size
CAR_DAMAGE_SIZE    = 42  # F1 25 per-car car damage size
MOTION_CAR_SIZE    = 60  # worldPositionX/Y/Z + velocity + direction + gforce + angles
CAR_TELEMETRY_SIZE = 60  # speed(u16) + throttle/steer/brake(f32) + gear/rpm/drs + temps

# Minimum distance (world units) between stored trace points — keeps trace lean
_TRACE_MIN_DIST = 3.0
_TRACE_MAX_PTS  = 4000

def parse_motion_packet(data, player_idx):
    try:
        base = HEADER_SIZE + player_idx * MOTION_CAR_SIZE
        if len(data) < base + 44:
            return
        # +0 posX(f32)  +8 posZ(f32)  +36 gForceLateral(f32)  +40 gForceLongitudinal(f32)
        x     = struct.unpack_from("<f", data, base +  0)[0]
        z     = struct.unpack_from("<f", data, base +  8)[0]
        g_lat = struct.unpack_from("<f", data, base + 36)[0]
        g_lon = struct.unpack_from("<f", data, base + 40)[0]
        with state_lock:
            state["car_pos"] = {"x": round(x, 1), "z": round(z, 1)}
            state["g_lat"]   = round(g_lat, 3)
            state["g_lon"]   = round(g_lon, 3)
            spd      = state["car_speed"]
            throttle = state["car_throttle"]
            steer    = state["car_steer"]
            brake    = state["car_brake"]
            gear     = state["car_gear"]
            rpm      = state["car_rpm"]
            sector   = state["current_sector"]
            trace    = state["lap_trace"]
            # Subsample: only store a point if car has moved far enough
            if len(trace) < _TRACE_MAX_PTS:
                if not trace or (abs(x - trace[-1]["x"]) + abs(z - trace[-1]["z"])) >= _TRACE_MIN_DIST:
                    trace.append({
                        "x": round(x, 1), "z": round(z, 1),
                        "speed": spd, "sector": sector,
                        "throttle": throttle, "brake": brake,
                        "steer": steer, "gear": gear, "rpm": rpm,
                        "gLat": round(g_lat, 2), "gLon": round(g_lon, 2),
                    })
    except Exception as e:
        log.debug("parse_motion: %s", e)

def parse_car_telemetry_packet(data, player_idx):
    try:
        base = HEADER_SIZE + player_idx * CAR_TELEMETRY_SIZE
        if len(data) < base + 20:
            return
        # +0 speed(u16)  +2 throttle(f32)  +6 steer(f32)  +10 brake(f32)
        # +14 clutch(u8) +15 gear(i8)  +16 engineRPM(u16)  +18 drs(u8)  +19 revLightsPct(u8)
        speed          = struct.unpack_from("<H", data, base +  0)[0]
        throttle       = struct.unpack_from("<f", data, base +  2)[0]
        steer          = struct.unpack_from("<f", data, base +  6)[0]
        brake          = struct.unpack_from("<f", data, base + 10)[0]
        gear           = struct.unpack_from("<b", data, base + 15)[0]
        rpm            = struct.unpack_from("<H", data, base + 16)[0]
        rev_lights_pct = struct.unpack_from("<B", data, base + 19)[0]
        with state_lock:
            state["car_speed"]       = int(speed)
            state["car_throttle"]    = round(max(0.0, min(1.0, throttle)), 3)
            state["car_steer"]       = round(max(-1.0, min(1.0, steer)),   3)
            state["car_brake"]       = round(max(0.0, min(1.0, brake)),    3)
            state["car_gear"]        = int(gear)
            state["car_rpm"]         = int(rpm)
            state["rev_lights_pct"]  = int(rev_lights_pct)
    except Exception as e:
        log.debug("parse_car_telemetry: %s", e)

def parse_car_status_packet(data, player_idx):
    try:
        base = HEADER_SIZE + (player_idx * CAR_STATUS_SIZE)
        if len(data) < base + CAR_STATUS_SIZE:
            return
        # +5 fuelInTank  +9 fuelCapacity  +13 fuelRemainingLaps
        fuel_in_tank, fuel_capacity, fuel_remaining = struct.unpack_from("<fff", data, base + 5)
        # +26 visualTyreCompound  +27 tyresAgeLaps
        visual_compound = struct.unpack_from("<B", data, base + 26)[0]
        tyre_age        = struct.unpack_from("<B", data, base + 27)[0]
        compound_name = VISUAL_COMPOUNDS.get(visual_compound)
        with state_lock:
            state["current_compound"]    = compound_name
            state["tyre_age_laps"]       = int(tyre_age)
            state["fuel_in_tank"]        = round(float(fuel_in_tank), 2)
            state["fuel_capacity"]       = round(float(fuel_capacity), 2)
            state["fuel_remaining_laps"] = round(float(fuel_remaining), 2)
    except Exception as e:
        log.debug("parse_car_status: %s", e)

# Packet ID 10 – Car Damage Data
def parse_car_damage_packet(data, player_idx):
    try:
        # Compute per-car size from packet length rather than using a hardcoded
        # constant — guards against F1 25 spec changes between game versions.
        body_len = len(data) - HEADER_SIZE
        if body_len < 20:
            return
        per_car = body_len // 22   # always 22 cars in the array
        if per_car < 20:
            return
        base = HEADER_SIZE + player_idx * per_car
        if len(data) < base + 20:
            return
        # +0  tyresWear[4]        4 × float  (RL, RR, FL, FR)
        # +16 tyresDamage[4]     4 × uint8  (RL, RR, FL, FR)
        # +24 frontLeftWingDamage  uint8
        # +25 frontRightWingDamage uint8
        wear   = struct.unpack_from("<4f", data, base +  0)
        damage = struct.unpack_from("<4B", data, base + 16)
        valid  = [round(w, 1) if 0.0 <= w <= 100.0 else None for w in wear]
        # F1 25 (per_car=46) inserted 4 bytes at +24..+27 shifting wing damage
        # to +28/+29. F1 24 (per_car=41) had it at +24/+25.
        fw_off = 28 if per_car >= 46 else 24
        fw_dmg = [None, None]
        if len(data) >= base + fw_off + 2:
            fw_dmg = list(struct.unpack_from("<2B", data, base + fw_off))
        with state_lock:
            state["tyre_wear"]          = valid
            state["tyre_damage"]        = list(damage)
            state["front_wing_damage"]  = fw_dmg  # [left, right] 0-100
    except Exception as e:
        log.debug("parse_car_damage: %s", e)

# Packet ID 3 – Event Data
def parse_event_packet(data, player_idx):
    try:
        base = HEADER_SIZE
        if len(data) < base + 4:
            return
        code = data[base:base + 4].decode("ascii", errors="ignore")
        if code == "FTLP" and len(data) >= base + 5:
            vehicle_idx = struct.unpack_from("<B", data, base + 4)[0]
            if vehicle_idx == player_idx:
                with state_lock:
                    state["player_fastest_lap"] = True
    except Exception as e:
        log.debug("parse_event: %s", e)

# Packet ID 8 – Final Classification Data
def parse_final_classification_packet(data, player_idx):
    try:
        base = HEADER_SIZE
        if len(data) < base + 1:
            return
        num_cars = struct.unpack_from("<B", data, base)[0]
        if player_idx >= num_cars or num_cars == 0:
            return
        # Infer the per-car stride from packet length (22 entries always present).
        # F1 24 = 45 bytes/car, F1 25 = 46 bytes/car. Using the inferred value
        # avoids the 1-byte-per-car drift that corrupts reads for higher car indices.
        inferred_per_car = (len(data) - base - 1) // 22
        per_car = inferred_per_car if inferred_per_car >= FINAL_CLASS_SIZE else FINAL_CLASS_SIZE
        car_base = base + 1 + player_idx * per_car
        if len(data) < car_base + 20:
            return
        position      = struct.unpack_from("<B", data, car_base + 0)[0]
        num_laps      = struct.unpack_from("<B", data, car_base + 1)[0]
        grid_pos      = struct.unpack_from("<B", data, car_base + 2)[0]
        points        = struct.unpack_from("<B", data, car_base + 3)[0]
        result_status = struct.unpack_from("<B", data, car_base + 5)[0]
        best_lap_ms   = struct.unpack_from("<I", data, car_base + 6)[0]
        total_time_s  = struct.unpack_from("<d", data, car_base + 10)[0]
        best_lap_str  = ms_to_laptime(best_lap_ms) if best_lap_ms > 0 else "—"

        print(f"[Final Classification] pkt_len={len(data)} per_car={per_car} "
              f"player_idx={player_idx} status={result_status} pos={position} "
              f"laps={num_laps} best={best_lap_str}")

        # Only save when the race is actually over. Status 2 ("Active") is
        # included because F1 25 reports classified finishers (including DNFs
        # from crashes) as Active rather than Finished/Retired in many cases.
        # Status 0 (Invalid) and 1 (Inactive) are still ignored — those are
        # formation-lap / pre-race placeholders.
        FINAL_STATUSES = {2, 3, 4, 5, 6, 7}  # Active, Finished, DNF, DSQ, N/C, Retired
        if result_status not in FINAL_STATUSES:
            print(f"[Final Classification] ignored — status {result_status} not final")
            return

        RACE_SESSION_TYPES = {"Race", "Race 2", "Race 3"}

        with state_lock:
            sid       = state["current_session_id"]
            track     = state["session"]["track"]
            sess_type = state["session"]["session_type"]

        print(f"[Final Classification] status={result_status} pos={position} "
              f"sess='{sess_type}' track='{track}' sid={sid}")

        # Only record career results for race sessions
        if sess_type not in RACE_SESSION_TYPES:
            print(f"[Final Classification] skipped — session type '{sess_type}' not a race")
            return

        with state_lock:
            # Guard against the game re-sending this packet on the results screen
            if sid is not None and state["race_result_saved_sid"] == sid:
                print(f"[Final Classification] skipped — already saved for session {sid}")
                return
            fastest = state["player_fastest_lap"]
            state["player_fastest_lap"]    = False
            state["race_result_saved_sid"] = sid
            state["race_result"] = {
                "position": position,
                "grid_pos": grid_pos,
                "points": points,
                "num_laps": num_laps,
                "result_status": result_status,
                "best_lap_ms": best_lap_ms,
                "best_lap": best_lap_str,
                "total_time_s": round(total_time_s, 3),
                "fastest_lap": fastest,
                "track": track,
                "session_type": sess_type,
            }
        db_save_race_result(sid, track, sess_type, position, grid_pos, points,
                            num_laps, result_status, best_lap_ms, best_lap_str,
                            total_time_s, fastest)
        print(f"[Final Classification] saved — pos={position} pts={points} "
              f"track='{track}' sess='{sess_type}'")
        stats = db_get_career_stats()
        with state_lock:
            state["career_stats"] = stats
    except Exception as exc:
        print(f"[Final Classification] ERROR: {exc}")

# ── Community leaderboard ─────────────────────────────────────────────────────

_backend_warned: set = set()

def _warn_backend_unreachable(service: str) -> None:
    if service not in _backend_warned:
        print(f"[{service}] Backend unreachable — {service.lower()} features will be unavailable until the connection is restored.")
        _backend_warned.add(service)

# ── Auto-update ───────────────────────────────────────────────────────────────
_UPDATE_BASE = "https://raw.githubusercontent.com/brianturner005/F1_lap_tracker/main"
_UPDATE_FILES = ["F1_lap_tracker.py", "static/dashboard.html"]

def _parse_version(v):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0, 0, 0)

def _check_and_apply_update():
    time.sleep(8)  # wait for startup to settle before hitting network
    try:
        from urllib.request import urlopen
        with urlopen(f"{_UPDATE_BASE}/version.txt", timeout=10) as r:
            remote_ver = r.read().decode("utf-8").strip()
        if _parse_version(remote_ver) <= _parse_version(VERSION):
            return
        print(f"[Update] New version available: {remote_ver} (you have {VERSION})")
        print(f"[Update] Downloading update…")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        updated = []
        for rel in _UPDATE_FILES:
            try:
                with urlopen(f"{_UPDATE_BASE}/{rel}", timeout=30) as r:
                    content = r.read()
                dest = os.path.join(script_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(content)
                os.replace(tmp, dest)
                updated.append(rel)
            except Exception as e:
                log.warning("Update download failed for %s: %s", rel, e)
        if updated:
            print(f"[Update] ✓ v{remote_ver} downloaded ({', '.join(updated)})")
            print(f"[Update] Restart Pitwall IQ to apply the update.")
            with state_lock:
                state["update_available"] = remote_ver
    except Exception as e:
        log.debug("Auto-update check failed: %s", e)

def _lb_post(payload, background=True):
    """POST payload dict to leaderboard /api/lb-submit.

    background=True  fires a daemon thread (normal PB submission).
    background=False submits synchronously and returns the result dict.
    """
    if not LEADERBOARD_URL:
        return None
    def _run():
        try:
            from urllib.request import urlopen, Request as UReq
            data = json.dumps(payload).encode()
            url = f"{LEADERBOARD_URL}/api/lb-submit"
            req = UReq(url, data=data,
                       headers={"Content-Type": "application/json"},
                       method="POST")
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            if result.get("rank"):
                with state_lock:
                    lb = state.get("leaderboard") or {}
                    lb["player_rank"] = result["rank"]
                    state["leaderboard"] = lb
            if not result.get("ok") and result.get("error"):
                with state_lock:
                    state["lb_error"] = result["error"]
            return result
        except urllib.error.URLError as exc:
            log.debug("lb-submit URLError: %s", exc)
            _warn_backend_unreachable("Leaderboard")
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.debug("lb-submit error: %s", exc)
            print(f"[lb-submit] ERROR: {exc}")
            return {"ok": False, "error": str(exc)}
    if background:
        threading.Thread(target=_run, daemon=True).start()
        return None
    return _run()

def _lb_seed_all():
    """Submit every personal best to the community leaderboard synchronously."""
    if not LEADERBOARD_URL:
        print("[lb-seed] Skipped — no LEADERBOARD_URL configured")
        return 0
    with state_lock:
        player_id    = state.get("player_id") or ""
        display_name = state.get("display_name") or "Anonymous"
    if not player_id:
        print("[lb-seed] Skipped — no player_id in state")
        return 0
    pbs = db_get_all_pbs()
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    count = 0
    for pb in pbs:
        if not pb.get("lap_time_ms"):
            continue
        result = _lb_post({
            "player_id":    player_id,
            "display_name": display_name,
            "track":        pb["track"],
            "session_type": pb["session_type"],
            "lap_time_ms":  int(pb["lap_time_ms"]),
            "lap_time":     pb["lap_time"],
            "compound":     pb.get("compound") or "",
            "submitted_at": now,
        }, background=False)
        ok = result and result.get("ok")
        print(f"[lb-seed] {pb['track']} / {pb['session_type']}: {'ok rank #' + str(result.get('rank')) if ok else result}")
        if ok:
            count += 1
    return count


def _lb_refresh(track_override=None, session_type_override=None):
    """Fetch leaderboard for the given (or current) track from Azure and cache in state."""
    if not LEADERBOARD_URL:
        return
    try:
        from urllib.request import urlopen
        from urllib.parse import quote
        with state_lock:
            track        = track_override or state["session"].get("track", "Unknown")
            session_type = session_type_override or state["session"].get("session_type", "Unknown")
            player_id    = state.get("player_id") or ""
        if track in ("Unknown", None, ""):
            # No active session — fall back to the most recently driven track
            con = sqlite3.connect(DB_PATH)
            row = con.execute(
                "SELECT track, session_type FROM personal_bests "
                "ORDER BY set_at DESC LIMIT 1"
            ).fetchone()
            con.close()
            if not row:
                return
            track, session_type = row[0], row[1]
        url = (f"{LEADERBOARD_URL}/api/leaderboard"
               f"/{quote(track, safe='')}/{quote(session_type, safe='')}"
               f"?player_id={player_id}")
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        with state_lock:
            state["leaderboard"] = data
            _backend_warned.discard("Leaderboard")
    except urllib.error.URLError as e:
        log.debug("Leaderboard fetch failed: %s", e)
        _warn_backend_unreachable("Leaderboard")
    except Exception as e:
        log.debug("Leaderboard fetch failed: %s", e)

def leaderboard_worker():
    """Background thread: refresh community leaderboard every 60 s."""
    while True:
        time.sleep(60)
        _lb_refresh()

# ── AI lap debrief (proxied via Pitwall IQ Azure Function) ────────────────────

def _ai_debrief_proxy(laps, session_info, best_lap_ms, track_pb_ms, track_pb_compound, player_id):
    """POST lap data to the Pitwall IQ proxy Function and return (debrief_text, remaining)."""
    from urllib.request import urlopen, Request as UReq
    payload = json.dumps({
        "player_id":      player_id,
        "laps":           laps,
        "session":        session_info,
        "best_lap_ms":    best_lap_ms,
        "track_pb_ms":    track_pb_ms,
        "track_pb_compound": track_pb_compound,
    }).encode()
    req = UReq(
        f"{PITWALL_PROXY_URL}/api/debrief",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=35) as resp:
        result = json.loads(resp.read())
    return result["debrief"], result.get("remaining")

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
            elif pid == 6:
                parse_car_telemetry_packet(data, pidx)
            elif pid == 7:
                parse_car_status_packet(data, pidx)
            elif pid == 0:
                parse_motion_packet(data, pidx)
            elif pid == 3:
                parse_event_packet(data, pidx)
            elif pid == 8:
                parse_final_classification_packet(data, pidx)
            elif pid == 10:
                parse_car_damage_packet(data, pidx)
        except socket.timeout:
            pass
        except Exception as e:
            log.debug("UDP packet error: %s", e)

# ── HTTP Server (dashboard) ───────────────────────────────────────────────────

# Dashboard HTML is served from static/dashboard.html



class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # silence request logs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/logo":
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.PNG")
            if os.path.exists(logo_path):
                with open(logo_path, "rb") as f:
                    img_data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", len(img_data))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(img_data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif parsed.path.startswith("/api/track-svg/"):
            name = os.path.basename(parsed.path.split("/api/track-svg/", 1)[1])
            svg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "assets", "tracks", f"{name}.svg")
            if os.path.exists(svg_path):
                with open(svg_path, "rb") as f:
                    svg_data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", len(svg_data))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(svg_data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif parsed.path == "/api/state":
            with state_lock:
                track_name = state["session"].get("track", "")
                out = dict(state)
                out["track_svg"] = TRACK_SVG.get(track_name)
                state["lb_error"] = None  # clear after delivering to client
                payload = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/career":
            recent = db_get_recent_races()
            stats  = db_get_career_stats()
            payload = json.dumps({"stats": stats, "recent": recent}).encode()
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
            qs = parse_qs(parsed.query)
            track_filter = qs.get("track", [None])[0]
            con = sqlite3.connect(DB_PATH)
            con.row_factory = sqlite3.Row
            _valid = "track IS NOT NULL AND track != '' AND track != 'Unknown' " \
                     "AND session_type IS NOT NULL AND session_type != '' AND session_type != 'Unknown'"
            if track_filter:
                rows = con.execute(
                    f"SELECT * FROM personal_bests WHERE track=? AND {_valid} ORDER BY session_type",
                    (track_filter,)
                ).fetchall()
            else:
                rows = con.execute(
                    f"SELECT * FROM personal_bests WHERE {_valid} ORDER BY track, session_type"
                ).fetchall()
            con.close()
            pbs = [dict(r) for r in rows]
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

        elif parsed.path == "/api/leaderboard":
            with state_lock:
                payload = json.dumps(state.get("leaderboard") or {}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)


        elif parsed.path == "/api/motion":
            with state_lock:
                trace   = state["lap_trace"]
                outline = state["track_outline"]
                # Thin to max 800 points each for a lean response
                def _thin(pts, n=800):
                    if len(pts) <= n:
                        return pts
                    step = len(pts) // n
                    return pts[::step]
                payload = json.dumps({
                    "car_pos":             state["car_pos"],
                    "car_speed":           state["car_speed"],
                    "car_gear":            state["car_gear"],
                    "rev_lights_pct":      state["rev_lights_pct"],
                    "lap_trace":           _thin(trace),
                    "track_outline":       _thin(outline),
                    "last_sector":         state["last_sector"],
                    "current_sector":      state["current_sector"],
                    "fuel_in_tank":        state["fuel_in_tank"],
                    "fuel_capacity":       state["fuel_capacity"],
                    "fuel_remaining_laps": state["fuel_remaining_laps"],
                }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path.startswith("/api/lap-trace/"):
            # /api/lap-trace/{session_id}/{lap_num}
            parts = parsed.path.split("/")
            try:
                session_id = int(parts[-2])
                lap_num    = int(parts[-1])
                con = sqlite3.connect(DB_PATH)
                row = con.execute(
                    "SELECT trace, tyre_wear, tyre_damage FROM laps WHERE session_id=? AND lap_num=?",
                    (session_id, lap_num)
                ).fetchone()
                con.close()
                trace_data      = json.loads(row[0]) if row and row[0] else []
                tyre_wear_data  = json.loads(row[1]) if row and len(row) > 1 and row[1] else None
                tyre_damage_data= json.loads(row[2]) if row and len(row) > 2 and row[2] else None
                payload = json.dumps({
                    "trace":       trace_data,
                    "tyre_wear":   tyre_wear_data,
                    "tyre_damage": tyre_damage_data,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                log.debug("Trace fetch error: %s", e)
                self.send_response(400)
                self.end_headers()

        elif parsed.path == "/api/ai-config":
            payload = json.dumps({"enabled": bool(PITWALL_PROXY_URL)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/lb-config":
            with state_lock:
                cfg = {
                    "enabled":      bool(LEADERBOARD_URL),
                    "opt_in":       state.get("leaderboard_opt_in", False),
                    "display_name": state.get("display_name", "Anonymous"),
                }
            payload = json.dumps(cfg).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        else:
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dashboard.html")
            try:
                with open(html_path, "rb") as fh:
                    body = fh.read()
            except OSError:
                body = b"<h1>Dashboard not found &mdash; ensure static/dashboard.html exists.</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/lb-refresh":
            length = int(self.headers.get('Content-Length', 0) or 0)
            body = {}
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except Exception as e:
                    log.debug("POST body parse error: %s", e)
            threading.Thread(
                target=_lb_refresh,
                kwargs={
                    'track_override':        body.get('track'),
                    'session_type_override': body.get('session_type'),
                },
                daemon=True,
            ).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        elif parsed.path == "/api/lb-seed":
            count = _lb_seed_all()
            payload = json.dumps({"ok": True, "submitted": count}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        elif parsed.path == "/api/clear":
            old_session_id = None
            with state_lock:
                old_session_id = state["current_session_id"]
                state["laps"].clear()
                state["best_lap_ms"] = None
                state["best_lap_num"] = None
                state["current_lap"] = 1
                state["last_recorded_lap_ms"] = 0
                state["session"]["started_at"] = None
                state["current_session_id"] = None
                state["lap_trace"].clear()
                state["track_outline"].clear()
            if old_session_id is not None:
                db_close_session(old_session_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        elif parsed.path == "/api/debrief":
            with state_lock:
                laps_snap    = list(state["laps"])
                session_snap = dict(state["session"])
                best_ms      = state["best_lap_ms"]
                track_pb_ms  = state["track_pb_ms"]
                track_pb_cmp = state["track_pb_compound"]
                player_id    = state.get("player_id", "")
            if not laps_snap:
                err = json.dumps({"error": "No laps recorded yet"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(err))
                self.end_headers()
                self.wfile.write(err)
                return
            try:
                text, remaining = _ai_debrief_proxy(
                    laps_snap, session_snap, best_ms, track_pb_ms, track_pb_cmp, player_id
                )
                out = json.dumps({"debrief": text, "remaining": remaining}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(out))
                self.end_headers()
                self.wfile.write(out)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                log.warning("AI debrief HTTP %s: %s", exc.code, body)
                try:
                    msg = json.loads(body).get("error") or body
                except Exception:
                    msg = body or f"HTTP {exc.code}"
                err = json.dumps({"error": msg}).encode()
                self.send_response(exc.code if exc.code in (400, 429) else 500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(err))
                self.end_headers()
                self.wfile.write(err)
            except urllib.error.URLError as exc:
                _warn_backend_unreachable("AI Debrief")
                log.warning("AI debrief URLError: %s", exc)
                err = json.dumps({"error": "AI debrief backend is currently unreachable. Please try again later."}).encode()
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(err))
                self.end_headers()
                self.wfile.write(err)
            except Exception as exc:
                log.debug("AI debrief error: %s", exc)
                err = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(err))
                self.end_headers()
                self.wfile.write(err)

        elif parsed.path == "/api/lb-settings":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            opt_in       = bool(body.get("opt_in", False))
            display_name = str(body.get("display_name", "Anonymous"))[:32].strip() or "Anonymous"
            with state_lock:
                state["leaderboard_opt_in"] = opt_in
                state["display_name"]       = display_name
            db_save_config("leaderboard_opt_in", "1" if opt_in else "0")
            db_save_config("display_name", display_name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

def main():
    parser = argparse.ArgumentParser(description="Pitwall IQ — F1 Lap Time Tracker")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s: %(message)s")

    print("=" * 50)
    print("  Pitwall IQ — F1 Lap Time Tracker")
    print("=" * 50)
    print()
    print("IN-GAME SETUP (F1 25):")
    print("  Settings → Telemetry Settings")
    print("    UDP Telemetry  : On")
    print("    UDP Format     : 2025")
    print("    UDP IP Address : 127.0.0.1")
    print("    UDP Port       : 20777")
    print("    Broadcast Mode : Off")
    print()

    init_db()
    print(f"💾  Database → {os.path.abspath(DB_PATH)}")
    print()

    cfg = init_config()
    career = db_get_career_stats()
    with state_lock:
        state["player_id"]         = cfg["player_id"]
        state["career_stats"]      = career
        state["leaderboard_opt_in"] = cfg["leaderboard_opt_in"]
        state["display_name"]      = cfg["display_name"]
        state["leaderboard_enabled"] = bool(LEADERBOARD_URL)
    if PITWALL_PROXY_URL:
        print(f"🤖  AI Debrief  → {PITWALL_PROXY_URL}")
    if LEADERBOARD_URL:
        print(f"🌍  Leaderboard → {LEADERBOARD_URL}")
        lb_thread = threading.Thread(target=leaderboard_worker, daemon=True)
        lb_thread.start()
        _lb_refresh()   # immediate first fetch

    # Start UDP listener in background
    t = threading.Thread(target=udp_listener, daemon=True)
    t.start()

    # Check for updates in background (after startup settles)
    threading.Thread(target=_check_and_apply_update, daemon=True).start()

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", 5000), Handler)
    print(f"🌐  Dashboard → http://localhost:5000  (v{VERSION})")
    print()
    print("Press Ctrl+C to stop.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        with state_lock:
            open_session_id = state.get("current_session_id")
        if open_session_id is not None:
            db_close_session(open_session_id)
        print("\nStopped.")

if __name__ == "__main__":
    main()
