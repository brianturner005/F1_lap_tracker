# #!/usr/bin/env python3
“””
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
“””

import struct
import socket
import threading
import json
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

# ── Shared state ─────────────────────────────────────────────────────────────

state_lock = threading.Lock()
state = {
“session”: {
“track”: “Unknown”,
“session_type”: “Unknown”,
“weather”: “Unknown”,
“started_at”: None,
},
“current_lap”: 1,
“best_lap_ms”: None,
“best_lap_num”: None,
“laps”: [],          # list of lap dicts
“last_sector”: [None, None, None],  # current lap sector times ms
“session_history”: [],   # past sessions
“udp_connected”: False,
“player_position”: 0,
“total_laps”: 0,
}

TRACK_IDS = {
0:“Melbourne”, 1:“Paul Ricard”, 2:“Shanghai”, 3:“Sakhir (Bahrain)”,
4:“Catalunya”, 5:“Monaco”, 6:“Montreal”, 7:“Silverstone”, 8:“Hockenheim”,
9:“Hungaroring”, 10:“Spa”, 11:“Monza”, 12:“Singapore”, 13:“Suzuka”,
14:“Abu Dhabi”, 15:“Texas (COTA)”, 16:“Brazil”, 17:“Austria”,
18:“Sochi”, 19:“Mexico”, 20:“Baku (Azerbaijan)”, 21:“Sakhir Short”,
22:“Silverstone Short”, 23:“Texas Short”, 24:“Suzuka Short”,
25:“Hanoi”, 26:“Zandvoort”, 27:“Imola”, 28:“Portimão”, 29:“Jeddah”,
30:“Miami”, 31:“Las Vegas”, 32:“Lusail (Qatar)”, 33:“Interlagos Short”
}

SESSION_TYPES = {
0:“Unknown”, 1:“Practice 1”, 2:“Practice 2”, 3:“Practice 3”,
4:“Short Practice”, 5:“Qualifying 1”, 6:“Qualifying 2”, 7:“Qualifying 3”,
8:“Short Qualifying”, 9:“OSQ”, 10:“Race”, 11:“Race 2”,
12:“Race 3”, 13:“Time Trial”
}

WEATHER_IDS = {0:“Clear”, 1:“Light Cloud”, 2:“Overcast”, 3:“Light Rain”,
4:“Heavy Rain”, 5:“Storm”}

def ms_to_laptime(ms):
if ms is None or ms <= 0:
return “–:–.—”
total_sec = ms / 1000.0
minutes = int(total_sec // 60)
seconds = int(total_sec % 60)
millis = int(ms % 1000)
return f”{minutes}:{seconds:02d}.{millis:03d}”

def delta_str(ms, best_ms):
if ms is None or best_ms is None:
return “”
diff = ms - best_ms
if diff == 0:
return “BEST”
sign = “+” if diff > 0 else “-”
diff = abs(diff) / 1000.0
return f”{sign}{diff:.3f}s”

# ── UDP Packet Parsing (F1 2023/2024 format) ──────────────────────────────────

HEADER_FORMAT = “<HBBBBBQfIIBB”
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def parse_header(data):
if len(data) < HEADER_SIZE:
return None
vals = struct.unpack_from(HEADER_FORMAT, data, 0)
return {
“packet_format”: vals[0],
“game_year”: vals[1],
“game_major”: vals[2],
“game_minor”: vals[3],
“packet_version”: vals[4],
“packet_id”: vals[5],
“session_uid”: vals[6],
“session_time”: vals[7],
“frame_id”: vals[8],
“overall_frame_id”: vals[9],
“player_car_index”: vals[10],
“secondary_player_car_index”: vals[11],
}

# Packet ID 1 – Session Data

def parse_session_packet(data, player_idx):
try:
offset = HEADER_SIZE
# weather, trackTemperature, airTemperature, totalLaps, trackLength
weather = struct.unpack_from(”<B”, data, offset)[0]
offset += 3  # skip track/air temp
total_laps = struct.unpack_from(”<B”, data, offset)[0]
offset += 3  # skip trackLength (uint16) + safetyCarStatus
offset += 1  # skip networkGame
offset += 1  # skip numWeatherForecastSamples
# skip forecasts (56 bytes each * count) — we’ll just seek to trackId
# trackId is at offset HEADER_SIZE + 5 (after weather=1,trackTemp=1,airTemp=1,totalLaps=1,trackLength=2) = +6… let’s use known offsets
# F1 2023 packet layout: weather(1) trackTemp(1) airTemp(1) totalLaps(1) trackLength(2) safetyCarStatus(1) networkGame(1) numWeatherForecastSamples(1) weatherForecastSamples(56*numSamples) sessionType(1) …trackId
# Easier: use fixed known offsets from packet start (HEADER_SIZE)
base = HEADER_SIZE
weather_val = struct.unpack_from(”<B”, data, base)[0]
total_laps_val = struct.unpack_from(”<B”, data, base + 3)[0]
# numWeatherForecastSamples at base+8
num_forecasts = struct.unpack_from(”<B”, data, base + 8)[0]
after_forecasts = base + 9 + (56 * num_forecasts)
session_type = struct.unpack_from(”<B”, data, after_forecasts)[0]
track_id = struct.unpack_from(”<b”, data, after_forecasts + 1)[0]  # signed

```
    with state_lock:
        state["session"]["weather"] = WEATHER_IDS.get(weather_val, "Unknown")
        state["session"]["session_type"] = SESSION_TYPES.get(session_type, "Unknown")
        state["session"]["track"] = TRACK_IDS.get(track_id, f"Track {track_id}")
        state["total_laps"] = total_laps_val
        state["udp_connected"] = True
        if state["session"]["started_at"] is None:
            state["session"]["started_at"] = datetime.now().isoformat()
except Exception:
    pass
```

# Packet ID 2 – Lap Data

LAP_DATA_SIZE = 53  # F1 2023 per-car lap data size

def parse_lap_data_packet(data, player_idx):
try:
base = HEADER_SIZE + (player_idx * LAP_DATA_SIZE)
if len(data) < base + LAP_DATA_SIZE:
return
# lastLapTimeInMS(4) currentLapTimeInMS(4) sector1TimeInMS(2) sector1TimeMinutes(1)
# sector2TimeInMS(2) sector2TimeMinutes(1) deltaToCarInFrontInMS(4) deltaToBestLapInMS(4)
# lapDistance(4) totalDistance(4) safetyCarDelta(4) carPosition(1) currentLapNum(1)
# pitStatus(1) numPitStops(1) sector(1) currentLapInvalid(1) penalties(1) …
(last_lap_ms, cur_lap_ms,
s1_ms, s1_min,
s2_ms, s2_min) = struct.unpack_from(”<IIHBHb”, data, base)

```
    cur_lap_num = struct.unpack_from("<B", data, base + 23)[0]
    sector = struct.unpack_from("<B", data, base + 25)[0]  # 0=s1,1=s2,2=s3
    invalid = struct.unpack_from("<B", data, base + 26)[0]
    position = struct.unpack_from("<B", data, base + 22)[0]

    s1_total_ms = s1_min * 60000 + s1_ms if s1_min >= 0 else s1_ms
    s2_total_ms = s2_min * 60000 + s2_ms if s2_min >= 0 else s2_ms

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
            }
            lap_record["s1"] = ms_to_laptime(lap_record["s1_ms"])
            lap_record["s2"] = ms_to_laptime(lap_record["s2_ms"])
            lap_record["s3"] = ms_to_laptime(lap_record["s3_ms"])

            state["laps"].append(lap_record)

            # Update best lap (valid laps only)
            if not invalid and last_lap_ms > 10000:
                if state["best_lap_ms"] is None or last_lap_ms < state["best_lap_ms"]:
                    state["best_lap_ms"] = last_lap_ms
                    state["best_lap_num"] = prev_lap

        # Annotate all laps with delta
        for lap in state["laps"]:
            lap["delta"] = delta_str(lap["lap_time_ms"], state["best_lap_ms"])
            lap["is_best"] = lap["lap_num"] == state["best_lap_num"]
except Exception:
    pass
```

def udp_listener():
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((“0.0.0.0”, 20777))
sock.settimeout(2.0)
print(“🎮  UDP listener active on port 20777”)
while True:
try:
data, _ = sock.recvfrom(4096)
header = parse_header(data)
if not header:
continue
pid = header[“packet_id”]
pidx = header[“player_car_index”]
if pid == 1:
parse_session_packet(data, pidx)
elif pid == 2:
parse_lap_data_packet(data, pidx)
except socket.timeout:
pass
except Exception:
pass

# ── HTTP Server (dashboard) ───────────────────────────────────────────────────

HTML = r”””<!DOCTYPE html>

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
    --bg: #0a0a0a;
    --panel: #111114;
    --border: #222228;
    --text: #e8e8e8;
    --muted: #666;
    --gold: #ffd700;
    --green: #00d68f;
    --purple: #c77dff;
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
content: ‘’;
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
border-bottom: 2px solid var(–red);
background: linear-gradient(90deg, #0d0000 0%, var(–panel) 40%);
}
.logo {
font-family: ‘Orbitron’, sans-serif;
font-weight: 900;
font-size: 1.4rem;
letter-spacing: .15em;
color: var(–red);
text-shadow: 0 0 20px rgba(225,6,0,.4);
}
.logo span { color: #fff; }
.status-dot {
width: 10px; height: 10px; border-radius: 50%;
background: var(–muted);
display: inline-block; margin-right: 8px;
transition: background .3s;
}
.status-dot.live { background: var(–green); box-shadow: 0 0 8px var(–green); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.status-text { font-size: .75rem; color: var(–muted); }
.status-text.live { color: var(–green); }

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
background: var(–panel);
border: 1px solid var(–border);
border-radius: 4px;
padding: 16px;
position: relative;
overflow: hidden;
}
.panel::before {
content: ‘’;
position: absolute; top: 0; left: 0; right: 0; height: 2px;
background: var(–red);
}
.panel-title {
font-family: ‘Orbitron’, sans-serif;
font-size: .6rem;
letter-spacing: .2em;
color: var(–muted);
text-transform: uppercase;
margin-bottom: 12px;
}

/* BIG NUMBER panels */
.big-num {
font-family: ‘Orbitron’, sans-serif;
font-size: 2.4rem;
font-weight: 700;
color: var(–text);
line-height: 1;
margin-bottom: 4px;
}
.big-num.gold { color: var(–gold); text-shadow: 0 0 20px rgba(255,215,0,.3); }
.big-num.red { color: var(–red); }
.sub-label { font-size: .7rem; color: var(–muted); }

/* Sector strips */
.sectors {
display: grid;
grid-template-columns: 1fr 1fr 1fr;
gap: 8px;
}
.sector {
background: #0d0d10;
border: 1px solid var(–border);
border-radius: 3px;
padding: 10px 8px;
text-align: center;
}
.sector-label { font-size: .6rem; color: var(–muted); margin-bottom: 4px; letter-spacing: .15em; }
.sector-time { font-family: ‘Orbitron’, sans-serif; font-size: .95rem; color: var(–text); }
.sector-time.purple { color: var(–purple); }

/* Session info */
.info-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #1a1a1e; font-size: .8rem; }
.info-row:last-child { border-bottom: none; }
.info-key { color: var(–muted); }
.info-val { color: var(–text); text-align: right; }

/* Lap table */
.lap-table-wrap { overflow-y: auto; max-height: 340px; }
table { width: 100%; border-collapse: collapse; font-size: .78rem; }
thead th {
font-family: ‘Orbitron’, sans-serif;
font-size: .55rem;
letter-spacing: .15em;
color: var(–muted);
text-align: left;
padding: 6px 8px;
border-bottom: 1px solid var(–border);
position: sticky; top: 0;
background: var(–panel);
}
tbody tr { border-bottom: 1px solid #181820; transition: background .15s; }
tbody tr:hover { background: #1a1a22; }
tbody tr.best-lap { background: rgba(255,215,0,.06); }
tbody tr.invalid { opacity: .4; }
td { padding: 7px 8px; }
td.lap-num { color: var(–muted); font-size: .7rem; }
td.lap-time { font-family: ‘Orbitron’, sans-serif; font-size: .85rem; color: var(–text); }
td.lap-time.best { color: var(–gold); }
td.delta { font-size: .75rem; }
td.delta.positive { color: #ff6b6b; }
td.delta.best-text { color: var(–gold); font-weight: bold; }
td.sector { color: #9999bb; font-size: .72rem; }
.invalid-pill {
background: rgba(225,6,0,.2);
color: var(–red);
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
color: var(–muted);
}
.waiting .big-icon { font-size: 2.5rem; margin-bottom: 12px; }
.waiting p { font-size: .8rem; line-height: 1.8; }
.waiting code { color: var(–red); background: #1a0000; padding: 1px 5px; border-radius: 2px; }

/* Clear session button */
.btn {
background: transparent;
border: 1px solid var(–border);
color: var(–muted);
font-family: ‘Share Tech Mono’, monospace;
font-size: .7rem;
padding: 5px 12px;
cursor: pointer;
border-radius: 3px;
letter-spacing: .08em;
transition: all .2s;
}
.btn:hover { border-color: var(–red); color: var(–red); }
.btn-danger:hover { background: rgba(225,6,0,.1); }

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

<script>
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
}

function fmt(v) { return v || '--:--.---'; }

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
  const p3 = `<div class="panel">
    <div class="panel-title">Session</div>
    <div class="info-row"><span class="info-key">TRACK</span><span class="info-val">${d.session.track}</span></div>
    <div class="info-row"><span class="info-key">TYPE</span><span class="info-val">${d.session.session_type}</span></div>
    <div class="info-row"><span class="info-key">WEATHER</span><span class="info-val">${d.session.weather}</span></div>
    <div class="info-row"><span class="info-key">POSITION</span><span class="info-val">${d.player_position > 0 ? 'P' + d.player_position : '—'}</span></div>
  </div>`;

  // Lap table
  let rows = '';
  if (d.laps.length === 0) {
    rows = `<tr><td colspan="6" class="waiting"><div class="big-icon">🏎</div>
      <p>No laps recorded yet.<br>
      Make sure UDP telemetry is <code>ON</code> in F1 25 settings<br>
      IP: <code>127.0.0.1</code> &nbsp; Port: <code>20777</code></p></td></tr>`;
  } else {
    const reversed = [...d.laps].reverse();
    for (const lap of reversed) {
      const isBest = lap.is_best;
      const isInvalid = lap.invalid;
      const deltaClass = lap.delta === 'BEST' ? 'best-text' : (lap.delta && lap.delta.startsWith('+') ? 'positive' : '');
      rows += `<tr class="${isBest ? 'best-lap' : ''} ${isInvalid ? 'invalid' : ''}">
        <td class="lap-num">${lap.lap_num}</td>
        <td class="lap-time ${isBest ? 'best' : ''}">${lap.lap_time}${isBest ? ' ★' : ''}</td>
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
          <th>LAP</th><th>TIME</th><th>DELTA</th><th>S1</th><th>S2</th><th>S3</th><th></th>
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
setInterval(fetchState, 1000);
</script>

</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
def log_message(self, *args): pass  # silence request logs

```
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
        with state_lock:
            state["laps"].clear()
            state["best_lap_ms"] = None
            state["best_lap_num"] = None
            state["current_lap"] = 1
            state["session"]["started_at"] = None
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')
```

def main():
print(”=” * 50)
print(”  F1 Lap Tracker”)
print(”=” * 50)
print()
print(“IN-GAME SETUP (F1 25):”)
print(”  Settings → Telemetry Settings”)
print(”    UDP Telemetry  : On”)
print(”    UDP Format     : 2023 (or 2024)”)
print(”    UDP IP Address : 127.0.0.1”)
print(”    UDP Port       : 20777”)
print(”    Broadcast Mode : Off”)
print()

```
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
```

if **name** == “**main**”:
main()