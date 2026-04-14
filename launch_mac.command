#!/bin/bash
cd "$(dirname "$0")"

# Open the dashboard in the default browser after the server has had time to start
(sleep 2 && open "http://localhost:5000") &

python3 F1_lap_tracker.py
