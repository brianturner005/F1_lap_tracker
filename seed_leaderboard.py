"""
seed_leaderboard.py — Submit your local personal bests to the community leaderboard.

Useful if you set times before the leaderboard feature was configured, or if you
want to re-sync your historical bests after a fresh install.

Usage:
    python seed_leaderboard.py

The leaderboard only updates an entry if the submitted time is FASTER than the
existing one, so running this multiple times is safe.

Set F1_LEADERBOARD_URL env var if you host your own instance.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from urllib.request import urlopen, Request as URLRequest

# ── Config ────────────────────────────────────────────────────────────────────

LEADERBOARD_URL = os.environ.get(
    "F1_LEADERBOARD_URL",
    "https://f1tracker-func-6v3lqkyuhxwkc.azurewebsites.net",
).rstrip("/")
if LEADERBOARD_URL.endswith("/api"):
    LEADERBOARD_URL = LEADERBOARD_URL[:-4]

DB_PATH = os.path.join(os.path.dirname(__file__), "f1_laps.db")


def get_config():
    """Read player_id and display_name from the app's config table."""
    con = sqlite3.connect(DB_PATH)
    def _get(key, default):
        row = con.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    player_id    = _get("player_id", None)
    display_name = _get("display_name", "Anonymous")
    con.close()
    return player_id, display_name


def get_all_pbs():
    """Return all personal bests from the DB."""
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT track, session_type, lap_time_ms, lap_time, compound "
        "FROM personal_bests ORDER BY track, session_type"
    ).fetchall()
    con.close()
    return rows


def submit_time(player_id, display_name, track, session_type,
                lap_time_ms, lap_time, compound) -> dict:
    payload = json.dumps({
        "player_id":    player_id,
        "display_name": display_name,
        "track":        track,
        "session_type": session_type,
        "lap_time_ms":  int(lap_time_ms),
        "lap_time":     lap_time,
        "compound":     compound or "",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }).encode()

    req = URLRequest(
        f"{LEADERBOARD_URL}/api/lb-submit",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main():
    player_id, display_name = get_config()
    if not player_id:
        print("No player_id found — start the app at least once first.")
        return

    pbs = get_all_pbs()
    if not pbs:
        print("No personal bests found in the DB — nothing to submit.")
        return

    print(f"Submitting {len(pbs)} personal best(s) as '{display_name}'...\n")
    for track, session_type, lap_time_ms, lap_time, compound in pbs:
        result = submit_time(player_id, display_name, track, session_type,
                             lap_time_ms, lap_time, compound)
        if result.get("ok"):
            rank = result.get("rank", "?")
            updated = result.get("updated", False)
            note = f"rank #{rank}" + (" — new best!" if updated else " (no improvement)")
        else:
            note = f"FAILED: {result.get('error', '?')}"
        print(f"  {track:30s} | {session_type:15s} | {lap_time:12s} → {note}")

    print("\nDone.")


if __name__ == "__main__":
    main()
