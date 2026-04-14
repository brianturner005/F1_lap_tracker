#!/bin/bash
cd "$(dirname "$0")"

# Open the dashboard in the default browser after the server has had time to start
(sleep 2 && xdg-open "http://localhost:5000" 2>/dev/null) &

python3 F1_lap_tracker.py
