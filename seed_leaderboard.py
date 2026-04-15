"""
seed_leaderboard.py — Post 5-minute placeholder times to the community leaderboard
for every track/session-type combo in your local personal_bests DB.

Usage:
    python seed_leaderboard.py

The placeholder driver is identified as "TestDriver" with player_id
"test_placeholder_seed". Because the leaderboard only saves a time if it is
FASTER than an existing entry for that player_id, running this twice is safe.
Real driver entries (with your actual player_id) will never be affected.

Set F1_LEADERBOARD_URL env var if you host your own instance, otherwise the
default shared Pitwall IQ backend is used.
"""

import json
import os
import sqlite3
import urllib.request as urllib
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────

LEADERBOARD_URL = os.environ.get(
    "F1_LEADERBOARD_URL",
    "https://f1tracker-func-6v3lqkyuhxwkc.azurewebsites.net",
).rstrip("/")
if LEADERBOARD_URL.endswith("/api"):
    LEADERBOARD_URL = LEADERBOARD_URL[:-4]

DB_PATH = os.path.join(os.path.dirname(__file__), "f1_laps.db")

PLACEHOLDER_PLAYER_ID   = "test_placeholder_seed"
PLACEHOLDER_DISPLAY     = "Test Driver"
PLACEHOLDER_LAP_MS      = 5 * 60 * 1000   # 5:00.000
PLACEHOLDER_LAP_TIME    = "5:00.000"
PLACEHOLDER_COMPOUND    = ""


def get_all_track_combos():
    """Return all unique (track, session_type) pairs from personal_bests."""
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT DISTINCT track, session_type FROM personal_bests ORDER BY track"
    ).fetchall()
    con.close()
    return rows


def submit_time(track: str, session_type: str) -> dict:
    payload = json.dumps({
        "player_id":    PLACEHOLDER_PLAYER_ID,
        "display_name": PLACEHOLDER_DISPLAY,
        "track":        track,
        "session_type": session_type,
        "lap_time_ms":  PLACEHOLDER_LAP_MS,
        "lap_time":     PLACEHOLDER_LAP_TIME,
        "compound":     PLACEHOLDER_COMPOUND,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }).encode()

    req = urllib.Request(
        f"{LEADERBOARD_URL}/api/lb-submit",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main():
    combos = get_all_track_combos()
    if not combos:
        print("No personal bests found in the DB — nothing to seed.")
        return

    print(f"Seeding {len(combos)} track/session combo(s) with a {PLACEHOLDER_LAP_TIME} placeholder…\n")
    for track, session_type in combos:
        result = submit_time(track, session_type)
        status = "ok" if result.get("ok") else f"FAILED: {result.get('error', '?')}"
        print(f"  {track:30s} | {session_type:15s} → {status}")

    print("\nDone. Community leaderboard entries with 5:00.000 placeholder times are now live.")
    print("Any real driver time will rank above these since 5 minutes is very slow.")


if __name__ == "__main__":
    main()
