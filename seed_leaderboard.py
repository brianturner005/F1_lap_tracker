"""
seed_leaderboard.py — Submit all your personal bests to the community leaderboard.

Requires the F1 Lap Tracker app to be running (it handles the Azure connection).

Usage:
    python seed_leaderboard.py [port]

    port  Optional. Default is 8080.
"""

import json
import sys
from urllib.request import urlopen, Request as URLRequest

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
BASE = f"http://localhost:{PORT}"


def main():
    print(f"Connecting to F1 Lap Tracker at {BASE}…")
    req = URLRequest(f"{BASE}/api/lb-seed", data=b"", method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        print(f"Error: {exc}")
        print("Make sure the F1 Lap Tracker app is running before seeding.")
        return

    if result.get("ok"):
        print(f"Done — submitted {result['submitted']} personal best(s) to the community leaderboard.")
    else:
        print(f"Server returned an error: {result}")


if __name__ == "__main__":
    main()
