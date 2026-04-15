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
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

# ── Leaderboard config ───────────────────────────────────────────────────────
# Default URL is the shared Pitwall IQ backend — no configuration needed.
# Override by setting F1_LEADERBOARD_URL if you host your own instance.
LEADERBOARD_URL = os.environ.get(
    "F1_LEADERBOARD_URL",
    "https://f1tracker-func-6v3lqkyuhxwkc.azurewebsites.net",
).rstrip("/")
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
    "udp_connected": False,
    "player_position": 0,
    "total_laps": 0,
    "last_recorded_lap_ms": 0,  # tracks last lap time we saved, to catch final lap
    "car_pos": {"x": 0.0, "z": 0.0},  # current world position
    "car_speed": 0,                    # current speed km/h
    "car_throttle": 0.0,               # throttle input 0.0–1.0
    "car_brake": 0.0,                  # brake input 0.0–1.0
    "car_gear": 0,                     # current gear (-1=R, 0=N, 1–8)
    "g_lat": 0.0,                      # lateral g-force
    "g_lon": 0.0,                      # longitudinal g-force
    "current_sector": 0,               # 0=S1, 1=S2, 2=S3
    "lap_trace": [],                   # [{x,z,speed,throttle,brake,gear,gLat,gLon,sector}] current lap
    "track_outline": [],               # reference trace from last completed lap
    "career_stats": {"races":0,"wins":0,"podiums":0,"points":0,"fastest_laps":0,"dnfs":0},
    "race_result": None,               # populated when Final Classification packet (ID 8) arrives
    "player_fastest_lap": False,       # set True when FTLP event fires for the player
    "race_result_saved_sid": None,     # session ID for which race result was already saved
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
    # Migration: add trace column if upgrading from older DB
    try:
        con.execute("ALTER TABLE laps ADD COLUMN trace TEXT")
    except Exception:
        pass
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

def db_save_lap(session_id, lap, trace=None):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO laps
           (session_id, lap_num, lap_time_ms, lap_time, s1_ms, s2_ms, s3_ms, invalid, timestamp, compound, trace)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, lap["lap_num"], lap["lap_time_ms"], lap["lap_time"],
         lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], int(lap["invalid"]),
         lap["timestamp"], lap.get("compound"),
         json.dumps(trace) if trace else None)
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
            SUM(CASE WHEN position = 1 AND result_status = 3 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN position <= 3 AND result_status = 3 THEN 1 ELSE 0 END) AS podiums,
            SUM(points)                                                   AS points,
            SUM(fastest_lap)                                              AS fastest_laps,
            SUM(CASE WHEN result_status IN (4,7) THEN 1 ELSE 0 END)      AS dnfs
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
        if save_session_id is not None:
            with state_lock:
                if state["lap_trace"]:
                    saved_trace = list(state["lap_trace"])
                    state["track_outline"] = saved_trace
                state["lap_trace"] = []

        if save_session_id is not None:
            db_save_lap(save_session_id, lap_record, trace=saved_trace)
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
    except Exception:
        pass

# Packet ID 7 – Car Status Data

CAR_STATUS_SIZE    = 55  # F1 25 per-car car status size
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
            brake    = state["car_brake"]
            gear     = state["car_gear"]
            sector   = state["current_sector"]
            trace    = state["lap_trace"]
            # Subsample: only store a point if car has moved far enough
            if len(trace) < _TRACE_MAX_PTS:
                if not trace or (abs(x - trace[-1]["x"]) + abs(z - trace[-1]["z"])) >= _TRACE_MIN_DIST:
                    trace.append({
                        "x": round(x, 1), "z": round(z, 1),
                        "speed": spd, "sector": sector,
                        "throttle": throttle, "brake": brake, "gear": gear,
                        "gLat": round(g_lat, 2), "gLon": round(g_lon, 2),
                    })
    except Exception:
        pass

def parse_car_telemetry_packet(data, player_idx):
    try:
        base = HEADER_SIZE + player_idx * CAR_TELEMETRY_SIZE
        if len(data) < base + 16:
            return
        # +0 speed(u16)  +2 throttle(f32)  +6 steer(f32)  +10 brake(f32)  +15 gear(i8)
        speed    = struct.unpack_from("<H",  data, base +  0)[0]
        throttle = struct.unpack_from("<f",  data, base +  2)[0]
        brake    = struct.unpack_from("<f",  data, base + 10)[0]
        gear     = struct.unpack_from("<b",  data, base + 15)[0]
        with state_lock:
            state["car_speed"]    = int(speed)
            state["car_throttle"] = round(max(0.0, min(1.0, throttle)), 3)
            state["car_brake"]    = round(max(0.0, min(1.0, brake)),    3)
            state["car_gear"]     = int(gear)
    except Exception:
        pass

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
    except Exception:
        pass

# Packet ID 8 – Final Classification Data
def parse_final_classification_packet(data, player_idx):
    try:
        base = HEADER_SIZE
        if len(data) < base + 1:
            return
        num_cars = struct.unpack_from("<B", data, base)[0]
        if player_idx >= num_cars:
            return
        car_base = base + 1 + player_idx * FINAL_CLASS_SIZE
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

        # Only save when the race is actually over — status must be Finished,
        # DNF, DSQ, N/C, or Retired. Ignore Invalid/Inactive/Active packets
        # which the game sends during formation lap and mid-race.
        FINAL_STATUSES = {3, 4, 5, 6, 7}  # Finished, DNF, DSQ, N/C, Retired
        if result_status not in FINAL_STATUSES:
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
        stats = db_get_career_stats()
        with state_lock:
            state["career_stats"] = stats
    except Exception:
        pass

# ── Community leaderboard ─────────────────────────────────────────────────────

def _lb_post(payload):
    """POST payload dict to leaderboard /api/lb-submit in background."""
    if not LEADERBOARD_URL:
        return
    def _run():
        try:
            from urllib.request import urlopen, Request as UReq
            data = json.dumps(payload).encode()
            req = UReq(
                f"{LEADERBOARD_URL}/api/lb-submit",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if result.get("rank"):
                    with state_lock:
                        lb = state.get("leaderboard") or {}
                        lb["player_rank"] = result["rank"]
                        state["leaderboard"] = lb
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

def _lb_refresh():
    """Fetch leaderboard for current track from Azure and cache in state."""
    if not LEADERBOARD_URL:
        return
    try:
        from urllib.request import urlopen
        from urllib.parse import quote
        with state_lock:
            track        = state["session"].get("track", "Unknown")
            session_type = state["session"].get("session_type", "Unknown")
            player_id    = state.get("player_id") or ""
        if track in ("Unknown", None):
            return
        url = (f"{LEADERBOARD_URL}/api/leaderboard"
               f"/{quote(track, safe='')}/{quote(session_type, safe='')}"
               f"?player_id={player_id}")
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        with state_lock:
            state["leaderboard"] = data
    except Exception:
        pass

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
<title>Pitwall IQ</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Inter:wght@400;500&display=swap" rel="stylesheet">
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
    /* Glass / depth system */
    --glass: rgba(255,255,255,.035);
    --glass-hi: rgba(255,255,255,.07);
    --glass-border: rgba(255,255,255,.09);
    --shadow-panel: 0 4px 28px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.06);
    --shadow-sm: 0 2px 10px rgba(0,0,0,.4);
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
    background-image: radial-gradient(ellipse 70% 50% at 8% 50%, color-mix(in srgb, var(--red) 7%, transparent) 0%, transparent 65%);
  }

/* ambient vignette overlay */
body::before {
content: '';
position: fixed; inset: 0;
background:
  radial-gradient(ellipse 80% 50% at 50% 0%, transparent 40%, rgba(0,0,0,.5) 100%),
  radial-gradient(ellipse 50% 40% at 85% 85%, rgba(0,0,0,.3) 0%, transparent 70%);
pointer-events: none;
z-index: 999;
}

header {
display: flex;
align-items: center;
justify-content: space-between;
padding: 12px 28px;
border-bottom: 1px solid var(--glass-border);
background: linear-gradient(90deg, var(--header-tint) 0%, rgba(17,17,20,.9) 100%);
backdrop-filter: blur(24px);
-webkit-backdrop-filter: blur(24px);
position: sticky;
top: 0;
z-index: 100;
box-shadow: 0 1px 0 var(--glass-border), 0 4px 24px rgba(0,0,0,.6);
}
.logo {
font-family: 'Orbitron', sans-serif;
font-weight: 900;
font-size: 2.2rem;
letter-spacing: .12em;
color: var(--red);
text-shadow: 0 0 28px var(--logo-glow);
line-height: 1;
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

.app-wrap {
display: flex;
align-items: flex-start;
}
.sidebar {
width: 420px;
flex-shrink: 0;
position: sticky;
top: 0;
max-height: 100vh;
overflow-y: auto;
padding: 20px 16px;
border-right: 1px solid var(--glass-border);
display: flex;
flex-direction: column;
gap: 16px;
}
.main-col {
flex: 1;
min-width: 0;
padding: 20px;
}
.below-grid {
display: grid;
grid-template-columns: 1fr 1fr;
gap: 16px;
margin-top: 16px;
}

.panel {
background: linear-gradient(145deg, var(--glass-hi) 0%, var(--glass) 100%);
border: 1px solid var(--glass-border);
border-radius: 14px;
padding: 20px;
position: relative;
overflow: hidden;
box-shadow: var(--shadow-panel);
backdrop-filter: blur(8px);
-webkit-backdrop-filter: blur(8px);
}
/* Collapsible panels */
.panel-title.collapsible { cursor: pointer; user-select: none; display: flex; justify-content: space-between; align-items: center; }
.panel-title.collapsible:hover { color: #fff; }
.collapse-arrow { font-size: .85rem; color: #aaa; transition: transform .2s; display: inline-block; background: rgba(255,255,255,.08); border-radius: 3px; padding: 1px 5px; line-height: 1.4; }
.panel-title.collapsible:hover .collapse-arrow { color: #fff; background: rgba(255,255,255,.16); }
.panel.collapsed .collapse-arrow { transform: rotate(-90deg); }
.panel.collapsed .collapsible-body { display: none; }
.panel::before {
content: '';
position: absolute; top: 0; left: 12%; right: 12%; height: 1px;
background: linear-gradient(90deg, transparent, var(--red), transparent);
opacity: .85;
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
font-size: 2.5rem;
font-weight: 700;
color: var(--text);
line-height: 1;
margin-bottom: 6px;
letter-spacing: -.02em;
}
.big-num.gold { color: var(--gold); text-shadow: 0 0 28px rgba(255,215,0,.5), 0 0 56px rgba(255,215,0,.18); }
.big-num.red { color: var(--red); text-shadow: 0 0 22px rgba(225,6,0,.45); }
.sub-label { font-size: .7rem; color: var(--muted); }

/* Sector strips */
.sectors {
display: grid;
grid-template-columns: 1fr 1fr 1fr;
gap: 8px;
}
.sector {
background: linear-gradient(145deg, var(--glass-hi) 0%, var(--glass) 100%);
border: 1px solid var(--glass-border);
border-radius: 8px;
padding: 12px 8px;
text-align: center;
box-shadow: var(--shadow-sm);
transition: border-color .2s;
}
.sector-label { font-size: .6rem; color: var(--muted); margin-bottom: 4px; letter-spacing: .15em; }
.sector-time { font-family: 'Orbitron', sans-serif; font-size: .95rem; color: var(--text); }
.sector-time.purple { color: var(--purple); }

/* Session info */
.info-row { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,.05); font-size: .8rem; }
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
tbody tr { border-bottom: 1px solid rgba(255,255,255,.04); transition: background .15s; }
tbody tr:hover { background: rgba(255,255,255,.05); }
tbody tr.best-lap { background: rgba(255,215,0,.07); }
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

/* sessions/pbs/lb wrapper — full width within their container */

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
background: var(--glass);
border: 1px solid var(--glass-border);
color: var(--muted);
font-family: 'Share Tech Mono', monospace;
font-size: .7rem;
padding: 7px 16px;
cursor: pointer;
border-radius: 6px;
letter-spacing: .08em;
transition: all .2s;
text-decoration: none;
display: inline-block;
backdrop-filter: blur(4px);
}
.btn:hover { border-color: var(--red); color: var(--red); background: rgba(225,6,0,.09); }
.btn-danger:hover { background: rgba(225,6,0,.14); }
.btn-green { border-color: rgba(0,214,143,.22); color: var(--green); }
.btn-green:hover { border-color: var(--green); background: rgba(0,214,143,.1); color: var(--green); }

/* Past sessions */
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

/* Leaderboard settings in header */
.lb-input {
background: var(--glass);
border: 1px solid var(--glass-border);
color: var(--text);
font-family: 'Share Tech Mono', monospace;
font-size: .7rem;
padding: 6px 10px;
border-radius: 6px;
outline: none;
width: 130px;
transition: border-color .2s;
backdrop-filter: blur(4px);
}
.lb-input:focus { border-color: var(--red); }
.lb-input::placeholder { color: var(--muted); }
.btn-toggle.active { border-color: var(--green); color: var(--green); }

/* Sector mini-best highlight */
td.sector.s-best { background: rgba(167,139,250,.18); color: var(--purple) !important; font-weight: 700; border-radius: 3px; }
/* Tabs */
.tab-bar { display:flex; gap:0; margin-bottom:16px; border-bottom:1px solid var(--glass-border); }
.tab { background:none; border:none; border-bottom:2px solid transparent; color:var(--muted); font-family:'Orbitron',sans-serif; font-size:.7rem; letter-spacing:.1em; padding:10px 24px; cursor:pointer; margin-bottom:-1px; transition:all .2s; border-radius:6px 6px 0 0; }
.tab.active { color:var(--red); border-bottom-color:var(--red); background:rgba(255,255,255,.03); }
.tab:hover:not(.active) { color:var(--text); background:rgba(255,255,255,.03); }
/* Career panel */
.career-summary { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.stat-box { flex:1; min-width:72px; background:linear-gradient(145deg, var(--glass-hi) 0%, var(--glass) 100%); border:1px solid var(--glass-border); border-radius:10px; padding:14px 10px; text-align:center; box-shadow:var(--shadow-sm); transition:border-color .2s, transform .15s; }
.stat-box:hover { border-color:rgba(255,255,255,.16); transform:translateY(-1px); }
.stat-val { font-family:'Orbitron',sans-serif; font-size:1.3rem; font-weight:700; color:var(--text); }
.stat-lbl { font-size:.6rem; color:var(--muted); letter-spacing:.1em; margin-top:3px; }
.fl-badge { background:var(--purple); color:#fff; font-size:.6rem; padding:1px 5px; border-radius:2px; margin-right:4px; font-weight:700; vertical-align:middle; }
td.finish-gold { color:#ffd700; font-weight:700; }
td.finish-silver { color:#c0c0c0; font-weight:700; }
td.finish-bronze { color:#cd7f32; font-weight:700; }

/* Toast notifications */
#toast-container { position:fixed; top:20px; right:20px; z-index:9999; display:flex; flex-direction:column; gap:8px; pointer-events:none; }
.toast { background:rgba(17,17,20,.88); border:1px solid var(--glass-border); border-radius:10px; padding:12px 20px; font-size:.78rem; letter-spacing:.04em; opacity:1; transition:opacity .35s; min-width:220px; backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px); box-shadow:0 8px 32px rgba(0,0,0,.5); }
.toast.pb     { border-color:var(--purple); color:var(--purple); }
.toast.sector { border-color:var(--yellow); color:var(--yellow); }
.toast.best   { border-color:var(--green);  color:var(--green);  }

/* Lap comparison */
.comp-cell { white-space:nowrap; }
.comp-btn { font-size:.58rem; padding:1px 5px; border-radius:2px; border:1px solid var(--border); background:none; cursor:pointer; color:var(--muted); letter-spacing:.06em; margin-left:2px; line-height:1.6; }
.comp-btn:hover { opacity:.75; }
.comp-btn.a-sel { border-color:#4fc3f7; color:#4fc3f7; }
.comp-btn.b-sel { border-color:#f7a44c; color:#f7a44c; }
.comp-tag-a { color:#4fc3f7; }
.comp-tag-b { color:#f7a44c; }
#comp-bar { display:none; align-items:center; gap:10px; padding:8px 14px; background:var(--glass); border:1px solid var(--glass-border); border-radius:8px; font-size:.72rem; letter-spacing:.05em; margin-bottom:12px; backdrop-filter:blur(4px); }
tr.comp-a-row td { background:rgba(79,195,247,.07); }
tr.comp-b-row td { background:rgba(247,164,76,.07); }

/* Telemetry charts */
.telem-wrap { display: flex; gap: 10px; align-items: flex-start; margin-top: 4px; }
.telem-charts { flex: 1; min-width: 0; }
.telem-gforce-wrap { width: 160px; flex-shrink: 0; }
.telem-label { font-size: .6rem; letter-spacing: .1em; color: var(--muted); margin-bottom: 2px; }

/* Community leaderboard panel */
.lb-wrap { padding-bottom: 8px; }
tr.lb-player { background: rgba(0,214,143,.08); }
tr.lb-player td { color: var(--green); }
td.lb-rank { color: var(--muted); font-size: .7rem; width: 32px; }
#tab-leaderboard .lb-wrap .lap-table-wrap { max-height: 600px; overflow-y: auto; }
td.lb-rank.top3 { color: var(--gold); font-family: 'Orbitron', sans-serif; font-weight: 700; }

/* AI Debrief panel */
.debrief-panel { border-color: rgba(199,125,255,.25) !important; }
.debrief-panel::before { background: linear-gradient(90deg, transparent, var(--purple), transparent) !important; }
.debrief-body { padding: 4px 0; }
.debrief-para { font-family: 'Inter', sans-serif; font-size: .92rem; line-height: 1.8; color: #d0d0d8; margin-bottom: 16px; letter-spacing: .01em; }
.debrief-para:last-child { margin-bottom: 0; }
.debrief-loading { color: var(--muted); font-size: .8rem; padding: 20px 0; animation: pulse 1.5s infinite; }

/* Logo + beta badge */
.logo-wrap { display:flex; align-items:center; gap:10px; }
.logo-img { height:180px; width:auto; display:block; mix-blend-mode: multiply; }
.beta-badge {
  font-family: 'Orbitron', sans-serif;
  font-size: .52rem;
  font-weight: 700;
  letter-spacing: .2em;
  color: var(--red);
  border: 1px solid color-mix(in srgb, var(--red) 60%, transparent);
  background: color-mix(in srgb, var(--red) 8%, transparent);
  padding: 4px 10px;
  border-radius: 5px;
  opacity: .9;
  align-self: flex-end;
  margin-bottom: 6px;
  white-space: nowrap;
}

/* Theme selector */
.theme-select {
background: var(--glass);
border: 1px solid var(--glass-border);
color: var(--muted);
font-family: 'Share Tech Mono', monospace;
font-size: .7rem;
padding: 6px 10px;
border-radius: 6px;
cursor: pointer;
letter-spacing: .06em;
outline: none;
transition: border-color .2s, color .2s;
backdrop-filter: blur(4px);
}
.theme-select:hover, .theme-select:focus { border-color: var(--red); color: var(--text); }
.theme-select option { background: #111; }

/* Track map */
#track-map-panel { display:none; }
#track-canvas { border-radius:8px; background:transparent; }
.map-mode-btn {
  font-size: .52rem; padding: 3px 8px; border-radius: 5px; cursor: pointer;
  background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted);
  font-family: 'Share Tech Mono', monospace; letter-spacing: .06em;
  transition: border-color .2s, color .2s, background .2s;
}
.map-mode-btn.active { border-color: var(--red); color: var(--red); background: rgba(225,6,0,.08); }

@media (max-width: 900px) {
.app-wrap { flex-direction: column; }
.sidebar { width: 100%; position: static; max-height: none; border-right: none; border-bottom: 1px solid var(--glass-border); flex-direction: row; flex-wrap: wrap; }
.sidebar .panel { flex: 1; min-width: 180px; }
.below-grid { grid-template-columns: 1fr; }
.big-num { font-size: 1.6rem; }
}
</style>

</head>
<body>
<header>
  <div class="logo-wrap">
    <div class="logo">PITWALL<span> IQ</span></div>
    <span class="beta-badge">IN DEVELOPMENT</span>
  </div>
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
    <div id="lb-controls" style="display:none;align-items:center;gap:8px;">
      <input id="lb-name" type="text" class="lb-input" placeholder="Display name" maxlength="32">
      <button id="lb-toggle" class="btn btn-toggle" onclick="toggleLBOptIn()">SUBMIT PBs: OFF</button>
    </div>
    <button id="debrief-btn" class="btn" style="display:none;border-color:#7b5ea7;color:var(--purple)" onclick="requestDebrief()">AI DEBRIEF</button>
    <button class="btn btn-green" onclick="exportCSV()">EXPORT CSV</button>
    <button class="btn btn-danger" onclick="clearSession()">CLEAR SESSION</button>
    <div>
      <span class="status-dot" id="dot"></span>
      <span class="status-text" id="status-text">Waiting for telemetry…</span>
    </div>
  </div>
</header>

<div class="app-wrap">
  <aside class="sidebar">
    <div id="sidebar-stats"><!-- stat panels filled by JS --></div>
    <div class="panel" id="track-map-panel">
      <div class="panel-title" style="display:flex;justify-content:space-between;align-items:center;">
        <span>Track Map</span>
        <div style="display:flex;gap:4px;">
          <button class="map-mode-btn active" id="map-btn-sector" onclick="setMapMode('sector')">S1/S2/S3</button>
          <button class="map-mode-btn" id="map-btn-speed" onclick="setMapMode('speed')">SPEED</button>
        </div>
      </div>
      <div style="position:relative;width:100%;aspect-ratio:1/1;">
        <img id="track-svg-img" src="" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;opacity:0.18;display:none;transform:scaleY(-1);">
        <canvas id="track-canvas" width="228" height="228" style="position:absolute;inset:0;width:100%;height:100%;"></canvas>
      </div>
      <div id="lap-nav" style="display:none;align-items:center;justify-content:space-between;margin-top:8px;">
        <button class="map-mode-btn" onclick="lapNavStep(-1)">&#8592;</button>
        <span id="lap-nav-label" style="font-size:.65rem;color:var(--muted);letter-spacing:.1em;"></span>
        <button class="map-mode-btn" onclick="lapNavStep(1)">&#8594;</button>
        <button class="map-mode-btn" id="lap-nav-live" onclick="lapNavLive()" style="margin-left:4px;border-color:var(--green);color:var(--green);">LIVE</button>
      </div>
    </div>
  </aside>
  <div class="main-col">
    <div class="tab-bar">
      <button class="tab active" id="tab-btn-session" onclick="switchTab('session')">SESSION</button>
      <button class="tab" id="tab-btn-career" onclick="switchTab('career')">CAREER</button>
      <button class="tab" id="tab-btn-leaderboard" onclick="switchTab('leaderboard')">LEADERBOARD</button>
    </div>
    <div id="tab-session">
    <div id="comp-bar">
      <span class="comp-tag-a" id="comp-label-a">A: —</span>
      <span style="color:var(--muted)">vs</span>
      <span class="comp-tag-b" id="comp-label-b">B: —</span>
      <button onclick="clearComparison()" style="margin-left:auto;font-size:.6rem;color:var(--muted);background:none;border:1px solid var(--border);border-radius:2px;padding:2px 8px;cursor:pointer;">CLEAR</button>
    </div>
    <div id="lap-table"></div>
    <div id="telemetry-section" style="display:none;margin-top:12px;">
      <div class="panel">
        <div class="panel-title" id="telem-title">Telemetry</div>
        <div class="telem-wrap">
          <div class="telem-charts">
            <div class="telem-label">SPEED (km/h)</div>
            <canvas id="speed-canvas" width="600" height="72" style="width:100%;display:block;"></canvas>
            <div class="telem-label" style="margin-top:6px;">THROTTLE &amp; BRAKE</div>
            <canvas id="inputs-canvas" width="600" height="56" style="width:100%;display:block;"></canvas>
          </div>
          <div class="telem-gforce-wrap">
            <div class="telem-label">G-FORCE</div>
            <canvas id="gforce-canvas" width="160" height="160" style="display:block;width:100%;"></canvas>
          </div>
        </div>
      </div>
    </div>
    <div class="below-grid">
      <div id="pbs-section"></div>
      <div id="sessions-section"></div>
    </div>
    <div id="debrief-section"></div>
    </div><!-- end tab-session -->
    <div id="tab-career" style="display:none">
      <div id="career-section"></div>
    </div>
    <div id="tab-leaderboard" style="display:none">
      <div id="lb-section"></div>
    </div>
  </div>
</div>

<script>
// ── Tab system ────────────────────────────────────────────────────────────────
function switchTab(name) {
  document.getElementById('tab-session').style.display     = name === 'session'     ? '' : 'none';
  document.getElementById('tab-career').style.display      = name === 'career'      ? '' : 'none';
  document.getElementById('tab-leaderboard').style.display = name === 'leaderboard' ? '' : 'none';
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.id === `tab-btn-${name}`)
  );
  if (name === 'career') loadCareer();
  if (name === 'leaderboard') fetchLeaderboard();
}

// ── Career stats ──────────────────────────────────────────────────────────────
const RACE_STATUS = {0:'Invalid',1:'Inactive',2:'Active',3:'Finished',4:'DNF',5:'DSQ',6:'N/C',7:'Retired'};
let _lastRaceResultTs = null;

async function loadCareer() {
  try {
    const r = await fetch('/api/career');
    const d = await r.json();
    renderCareer(d);
  } catch(e) {}
}

function renderCareer(d) {
  const { stats, recent } = d;
  const winPct = stats.races > 0 ? ((stats.wins / stats.races) * 100).toFixed(0) : 0;
  const rows = recent.map(r => {
    const pos = r.result_status === 3 ? r.position : null;
    const finishTxt = pos ? `P${pos}` : (RACE_STATUS[r.result_status] || '?');
    const finishCls = pos === 1 ? ' finish-gold' : pos === 2 ? ' finish-silver' : pos === 3 ? ' finish-bronze' : '';
    const fl = r.fastest_lap ? '<span class="fl-badge">FL</span>' : '';
    return `<tr>
      <td>${esc(r.track)}</td>
      <td style="color:var(--muted);font-size:.7rem">${esc(r.session_type)}</td>
      <td class="num">${r.grid_pos || '—'}</td>
      <td class="num${finishCls}">${finishTxt}</td>
      <td class="num">${r.points}</td>
      <td style="font-size:.7rem">${fl}${esc(r.best_lap || '—')}</td>
    </tr>`;
  }).join('');
  const section = document.getElementById('career-section');
  if (!section) return;
  section.innerHTML = `
    <div class="panel">
      <div class="panel-title">CAREER STATS</div>
      <div class="career-summary">
        <div class="stat-box"><div class="stat-val">${stats.races}</div><div class="stat-lbl">RACES</div></div>
        <div class="stat-box"><div class="stat-val">${stats.wins}</div><div class="stat-lbl">WINS</div></div>
        <div class="stat-box"><div class="stat-val">${stats.podiums}</div><div class="stat-lbl">PODIUMS</div></div>
        <div class="stat-box"><div class="stat-val">${stats.points}</div><div class="stat-lbl">POINTS</div></div>
        <div class="stat-box"><div class="stat-val">${stats.fastest_laps}</div><div class="stat-lbl">FAST LAPS</div></div>
        <div class="stat-box"><div class="stat-val">${stats.dnfs}</div><div class="stat-lbl">DNFs</div></div>
      </div>
      ${recent.length ? `
        <div class="lap-table-wrap" style="margin-top:14px">
          <table class="lap-table">
            <thead><tr>
              <th>TRACK</th><th>TYPE</th><th>GRID</th><th>FINISH</th><th>PTS</th><th>BEST LAP</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>` : '<p style="color:var(--muted);margin-top:12px;font-size:.8rem">No race results yet — finish a race session to start tracking your career.</p>'}
    </div>`;
}

// ── Community leaderboard ─────────────────────────────────────────────────────
let _lbOptIn = false;

async function initLB() {
  try {
    const r = await fetch('/api/lb-config');
    const c = await r.json();
    if (!c.enabled) return;
    document.getElementById('lb-controls').style.display = 'flex';
    document.getElementById('lb-name').value = c.display_name || '';
    _lbOptIn = c.opt_in;
    _updateToggle();
    fetchLeaderboard();
  } catch(e) {}
}

function _updateToggle() {
  const btn = document.getElementById('lb-toggle');
  if (!btn) return;
  btn.textContent = _lbOptIn ? 'SUBMIT PBs: ON' : 'SUBMIT PBs: OFF';
  btn.className   = 'btn btn-toggle' + (_lbOptIn ? ' active' : '');
}

async function toggleLBOptIn() {
  _lbOptIn = !_lbOptIn;
  _updateToggle();
  const name = document.getElementById('lb-name').value.trim() || 'Anonymous';
  await fetch('/api/lb-settings', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({opt_in: _lbOptIn, display_name: name}),
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const nameInput = document.getElementById('lb-name');
  if (nameInput) {
    nameInput.addEventListener('change', async () => {
      await fetch('/api/lb-settings', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({opt_in: _lbOptIn, display_name: nameInput.value.trim() || 'Anonymous'}),
      });
    });
  }
});

async function fetchLeaderboard() {
  try {
    const r = await fetch('/api/leaderboard');
    const d = await r.json();
    renderLeaderboard(d);
  } catch(e) {}
}

function renderLeaderboard(d) {
  const el = document.getElementById('lb-section');
  if (!d || !d.entries || d.entries.length === 0) {
    el.innerHTML = `<div class="panel lb-wrap">
      <div class="panel-title">Community Leaderboard</div>
      <p style="color:var(--muted);font-size:.75rem;margin:8px 0 0">
        ${(!d || !d.track) ? 'Waiting for session data…' : 'No times posted for this track yet.'}
      </p></div>`;
    return;
  }
  let rows = '';
  for (const e of d.entries) {
    const top3 = e.rank <= 3 ? 'top3' : '';
    rows += `<tr class="${e.is_player ? 'lb-player' : ''}">
      <td class="lb-rank ${top3}">${e.rank}</td>
      <td class="lap-time" style="${e.is_player ? '' : ''}">${e.lap_time}</td>
      <td>${compoundPill(e.compound)}</td>
      <td style="font-size:.78rem">${esc(e.display_name)}</td>
    </tr>`;
  }
  const title = `${d.track} · ${d.session_type}`;
  const rankNote = d.player_rank ? ` <span style="color:var(--green);font-size:.6rem">YOUR RANK: #${d.player_rank}</span>` : '';
  el.innerHTML = `<div class="panel lb-wrap">
    <div class="panel-title" style="display:flex;justify-content:space-between;">
      <span>Community Leaderboard — ${title}</span>
      ${rankNote}
    </div>
    <div class="lap-table-wrap">
      <table>
        <thead><tr><th>#</th><th>TIME</th><th>TYRE</th><th>DRIVER</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    </div>
  </div>`;
}

// ── AI Debrief ────────────────────────────────────────────────────────────────
async function initAI() {
  try {
    const r = await fetch('/api/ai-config');
    const c = await r.json();
    if (c.enabled) {
      document.getElementById('debrief-btn').style.display = 'inline-block';
    }
  } catch(e) {}
}

async function requestDebrief() {
  const btn = document.getElementById('debrief-btn');
  const section = document.getElementById('debrief-section');
  btn.textContent = 'GENERATING...';
  btn.disabled = true;
  section.innerHTML = `<div class="panel debrief-panel">
    <div class="panel-title">AI Debrief — Race Engineer</div>
    <div class="debrief-loading">Analysing your session data…</div>
  </div>`;
  try {
    const r = await fetch('/api/debrief', { method: 'POST' });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    renderDebrief(d);
  } catch(e) {
    section.innerHTML = `<div class="panel debrief-panel">
      <div class="panel-title">AI Debrief — Race Engineer</div>
      <div style="color:var(--red);font-size:.8rem">Error: ${esc(e.message)}</div>
    </div>`;
  } finally {
    btn.textContent = 'AI DEBRIEF';
    btn.disabled = false;
  }
}

function renderDebrief(data) {
  const section = document.getElementById('debrief-section');
  const paras = data.debrief.split(/\n\n+/).filter(p => p.trim());
  const html = paras.map(p => {
    const lines = p.split('\n').map(l => esc(l)).join('<br>');
    return `<p class="debrief-para">${lines}</p>`;
  }).join('');
  const remainingNote = data.remaining != null
    ? `<span style="color:var(--muted);font-size:.65rem">${data.remaining} debrief${data.remaining !== 1 ? 's' : ''} remaining today</span>`
    : '';
  section.innerHTML = `<div class="panel debrief-panel">
    <div class="panel-title" style="display:flex;justify-content:space-between;align-items:center;">
      <span>AI Debrief — Race Engineer</span>
      <div style="display:flex;align-items:center;gap:12px;">${remainingNote}<button class="btn" onclick="document.getElementById('debrief-section').innerHTML=''">DISMISS</button></div>
    </div>
    <div class="debrief-body">${html}</div>
  </div>`;
}

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
  _reviewLap = null; _reviewTotal = 0; _lapCount = 0; _sessionId = null; _updateLapNav();
  _compareA = null; _compareB = null; _compareTraceA = null; _compareTraceB = null;
  _toastedLapCount = 0; _sBestMs = [Infinity, Infinity, Infinity];
  _updateCompBar(); renderTelemetry([]);
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

// ── Toast notifications ───────────────────────────────────────────────────────
let _toastedLapCount = 0;
let _sBestMs = [Infinity, Infinity, Infinity]; // session-best S1/S2/S3 in ms

function showToast(msg, type = 'info', duration = 3500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 380);
  }, duration);
}

function _checkToasts(laps) {
  for (let i = _toastedLapCount; i < laps.length; i++) {
    const lap = laps[i];
    if (lap.is_track_pb) {
      showToast('🏆  New Track PB  ' + lap.lap_time, 'pb');
    }
    if (!lap.invalid) {
      if (lap.s1_ms > 0 && lap.s1_ms < _sBestMs[0]) {
        if (_sBestMs[0] !== Infinity) showToast('🟣  Best S1  ' + lap.s1, 'sector');
        _sBestMs[0] = lap.s1_ms;
      }
      if (lap.s2_ms > 0 && lap.s2_ms < _sBestMs[1]) {
        if (_sBestMs[1] !== Infinity) showToast('🟣  Best S2  ' + lap.s2, 'sector');
        _sBestMs[1] = lap.s2_ms;
      }
      if (lap.s3_ms > 0 && lap.s3_ms < _sBestMs[2]) {
        if (_sBestMs[2] !== Infinity) showToast('🟣  Best S3  ' + lap.s3, 'sector');
        _sBestMs[2] = lap.s3_ms;
      }
    }
  }
  _toastedLapCount = laps.length;
}

// ── Lap comparison ────────────────────────────────────────────────────────────
let _compareA = null, _compareB = null;
let _compareTraceA = null, _compareTraceB = null;

function _updateCompBar() {
  const bar = document.getElementById('comp-bar');
  if (!bar) return;
  const active = _compareA !== null || _compareB !== null;
  bar.style.display = active ? 'flex' : 'none';
  document.getElementById('comp-label-a').textContent = _compareA !== null ? `A: Lap ${_compareA}` : 'A: —';
  document.getElementById('comp-label-b').textContent = _compareB !== null ? `B: Lap ${_compareB}` : 'B: —';
}

async function selectCompareLap(slot, lapNum) {
  if (slot === 'A') { _compareA = lapNum; _compareTraceA = null; }
  else              { _compareB = lapNum; _compareTraceB = null; }
  _updateCompBar();
  // Fetch the trace for this lap
  const sid = _sessionId;
  if (sid) {
    try {
      const r = await fetch(`/api/lap-trace/${sid}/${lapNum}`);
      const d = await r.json();
      if (slot === 'A') _compareTraceA = d.trace || [];
      else              _compareTraceB = d.trace || [];
    } catch(e) {}
  }
  _renderComparisonOrLive();
  if (lastData) render(lastData); // refresh row highlight + button states
}

function clearComparison() {
  _compareA = null; _compareB = null;
  _compareTraceA = null; _compareTraceB = null;
  _updateCompBar();
  const title = document.getElementById('telem-title');
  if (title) title.textContent = 'Telemetry';
  if (lastData) render(lastData);
  // Restore live or review telemetry
  if (_reviewLap !== null && _compareTraceA === null) {
    _loadReviewLap();
  } else if (lastData) {
    renderTelemetry(lastData.lap_trace || []);
  }
}

function _renderComparisonOrLive() {
  const tA = _compareTraceA, tB = _compareTraceB;
  if (tA && tA.length >= 2 && tB && tB.length >= 2) {
    renderTelemetry(tA, tB);
  } else if (tA && tA.length >= 2) {
    renderTelemetry(tA);
  } else if (tB && tB.length >= 2) {
    renderTelemetry(tB);
  }
}

function _comparisonActive() {
  return _compareA !== null || _compareB !== null;
}

function _togglePanel(panelId) {
  const el = document.getElementById(panelId);
  if (!el) return;
  const collapsed = el.classList.toggle('collapsed');
  localStorage.setItem('collapsed_' + panelId, collapsed ? '1' : '0');
}
function _isCollapsed(panelId) {
  return localStorage.getItem('collapsed_' + panelId) === '1';
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
  const pbsCollapsed = _isCollapsed('pbs-panel');
  el.innerHTML = `<div class="panel${pbsCollapsed ? ' collapsed' : ''}" id="pbs-panel">
    <div class="panel-title collapsible" onclick="_togglePanel('pbs-panel')">
      <span>Personal Bests — All Time</span>
      <span class="collapse-arrow">▾</span>
    </div>
    <div class="collapsible-body lap-table-wrap">
      <table>
        <thead><tr>
          <th>TRACK</th><th>TYPE</th><th>TIME</th><th>TYRE</th><th>SET</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
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
  const sessCollapsed = _isCollapsed('sessions-panel');
  el.innerHTML = `<div class="panel${sessCollapsed ? ' collapsed' : ''}" id="sessions-panel">
    <div class="panel-title collapsible" onclick="_togglePanel('sessions-panel')">
      <span>Past Sessions</span>
      <span class="collapse-arrow">▾</span>
    </div>
    <div class="collapsible-body lap-table-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>TRACK</th><th>TYPE</th><th>WEATHER</th><th>STARTED</th><th>ENDED</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

function fmt(v) { return v || '--:--.---'; }

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

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

  const sidebar  = document.getElementById('sidebar-stats');
  const lapTable = document.getElementById('lap-table');

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
    <div class="info-row"><span class="info-key">TRACK</span><span class="info-val">${esc(d.session.track)}</span></div>
    <div class="info-row"><span class="info-key">TYPE</span><span class="info-val">${esc(d.session.session_type)}</span></div>
    <div class="info-row"><span class="info-key">WEATHER</span><span class="info-val">${esc(d.session.weather)}</span></div>
    <div class="info-row"><span class="info-key">POSITION</span><span class="info-val">${d.player_position > 0 ? 'P' + d.player_position : '—'}</span></div>
    ${pbRow}
  </div>`;

  // Lap table
  _checkToasts(d.laps);

  // Toast: race result (fires once when Final Classification packet arrives)
  if (d.race_result && d.race_result.recorded_at !== _lastRaceResultTs) {
    _lastRaceResultTs = d.race_result.recorded_at;
    const rr = d.race_result;
    const status = RACE_STATUS[rr.result_status] || '?';
    const msg = rr.result_status === 3
      ? `Race finished: P${rr.position} · ${rr.points} pts${rr.fastest_lap ? ' · Fastest Lap!' : ''}`
      : `Race ended: ${status}`;
    showToast(msg, rr.position === 1 ? 'pb' : 'info', 6000);
  }

  // Find best sector times across valid laps (for mini-best highlighting)
  const validLaps = d.laps.filter(l => !l.invalid);
  const bestS1ms = Math.min(...validLaps.filter(l => l.s1_ms > 0).map(l => l.s1_ms), Infinity);
  const bestS2ms = Math.min(...validLaps.filter(l => l.s2_ms > 0).map(l => l.s2_ms), Infinity);
  const bestS3ms = Math.min(...validLaps.filter(l => l.s3_ms > 0).map(l => l.s3_ms), Infinity);

  let rows = '';
  if (d.laps.length === 0) {
    rows = `<tr><td colspan="9" class="waiting"><div class="big-icon">🏎</div>
      <p>No laps recorded yet.<br>
      Make sure UDP telemetry is <code>ON</code> in F1 25 settings<br>
      IP: <code>127.0.0.1</code> &nbsp; Port: <code>20777</code></p></td></tr>`;
  } else {
    const reversed = [...d.laps].reverse();
    for (const lap of reversed) {
      const isBest    = lap.is_best;
      const isTrackPB = lap.is_track_pb;
      const isInvalid = lap.invalid;
      const isCompA   = _compareA === lap.lap_num;
      const isCompB   = _compareB === lap.lap_num;
      const s1Best = !isInvalid && lap.s1_ms > 0 && lap.s1_ms === bestS1ms;
      const s2Best = !isInvalid && lap.s2_ms > 0 && lap.s2_ms === bestS2ms;
      const s3Best = !isInvalid && lap.s3_ms > 0 && lap.s3_ms === bestS3ms;
      const deltaClass = lap.delta === 'PB!'  ? 'pb-text'
                       : lap.delta === 'BEST' ? 'best-text'
                       : (lap.delta && lap.delta.startsWith('+')) ? 'positive' : '';
      const timeLabel = isTrackPB ? lap.lap_time + ' 🏆'
                      : isBest    ? lap.lap_time + ' ★'
                      : lap.lap_time;
      const rowClass = [
        isBest ? 'best-lap' : '', isTrackPB ? 'track-pb-lap' : '',
        isInvalid ? 'invalid' : '', isCompA ? 'comp-a-row' : '', isCompB ? 'comp-b-row' : ''
      ].join(' ');
      rows += `<tr class="${rowClass}">
        <td class="lap-num">${lap.lap_num}</td>
        <td>${compoundPill(lap.compound)}</td>
        <td class="lap-time ${isTrackPB || isBest ? 'best' : ''}">${timeLabel}</td>
        <td class="delta ${deltaClass}">${lap.delta || ''}</td>
        <td class="sector${s1Best ? ' s-best' : ''}">${lap.s1 !== '--:--.---' ? lap.s1 : '—'}</td>
        <td class="sector${s2Best ? ' s-best' : ''}">${lap.s2 !== '--:--.---' ? lap.s2 : '—'}</td>
        <td class="sector${s3Best ? ' s-best' : ''}">${lap.s3 !== '--:--.---' ? lap.s3 : '—'}</td>
        ${isInvalid ? '<td><span class="invalid-pill">INVALID</span></td>' : '<td></td>'}
        <td class="comp-cell">
          <button class="comp-btn${isCompA ? ' a-sel' : ''}" onclick="selectCompareLap('A',${lap.lap_num})">A</button>
          <button class="comp-btn${isCompB ? ' b-sel' : ''}" onclick="selectCompareLap('B',${lap.lap_num})">B</button>
        </td>
      </tr>`;
    }
  }

  const p4 = `<div class="panel">
    <div class="panel-title" style="display:flex;justify-content:space-between;">
      <span>Lap History</span>
      <span style="color:var(--muted)">${d.laps.length} laps</span>
    </div>
    <div class="lap-table-wrap">
      <table>
        <thead><tr>
          <th>LAP</th><th>TYRE</th><th>TIME</th><th>DELTA</th><th>S1</th><th>S2</th><th>S3</th><th></th><th>CMP</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;

  sidebar.innerHTML  = p1 + p2 + p3;
  lapTable.innerHTML = p4;
  _updateTrackSvg(d.track_svg || null);
}

function msToLap(ms) {
  if (!ms || ms <= 0) return '--:--.---';
  const total = ms / 1000;
  const m = Math.floor(total / 60);
  const s = Math.floor(total % 60);
  const ms3 = Math.floor(ms % 1000);
  return `${m}:${String(s).padStart(2,'0')}.${String(ms3).padStart(3,'0')}`;
}

// ── Telemetry Charts ──────────────────────────────────────────────────────────

const _SECTOR_PALETTE = ['#e10600', '#f7c948', '#9b59b6'];

function renderTelemetry(traceA, traceB = null) {
  const sec = document.getElementById('telemetry-section');
  if (!traceA || traceA.length < 2) { sec.style.display = 'none'; return; }
  sec.style.display = 'block';
  const title = document.getElementById('telem-title');
  if (title) {
    if (traceB && traceB.length >= 2 && _compareA !== null && _compareB !== null) {
      title.innerHTML = `Telemetry &nbsp;<span class="comp-tag-a">LAP ${_compareA}</span> <span style="color:var(--muted)">vs</span> <span class="comp-tag-b">LAP ${_compareB}</span>`;
    } else {
      title.textContent = 'Telemetry';
    }
  }
  _renderSpeedChart(traceA, traceB);
  _renderInputsChart(traceA, traceB);
  _renderGForceChart(traceA, traceB);
}

function _chartPad() { return { t: 6, b: 14, l: 28, r: 4 }; }


function _renderSpeedChart(traceA, traceB = null) {
  const canvas = document.getElementById('speed-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const pad = _chartPad();
  const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;
  const nA = traceA.length;
  const speedsA = traceA.map(p => p.speed || 0);
  const speedsB = traceB ? traceB.map(p => p.speed || 0) : [];
  const allSpeeds = [...speedsA, ...speedsB];
  const minS = Math.min(...allSpeeds), maxS = Math.max(...allSpeeds, 1);
  const rng = maxS - minS || 1;

  // Grid lines every 50 km/h
  ctx.lineWidth = 1;
  for (let v = Math.ceil(minS / 50) * 50; v <= maxS; v += 50) {
    const y = pad.t + ch - ((v - minS) / rng) * ch;
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.28)'; ctx.font = '8px monospace';
    ctx.fillText(v, 0, y + 3);
  }

  // Sector colour bar (from trace A)
  let secStart = 0, lastSec = traceA[0].sector;
  for (let i = 1; i <= nA; i++) {
    if (i === nA || traceA[i].sector !== lastSec) {
      const x1 = pad.l + (secStart / (nA - 1)) * cw;
      const x2 = pad.l + (Math.min(i, nA - 1) / (nA - 1)) * cw;
      ctx.fillStyle = _SECTOR_PALETTE[lastSec] || 'rgba(255,255,255,0.15)';
      ctx.fillRect(x1, h - pad.b + 2, x2 - x1, 4);
      if (i < nA) { lastSec = traceA[i].sector; secStart = i; }
    }
  }

  // Trace B (orange, behind A)
  if (traceB && traceB.length >= 2) {
    const nB = traceB.length;
    ctx.beginPath();
    for (let i = 0; i < nB; i++) {
      const x = pad.l + (i / (nB - 1)) * cw;
      const y = pad.t + ch - ((speedsB[i] - minS) / rng) * ch;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.lineTo(pad.l + cw, pad.t + ch); ctx.lineTo(pad.l, pad.t + ch); ctx.closePath();
    ctx.fillStyle = 'rgba(247,164,76,0.10)'; ctx.fill();
    ctx.beginPath();
    for (let i = 0; i < nB; i++) {
      const x = pad.l + (i / (nB - 1)) * cw;
      const y = pad.t + ch - ((speedsB[i] - minS) / rng) * ch;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#f7a44c'; ctx.lineWidth = 1.5; ctx.lineJoin = 'round'; ctx.stroke();
  }

  // Trace A (blue, on top)
  ctx.beginPath();
  for (let i = 0; i < nA; i++) {
    const x = pad.l + (i / (nA - 1)) * cw;
    const y = pad.t + ch - ((speedsA[i] - minS) / rng) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.lineTo(pad.l + cw, pad.t + ch); ctx.lineTo(pad.l, pad.t + ch); ctx.closePath();
  ctx.fillStyle = 'rgba(79,195,247,0.10)'; ctx.fill();
  ctx.beginPath();
  for (let i = 0; i < nA; i++) {
    const x = pad.l + (i / (nA - 1)) * cw;
    const y = pad.t + ch - ((speedsA[i] - minS) / rng) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.strokeStyle = '#4fc3f7'; ctx.lineWidth = 1.5; ctx.lineJoin = 'round'; ctx.stroke();
}

function _drawInputLines(ctx, trace, pad, cw, ch, thrColor, thrFill, brkColor, brkFill) {
  const n = trace.length;
  // Throttle fill
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = pad.l + (i / (n - 1)) * cw;
    const y = pad.t + ch - (trace[i].throttle || 0) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.lineTo(pad.l + cw, pad.t + ch); ctx.lineTo(pad.l, pad.t + ch); ctx.closePath();
  ctx.fillStyle = thrFill; ctx.fill();
  ctx.strokeStyle = thrColor; ctx.lineWidth = 1.2; ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = pad.l + (i / (n - 1)) * cw;
    const y = pad.t + ch - (trace[i].throttle || 0) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
  // Brake fill
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = pad.l + (i / (n - 1)) * cw;
    const y = pad.t + (trace[i].brake || 0) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.lineTo(pad.l + cw, pad.t); ctx.lineTo(pad.l, pad.t); ctx.closePath();
  ctx.fillStyle = brkFill; ctx.fill();
  ctx.strokeStyle = brkColor; ctx.lineWidth = 1.2;
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = pad.l + (i / (n - 1)) * cw;
    const y = pad.t + (trace[i].brake || 0) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function _renderInputsChart(traceA, traceB = null) {
  const canvas = document.getElementById('inputs-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const hasInputs = traceA.some(p => p.throttle !== undefined);
  if (!hasInputs) {
    ctx.fillStyle = 'rgba(255,255,255,0.18)'; ctx.font = '9px monospace';
    ctx.fillText('THROTTLE/BRAKE — restart app to collect input data', 32, h / 2 + 4);
    return;
  }

  const pad = { t: 2, b: 2, l: 28, r: 4 };
  const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;

  ctx.font = '8px monospace';
  ctx.fillStyle = 'rgba(0,214,143,0.8)'; ctx.fillText('THR', 0, pad.t + 9);
  ctx.fillStyle = 'rgba(225,6,0,0.8)';   ctx.fillText('BRK', 0, h - pad.b - 2);

  // B first (behind), then A on top
  if (traceB && traceB.length >= 2 && traceB.some(p => p.throttle !== undefined)) {
    _drawInputLines(ctx, traceB, pad, cw, ch,
      '#c07830', 'rgba(192,120,48,0.15)',
      '#c05000', 'rgba(192,80,0,0.12)');
  }
  _drawInputLines(ctx, traceA, pad, cw, ch,
    '#00d68f', 'rgba(0,214,143,0.25)',
    '#e10600', 'rgba(225,6,0,0.22)');
}

function _renderGForceChart(traceA, traceB = null) {
  return _renderGForceChartImpl(traceA, traceB);
}
function _renderGForceChartImpl(traceA, traceB) {
  const canvas = document.getElementById('gforce-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const cx = w / 2, cy = h / 2;
  const maxG = 3;
  const scale = Math.min(w, h) / 2 - 10;

  // Reference circles at 1G, 2G, 3G
  for (let g = 1; g <= 3; g++) {
    ctx.beginPath();
    ctx.arc(cx, cy, scale * g / maxG, 0, Math.PI * 2);
    ctx.strokeStyle = g === 3 ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.08)';
    ctx.lineWidth = g === 3 ? 1.5 : 1;
    ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.25)'; ctx.font = '8px monospace';
    ctx.fillText(`${g}G`, cx + scale * g / maxG + 2, cy - 2);
  }

  // Crosshairs
  ctx.strokeStyle = 'rgba(255,255,255,0.10)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx, 4); ctx.lineTo(cx, h - 4); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(4, cy); ctx.lineTo(w - 4, cy); ctx.stroke();

  // Axis labels
  ctx.fillStyle = 'rgba(255,255,255,0.25)'; ctx.font = '7px monospace';
  ctx.fillText('LAT', w - 20, cy - 3);
  ctx.fillText('LON', cx + 3, 10);

  const hasG = traceA.some(p => p.gLat !== undefined);
  if (!hasG) {
    ctx.fillStyle = 'rgba(255,255,255,0.20)'; ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('NO DATA', cx, cy + 4);
    ctx.textAlign = 'left';
    return;
  }

  // Trace B dots (orange, behind A)
  if (traceB && traceB.length >= 2) {
    for (const p of traceB) {
      if (p.gLat === undefined) continue;
      const px = cx + Math.max(-scale, Math.min(scale, (p.gLat / maxG) * scale));
      const py = cy - Math.max(-scale, Math.min(scale, (p.gLon / maxG) * scale));
      ctx.globalAlpha = 0.45;
      ctx.fillStyle = '#f7a44c';
      ctx.beginPath(); ctx.arc(px, py, 1.5, 0, Math.PI * 2); ctx.fill();
    }
  }

  // Trace A dots coloured by sector
  for (const p of traceA) {
    if (p.gLat === undefined) continue;
    const px = cx + Math.max(-scale, Math.min(scale, (p.gLat / maxG) * scale));
    const py = cy - Math.max(-scale, Math.min(scale, (p.gLon / maxG) * scale));
    ctx.globalAlpha = 0.55;
    ctx.fillStyle = _SECTOR_PALETTE[p.sector] || '#aaa';
    ctx.beginPath(); ctx.arc(px, py, 1.5, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Last point: bright white dot
  const last = traceA[traceA.length - 1];
  if (last && last.gLat !== undefined) {
    const px = cx + Math.max(-scale, Math.min(scale, (last.gLat / maxG) * scale));
    const py = cy - Math.max(-scale, Math.min(scale, (last.gLon / maxG) * scale));
    ctx.shadowBlur = 8; ctx.shadowColor = '#fff';
    ctx.fillStyle = '#ffffff';
    ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
  }
}

// ── Track Map ──────────────────────────────────────────────────────────────────
let _mapMode         = 'sector';
let _loadedSvg       = null;
let _reviewLap       = null;   // null = live mode; number = reviewing that lap
let _sessionId       = null;
let _lapCount        = 0;
let _reviewTotal     = 0;      // lap count locked when review was entered
let _lastGoodOutline = [];     // cached live outline so review renders always have a track shape

function _updateTrackSvg(svgName) {
  const img = document.getElementById('track-svg-img');
  if (!svgName) { img.style.display = 'none'; _loadedSvg = null; return; }
  if (svgName === _loadedSvg) return;
  _loadedSvg = svgName;
  img.src = `/api/track-svg/${svgName}`;
  img.style.display = 'block';
}
const _SECTOR_COLORS = ['#e10600', '#f7c948', '#9b59b6'];

function setMapMode(mode) {
  _mapMode = mode;
  document.getElementById('map-btn-sector').className = 'map-mode-btn' + (mode === 'sector' ? ' active' : '');
  document.getElementById('map-btn-speed').className  = 'map-mode-btn' + (mode === 'speed'  ? ' active' : '');
}

function _speedColor(t) {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.5) {
    const v = Math.round(t * 2 * 255);
    return `rgb(0,${v},${255 - v})`;
  }
  const v = Math.round((t - 0.5) * 2 * 255);
  return `rgb(${v},${Math.round((1 - (t - 0.5) * 2) * 200)},0)`;
}

function _bounds(pts) {
  if (!pts.length) return { minX: 0, maxX: 1, minZ: 0, maxZ: 1 };
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const p of pts) {
    if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
    if (p.z < minZ) minZ = p.z; if (p.z > maxZ) maxZ = p.z;
  }
  return { minX, maxX, minZ, maxZ };
}

function _toCanvas(p, b, cw, ch, pad) {
  const rng = Math.max(b.maxX - b.minX, b.maxZ - b.minZ, 1);
  const scale = (Math.min(cw, ch) - 2 * pad) / rng;
  const ox = pad + ((cw - 2 * pad) - (b.maxX - b.minX) * scale) / 2;
  const oz = pad + ((ch - 2 * pad) - (b.maxZ - b.minZ) * scale) / 2;
  return {
    x: ox + (p.x - b.minX) * scale,
    y: ch - oz - (p.z - b.minZ) * scale,
  };
}

function renderTrackMap(data) {
  const panel  = document.getElementById('track-map-panel');
  const canvas = document.getElementById('track-canvas');
  const outline = data.track_outline || [];
  const trace   = data.lap_trace    || [];

  if (outline.length < 10 && trace.length < 10) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';

  const ctx = canvas.getContext('2d');
  const cw = canvas.width, ch = canvas.height, pad = 14;
  ctx.clearRect(0, 0, cw, ch);

  const ref = outline.length >= trace.length ? outline : trace;
  const b   = _bounds(ref);

  // Track outline (dark reference)
  if (outline.length > 1) {
    ctx.strokeStyle = '#252530'; ctx.lineWidth = 10; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath();
    const s = _toCanvas(outline[0], b, cw, ch, pad);
    ctx.moveTo(s.x, s.y);
    for (const p of outline.slice(1)) { const c = _toCanvas(p, b, cw, ch, pad); ctx.lineTo(c.x, c.y); }
    ctx.stroke();
  }

  // Colored trace
  if (trace.length > 1) {
    const speeds = trace.map(p => p.speed);
    const minSpd = Math.min(...speeds), spdRng = Math.max(Math.max(...speeds) - minSpd, 1);
    for (let i = 1; i < trace.length; i++) {
      const c1 = _toCanvas(trace[i - 1], b, cw, ch, pad);
      const c2 = _toCanvas(trace[i],     b, cw, ch, pad);
      ctx.lineWidth = 3; ctx.lineCap = 'round';
      ctx.strokeStyle = _mapMode === 'sector'
        ? (_SECTOR_COLORS[trace[i].sector] || '#aaa')
        : _speedColor((trace[i].speed - minSpd) / spdRng);
      ctx.beginPath(); ctx.moveTo(c1.x, c1.y); ctx.lineTo(c2.x, c2.y); ctx.stroke();
    }
  }

  // Car position dot
  if (data.car_pos && ref.length > 0) {
    const pos = _toCanvas(data.car_pos, b, cw, ch, pad);
    ctx.shadowBlur = 10; ctx.shadowColor = '#fff';
    ctx.fillStyle = '#ffffff';
    ctx.beginPath(); ctx.arc(pos.x, pos.y, 5, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
  }
}

// ── Lap navigator ─────────────────────────────────────────────────────────────
function _updateLapNav() {
  const nav   = document.getElementById('lap-nav');
  const total = _reviewLap !== null ? _reviewTotal : _lapCount;
  if (total === 0) { nav.style.display = 'none'; return; }
  nav.style.display = 'flex';
  const liveBtn = document.getElementById('lap-nav-live');
  const label   = document.getElementById('lap-nav-label');
  if (_reviewLap === null) {
    label.textContent = 'LIVE';
    liveBtn.style.opacity = '0.3';
    liveBtn.style.pointerEvents = 'none';
  } else {
    label.textContent = `LAP ${_reviewLap} / ${_reviewTotal}`;
    liveBtn.style.opacity = '1';
    liveBtn.style.pointerEvents = 'auto';
  }
}

function lapNavStep(dir) {
  const total = _reviewLap !== null ? _reviewTotal : _lapCount;
  if (total === 0) return;
  if (_reviewLap === null) _reviewTotal = _lapCount;  // lock count when entering review
  const current = _reviewLap === null ? _reviewTotal + 1 : _reviewLap;
  const next = Math.max(1, Math.min(_reviewTotal, current + dir));
  if (next === current && _reviewLap !== null) return;
  _reviewLap = next;
  _updateLapNav();
  _loadReviewLap();
}

function lapNavLive() {
  _reviewLap   = null;
  _reviewTotal = 0;
  _updateLapNav();
}

async function _loadReviewLap() {
  if (_reviewLap === null || _sessionId === null) return;
  try {
    const r = await fetch(`/api/lap-trace/${_sessionId}/${_reviewLap}`);
    const d = await r.json();
    const trace = d.trace || [];
    renderTrackMap({ lap_trace: trace, track_outline: _lastGoodOutline, car_pos: null });
    if (!_comparisonActive()) renderTelemetry(trace);
  } catch(e) {}
}

async function fetchMotion() {
  try {
    const r = await fetch('/api/motion');
    const d = await r.json();
    // Cache outline for review mode (keep last good one even after race ends)
    if (d.track_outline && d.track_outline.length >= 10) _lastGoodOutline = d.track_outline;
    // Update lap count and session id from live state
    if (lastData) {
      const newCount = lastData.laps ? lastData.laps.length : 0;
      if (newCount !== _lapCount) {
        _lapCount = newCount;
        if (_reviewLap === null) _updateLapNav();  // don't disrupt review nav label
      }
      if (lastData.current_session_id && lastData.current_session_id !== _sessionId) {
        _sessionId = lastData.current_session_id;
        if (_reviewLap === null) {  // only reset when not actively reviewing a lap
          _lapCount    = 0;
          _reviewTotal = 0;
          _updateLapNav();
        }
      }
    }
    if (_reviewLap === null) {
      renderTrackMap(d);
      if (!_comparisonActive()) renderTelemetry(d.lap_trace || []);
    }
  } catch(e) {}
}

fetchState();
fetchPBs();
initLB();
initAI();
fetchSessions();
fetchMotion();
setInterval(fetchState, 1000);
setInterval(fetchPBs, 60000);
setInterval(fetchSessions, 30000);
setInterval(fetchLeaderboard, 60000);
setInterval(fetchMotion, 250);
</script>

<div id="toast-container"></div>
</body>
</html>"""

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
                payload = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        elif parsed.path == "/api/career":
            recent = db_get_recent_races()
            with state_lock:
                stats = dict(state["career_stats"])
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
                    "car_pos":       state["car_pos"],
                    "car_speed":     state["car_speed"],
                    "lap_trace":     _thin(trace),
                    "track_outline": _thin(outline),
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
                    "SELECT trace FROM laps WHERE session_id=? AND lap_num=?",
                    (session_id, lap_num)
                ).fetchone()
                con.close()
                trace_data = json.loads(row[0]) if row and row[0] else []
                payload = json.dumps({"trace": trace_data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)
            except Exception:
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
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("X-Content-Type-Options", "nosniff")
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
            except Exception as exc:
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

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", 5000), Handler)
    print("🌐  Dashboard → http://localhost:5000")
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
