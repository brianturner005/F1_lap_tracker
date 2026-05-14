"""
iRacing telemetry source for Pitwall IQ.

Reads from iRacing's shared memory API and writes to the shared state dict
in the same format as the F1 UDP listener, so the dashboard works unchanged.

Requires pyirsdk on Windows:
    pip install pyirsdk

The app works without this file / without pyirsdk installed — F1 support is
unaffected. This module is imported lazily at startup and silently skipped if
pyirsdk is not available.
"""

import logging
import math
import threading
import time
from datetime import datetime

try:
    import irsdk
    IRACING_AVAILABLE = True
except ImportError:
    IRACING_AVAILABLE = False

log = logging.getLogger(__name__)

_SESSION_TYPE_MAP = {
    "offline testing": "Practice",
    "open practice":   "Practice",
    "lone qualifying": "Qualifying",
    "open qualifying": "Qualifying",
    "lone time trial": "Time Trial",
    "open time trial": "Time Trial",
    "warmup":          "Warm Up",
    "race":            "Race",
}

_SKIES_MAP = {0: "Clear", 1: "Partly Cloudy", 2: "Mostly Cloudy", 3: "Overcast"}

_TRACE_MIN_DIST = 3.0
_TRACE_MAX_PTS  = 4000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sec_to_laptime(s: float) -> str:
    if s is None or s <= 0:
        return "–:–.—"
    ms = int(round(s * 1000))
    m   = ms // 60000
    sec = (ms % 60000) // 1000
    mil = ms % 1000
    return f"{m}:{sec:02d}.{mil:03d}"


def _ms_to_laptime(ms: int) -> str:
    return _sec_to_laptime(ms / 1000.0) if ms else "–:–.—"


def _delta_str(ms: int, best_ms: int) -> str:
    if ms is None or best_ms is None:
        return ""
    diff = ms - best_ms
    if diff == 0:
        return "BEST"
    sign = "+" if diff > 0 else "-"
    return f"{sign}{abs(diff) / 1000.0:.3f}s"


def _safe(ir, key, default=None):
    """Safely read an irsdk variable, returning *default* on any error."""
    try:
        val = ir[key]
        return val if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# IRacingSource
# ---------------------------------------------------------------------------

class IRacingSource:
    """Polls iRacing shared memory at 30 Hz and updates the Pitwall IQ state."""

    POLL_INTERVAL = 1.0 / 30  # seconds

    def __init__(self, state, state_lock, callbacks):
        """
        *callbacks* must contain callable values for these keys:
          db_create_session, db_close_session, db_save_lap,
          db_get_track_pb, db_upsert_track_pb, lb_post
        """
        self._state = state
        self._lock  = state_lock
        self._cb    = callbacks
        self._ir    = None

        # Session state
        self._session_id  = None
        self._session_key = None   # (track, session_type) — detect track/type changes

        # Lap state
        self._last_lap_time = None  # last seen LapLastLapTime value (seconds)
        self._lap_num       = 0
        self._lap_trace     = []

        # Sector tracking
        self._sector_boundaries = [0.333, 0.666]  # [end-of-S1-pct, end-of-S2-pct]
        self._in_sector    = 0      # 0, 1, or 2
        self._s1_end_time  = None   # LapCurrentLapTime (s) when S1 ended
        self._s2_end_time  = None   # LapCurrentLapTime (s) when S2 ended
        self._last_dist    = None   # last LapDistPct, used for wrap detection

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self):
        self._ir = irsdk.IRSDK()
        was_connected = False

        while True:
            try:
                # startup() return value is unreliable across pyirsdk versions
                # (returns None in 2.x, bool in 1.x). Call it when not yet
                # initialized, then check is_connected independently.
                if not self._ir.is_initialized:
                    self._ir.startup()

                connected = bool(self._ir.is_connected)

                if not connected:
                    if was_connected:
                        self._on_disconnect()
                        was_connected = False
                    time.sleep(2.0)
                    continue

                if not was_connected:
                    self._on_connect()
                    was_connected = True

                self._ir.freeze_var_buffer_latest()
                self._process_frame()

            except Exception as exc:
                log.warning("iRacing source error: %s", exc)
                time.sleep(1.0)
                continue

            time.sleep(self.POLL_INTERVAL)

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def _on_connect(self):
        log.info("iRacing connected")
        self._load_sector_boundaries()
        with self._lock:
            self._state["iracing_connected"] = True
            # Only take over from F1 if F1 is not actively connected
            if not self._state.get("udp_connected"):
                self._state["sim"] = "iRacing"
                self._state["udp_connected"] = True

    def _on_disconnect(self):
        log.info("iRacing disconnected")
        if self._session_id is not None:
            self._cb["db_close_session"](self._session_id)
            self._session_id  = None
            self._session_key = None
        with self._lock:
            self._state["iracing_connected"] = False
            if self._state.get("sim") == "iRacing":
                self._state["udp_connected"] = False

    # ── Sector boundary loading ───────────────────────────────────────────────

    def _load_sector_boundaries(self):
        """Parse sector boundary percentages from iRacing session YAML."""
        try:
            sectors = (self._ir["WeekendInfo"] or {}).get("TrackSectors", [])
            pcts = []
            for s in sectors:
                try:
                    pct = float(s.get("SectorStartPct", 0))
                    if pct > 0:
                        pcts.append(pct)
                except (TypeError, ValueError):
                    pass
            pcts.sort()
            if len(pcts) >= 2:
                self._sector_boundaries = pcts[:2]
            elif len(pcts) == 1:
                # Only one interior boundary found — split the remaining third evenly
                self._sector_boundaries = [pcts[0], pcts[0] + (1.0 - pcts[0]) / 2]
            # else keep the default [0.333, 0.666]
        except Exception as exc:
            log.debug("Could not load sector boundaries: %s", exc)

    # ── Per-frame processing ──────────────────────────────────────────────────

    def _process_frame(self):
        ir = self._ir

        # Skip when player is not on track
        if not _safe(ir, "IsOnTrack", False) or _safe(ir, "IsInGarage", True):
            return

        # ── Session info ──────────────────────────────────────────────────────
        # Track name lives in the WeekendInfo YAML block, not as a telemetry var.
        try:
            wi = ir["WeekendInfo"] or {}
            track = str(
                wi.get("TrackDisplayName") or wi.get("TrackName") or "Unknown"
            ).strip() or "Unknown"
        except Exception:
            track = "Unknown"

        session_num = int(_safe(ir, "SessionNum", 0) or 0)
        try:
            sessions  = ir["SessionInfo"]["Sessions"]
            raw_type  = (sessions[session_num].get("SessionType") or "").lower().strip()
            session_type = _SESSION_TYPE_MAP.get(raw_type, raw_type.title() or "Practice")
        except Exception:
            session_type = "Practice"

        skies   = int(_safe(ir, "Skies", 0) or 0)
        weather = _SKIES_MAP.get(skies, "Clear")

        # ── DB session lifecycle ──────────────────────────────────────────────
        session_key = (track, session_type)
        if self._session_key != session_key:
            if self._session_id is not None:
                self._cb["db_close_session"](self._session_id)
            started_at = datetime.now().isoformat()
            self._session_id = self._cb["db_create_session"](
                track, session_type, weather, started_at, sim="iRacing"
            )
            self._session_key = session_key
            self._last_lap_time = None
            self._lap_num = 0

            pb = self._cb["db_get_track_pb"](track, session_type, sim="iRacing")
            with self._lock:
                if self._state.get("sim") == "iRacing":
                    self._state["track_pb_ms"]       = pb["lap_time_ms"] if pb else None
                    self._state["track_pb_time"]      = pb["lap_time"]    if pb else None
                    self._state["track_pb_compound"]  = pb.get("compound", "") if pb else None
                    self._state["session"]["track"]        = track
                    self._state["session"]["session_type"] = session_type
                    self._state["session"]["weather"]      = weather
                    self._state["session"]["started_at"]   = started_at
                    self._state["current_session_id"] = self._session_id
                    self._state["laps"]         = []
                    self._state["best_lap_ms"]  = None
                    self._state["best_lap_num"] = None

        # ── Live telemetry ────────────────────────────────────────────────────
        speed_kmh = int((_safe(ir, "Speed", 0.0) or 0.0) * 3.6)
        throttle  = float(_safe(ir, "Throttle", 0.0) or 0.0)
        brake     = float(_safe(ir, "Brake",    0.0) or 0.0)
        gear      = int(_safe(ir, "Gear", 0) or 0)
        rpm_val   = float(_safe(ir, "RPM", 0.0) or 0.0)

        # Steering: iRacing gives radians; normalise to -1.0 … +1.0
        steer_rad = float(_safe(ir, "SteeringWheelAngle", 0.0) or 0.0)
        steer_max = float(_safe(ir, "SteeringWheelAngleMax", 1.5708) or 1.5708)
        steer = round(max(-1.0, min(1.0, steer_rad / steer_max if steer_max else steer_rad)), 3)

        # G-forces: iRacing gives m/s², convert to G
        lat_g = round(float(_safe(ir, "LatAccel", 0.0) or 0.0) / 9.81, 3)
        lon_g = round(float(_safe(ir, "LonAccel", 0.0) or 0.0) / 9.81, 3)

        # Rev lights: derive 0-100% from shift RPM band
        sl_first = float(_safe(ir, "PlayerCarSLFirstRPM", 0.0) or 0.0)
        sl_last  = float(_safe(ir, "PlayerCarSLLastRPM",  0.0) or 0.0)
        if sl_last > sl_first > 0:
            rev_pct = int(max(0, min(100, (rpm_val - sl_first) / (sl_last - sl_first) * 100)))
        else:
            rev_pct = 0

        # Position / lap counters
        player_idx = int(_safe(ir, "PlayerCarIdx", 0) or 0)
        positions  = _safe(ir, "CarIdxPosition", None)
        position   = int(positions[player_idx]) if (positions and player_idx < len(positions)) else 0
        total_laps = int(_safe(ir, "SessionLapsTotal", 0) or 0)
        if total_laps >= 32767:
            total_laps = 0  # iRacing uses 32767 for "unlimited"
        current_lap = int(_safe(ir, "Lap", 1) or 1)

        # Tyre wear: iRacing gives *remaining* fraction (1.0 = new); convert to used %
        # Map to [RL, RR, FL, FR] to match F1 layout
        tw_lf = float(_safe(ir, "TireWearLF", 1.0) or 1.0)
        tw_rf = float(_safe(ir, "TireWearRF", 1.0) or 1.0)
        tw_lr = float(_safe(ir, "TireWearLR", 1.0) or 1.0)
        tw_rr = float(_safe(ir, "TireWearRR", 1.0) or 1.0)
        tyre_wear = [
            round((1.0 - tw_lr) * 100),
            round((1.0 - tw_rr) * 100),
            round((1.0 - tw_lf) * 100),
            round((1.0 - tw_rf) * 100),
        ]

        fuel = round(float(_safe(ir, "FuelLevel", 0.0) or 0.0), 2)

        # Sector tracking and trace updates
        dist_pct      = float(_safe(ir, "LapDistPct", 0.0) or 0.0)
        cur_lap_time  = float(_safe(ir, "LapCurrentLapTime", 0.0) or 0.0)
        current_sector = self._update_sectors(dist_pct, cur_lap_time)

        # World position for track map — iRacing SDK does not expose CarIdxWorldPos*
        # so we always fall back to a synthetic circular layout from LapDistPct.
        # Real coords would need to be integrated from velocity; the circle gives the
        # dashboard enough x/z data to drive the telemetry charts correctly.
        _R = 500.0
        angle = dist_pct * 2 * math.pi
        car_pos = {
            "x": round(math.cos(angle) * _R, 1),
            "z": round(math.sin(angle) * _R, 1),
        }

        trace = self._lap_trace
        if len(trace) < _TRACE_MAX_PTS:
            prev = trace[-1] if trace else None
            dist_moved = (abs(car_pos["x"] - prev["x"]) + abs(car_pos["z"] - prev["z"])) if prev else _TRACE_MIN_DIST
            if dist_moved >= _TRACE_MIN_DIST:
                trace.append({
                    "x": car_pos["x"], "z": car_pos["z"],
                    "speed": speed_kmh, "sector": current_sector,
                    "throttle": round(throttle, 3), "brake": round(brake, 3),
                    "steer": steer, "gear": gear, "rpm": int(rpm_val),
                    "gLat": lat_g, "gLon": lon_g,
                })

        # Lap completion detection
        last_lap_s = float(_safe(ir, "LapLastLapTime", -1.0) or -1.0)
        if last_lap_s > 0 and last_lap_s != self._last_lap_time:
            self._on_lap_complete(last_lap_s, track, session_type)
            self._last_lap_time = last_lap_s

        # ── Write shared state ────────────────────────────────────────────────
        with self._lock:
            if self._state.get("sim") != "iRacing":
                return  # F1 took over — don't overwrite
            self._state["udp_connected"]  = True
            self._state["car_speed"]      = speed_kmh
            self._state["car_throttle"]   = round(throttle, 3)
            self._state["car_brake"]      = round(brake, 3)
            self._state["car_steer"]      = steer
            self._state["car_gear"]       = gear
            self._state["car_rpm"]        = int(rpm_val)
            self._state["rev_lights_pct"] = rev_pct
            self._state["g_lat"]          = lat_g
            self._state["g_lon"]          = lon_g
            self._state["player_position"] = position
            self._state["total_laps"]     = total_laps
            self._state["current_lap"]    = current_lap
            self._state["tyre_wear"]      = tyre_wear
            self._state["fuel_in_tank"]   = fuel
            self._state["current_sector"] = current_sector
            self._state["session"]["weather"] = weather
            if car_pos:
                self._state["car_pos"] = car_pos
            self._state["lap_trace"] = list(self._lap_trace)

    # ── Sector tracking ───────────────────────────────────────────────────────

    def _update_sectors(self, dist_pct: float, cur_lap_time: float) -> int:
        """
        Track sector crossings via LapDistPct.
        Returns the current sector index (0=S1, 1=S2, 2=S3).
        """
        b1, b2 = self._sector_boundaries

        # Detect lap wrap (dist_pct resets from ~1.0 back to ~0.0)
        if self._last_dist is not None and dist_pct < 0.1 and self._last_dist > 0.9:
            self._in_sector   = 0
            self._s1_end_time = None
            self._s2_end_time = None
            self._lap_trace   = []

        if self._in_sector == 0 and dist_pct >= b1:
            self._s1_end_time = cur_lap_time
            self._in_sector   = 1
        elif self._in_sector == 1 and dist_pct >= b2:
            self._s2_end_time = cur_lap_time
            self._in_sector   = 2

        self._last_dist = dist_pct
        return self._in_sector

    # ── Lap completion ────────────────────────────────────────────────────────

    def _on_lap_complete(self, lap_secs: float, track: str, session_type: str):
        lap_ms = int(round(lap_secs * 1000))
        if not (30_000 <= lap_ms <= 600_000):
            return  # sanity check — ignore implausible times

        self._lap_num += 1
        lap_time_str = _sec_to_laptime(lap_secs)
        timestamp    = datetime.now().isoformat()

        # Derive sector times from recorded crossing timestamps
        s1_ms = int(round(self._s1_end_time * 1000))  if self._s1_end_time else None
        s2_ms = int(round((self._s2_end_time - self._s1_end_time) * 1000)) \
                if (self._s2_end_time and self._s1_end_time) else None
        s3_ms = int(round((lap_secs - self._s2_end_time) * 1000)) \
                if self._s2_end_time else None

        saved_trace = list(self._lap_trace)

        # Snapshot state values we need outside the lock
        with self._lock:
            best_ms      = self._state.get("best_lap_ms")
            track_pb_ms  = self._state.get("track_pb_ms")
            opt_in       = self._state.get("leaderboard_opt_in", False)
            player_id    = self._state.get("player_id", "")
            display_name = self._state.get("display_name", "Anonymous")

        is_best     = best_ms is None or lap_ms < best_ms
        is_track_pb = track_pb_ms is None or lap_ms < track_pb_ms

        # Update session best
        if is_best:
            with self._lock:
                self._state["best_lap_ms"]  = lap_ms
                self._state["best_lap_num"] = self._lap_num

        ref_ms = best_ms if (best_ms and not is_best) else lap_ms
        delta  = "PB!" if is_track_pb else _delta_str(lap_ms, ref_ms)

        lap_record = {
            "lap_num":     self._lap_num,
            "lap_time_ms": lap_ms,
            "lap_time":    lap_time_str,
            "s1_ms":  s1_ms, "s1": _ms_to_laptime(s1_ms) if s1_ms else None,
            "s2_ms":  s2_ms, "s2": _ms_to_laptime(s2_ms) if s2_ms else None,
            "s3_ms":  s3_ms, "s3": _ms_to_laptime(s3_ms) if s3_ms else None,
            "invalid":     False,
            "compound":    "",
            "timestamp":   timestamp,
            "is_track_pb": is_track_pb,
            "is_best":     is_best,
            "delta":       delta,
            "telem":       {},
        }

        # Persist to DB
        if self._session_id is not None:
            self._cb["db_save_lap"](self._session_id, lap_record, trace=saved_trace or None)

        # Update track PB
        if is_track_pb:
            self._cb["db_upsert_track_pb"](
                track, session_type, lap_ms, lap_time_str, "",
                self._session_id, timestamp, sim="iRacing",
            )
            with self._lock:
                self._state["track_pb_ms"]      = lap_ms
                self._state["track_pb_time"]     = lap_time_str
                self._state["track_pb_compound"] = ""
                self._state["track_outline"]     = saved_trace

            if opt_in and player_id:
                self._cb["lb_post"]({
                    "player_id":    player_id,
                    "display_name": display_name,
                    "track":        track,
                    "session_type": session_type,
                    "lap_time_ms":  lap_ms,
                    "lap_time":     lap_time_str,
                    "compound":     "",
                    "submitted_at": timestamp,
                    "sim":          "iRacing",
                })

        # Append to live laps list
        with self._lock:
            if self._state.get("sim") == "iRacing":
                self._state["laps"].append(lap_record)
                self._state["track_outline"] = saved_trace
                self._state["last_sector"]   = [s1_ms, s2_ms, s3_ms]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_iracing_source(state, state_lock, callbacks):
    """
    Start the iRacing telemetry source thread.

    Returns True if pyirsdk is available and the thread was started.
    Returns False if pyirsdk is not installed (F1 support is unaffected).
    """
    if not IRACING_AVAILABLE:
        return False
    IRacingSource(state, state_lock, callbacks).start()
    return True
