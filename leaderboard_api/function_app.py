import hashlib
import ipaddress
import json
import logging
import os
import urllib.request as _urllib
from datetime import datetime, timezone

import azure.functions as func
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from better_profanity import profanity as _profanity

_profanity.load_censor_words()

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
}

DB_NAME = "f1tracker"
LEADERBOARD_CONTAINER = "leaderboard"
DEBRIEF_USAGE_CONTAINER = "debrief_usage"
DISPLAY_NAMES_CONTAINER = "display_names"
DAILY_DEBRIEF_LIMIT = 10
DAILY_IP_DEBRIEF_LIMIT = 20   # higher limit per IP to allow shared networks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_container(name: str = LEADERBOARD_CONTAINER):
    """Return a Cosmos DB container client by name."""
    conn_str = os.environ["COSMOS_CONNECTION_STRING"]
    client = CosmosClient.from_connection_string(conn_str)
    db = client.get_database_client(DB_NAME)
    return db.get_container_client(name)


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(data),
        status_code=status_code,
        headers=CORS_HEADERS,
        mimetype="application/json",
    )


def _error(message: str, status_code: int = 400) -> func.HttpResponse:
    return _json_response({"ok": False, "error": message}, status_code)


def _ms_to_laptime(ms) -> str:
    if not ms or ms <= 0:
        return "–:–.—"
    total_sec = ms / 1000.0
    minutes = int(total_sec // 60)
    seconds = int(total_sec % 60)
    millis = int(ms % 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


# ---------------------------------------------------------------------------
# Display-name helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lowercase + collapse whitespace — used as the uniqueness key."""
    return " ".join(name.lower().split())


def _check_and_register_name(display_name: str, player_id: str):
    """Return an error string if the name is taken, otherwise register it.

    Returns None on success, an error message string on conflict.
    The display_names container may not exist on older deployments;
    skip the check gracefully in that case.
    """
    normalized = _normalize_name(display_name)
    try:
        container = _get_container(DISPLAY_NAMES_CONTAINER)
        try:
            doc = container.read_item(item=normalized, partition_key=normalized)
            if doc.get("player_id") != player_id:
                return (
                    f'The display name "{display_name}" is already taken. '
                    "Please choose a different name."
                )
        except CosmosResourceNotFoundError:
            container.upsert_item({
                "id": normalized,
                "player_id": player_id,
                "display_name": display_name,
            })
    except Exception:
        # Container missing or other infra issue — skip uniqueness check
        # rather than blocking all submissions.
        logger.warning("display_names container unavailable; skipping uniqueness check")
    return None


# ---------------------------------------------------------------------------
# POST /api/lb-submit  (anonymous proxy — key stays server-side)
# POST /api/submit     (kept for backwards compat, requires function key)
# ---------------------------------------------------------------------------

def _handle_submit(body) -> func.HttpResponse:
    """Shared submit logic used by both endpoints."""
    required = ["player_id", "display_name", "track", "session_type", "lap_time_ms", "lap_time", "submitted_at"]
    missing = [f for f in required if f not in body or body[f] is None]
    if missing:
        return _error(f"Missing required fields: {', '.join(missing)}")

    player_id: str = str(body["player_id"]).strip()
    display_name: str = str(body["display_name"]).strip()
    track: str = str(body["track"]).strip()
    session_type: str = str(body["session_type"]).strip()
    lap_time_ms: int = body["lap_time_ms"]
    lap_time: str = str(body["lap_time"]).strip()
    compound: str = str(body.get("compound", "")).strip()
    submitted_at: str = str(body["submitted_at"]).strip()

    _VALID_COMPOUNDS = {"Soft", "Medium", "Hard", "Inter", "Wet", ""}

    if not player_id:
        return _error("player_id must not be empty.")
    if not display_name or len(display_name) > 32:
        return _error("display_name must be between 1 and 32 characters.")
    if not all(c.isprintable() for c in display_name):
        return _error("display_name contains invalid characters.")
    if _profanity.contains_profanity(display_name):
        return _error("That display name isn't allowed. Please choose a different name.")
    name_conflict = _check_and_register_name(display_name, player_id)
    if name_conflict:
        return _error(name_conflict)
    if not track or len(track) > 60:
        return _error("track must be between 1 and 60 characters.")
    if not session_type or len(session_type) > 30:
        return _error("session_type must be between 1 and 30 characters.")
    if not isinstance(lap_time_ms, int) or not (30_000 <= lap_time_ms <= 600_000):
        return _error("lap_time_ms must be an integer between 30000 and 600000.")
    if len(lap_time) > 20:
        return _error("lap_time string too long.")
    if compound not in _VALID_COMPOUNDS:
        return _error("Invalid compound value.")

    doc_id = f"{player_id}_{track}_{session_type}".replace(" ", "_")
    partition_key_value = f"{track}|{session_type}"

    document = {
        "id": doc_id,
        "track_session": partition_key_value,
        "player_id": player_id,
        "display_name": display_name,
        "track": track,
        "session_type": session_type,
        "lap_time_ms": lap_time_ms,
        "lap_time": lap_time,
        "compound": compound,
        "submitted_at": submitted_at,
    }

    container = _get_container(LEADERBOARD_CONTAINER)
    updated = False

    try:
        existing = container.read_item(item=doc_id, partition_key=partition_key_value)
        if lap_time_ms < existing.get("lap_time_ms", float("inf")):
            container.upsert_item(document)
            updated = True
    except CosmosResourceNotFoundError:
        container.upsert_item(document)
        updated = True

    query = (
        "SELECT VALUE COUNT(1) FROM c "
        "WHERE c.track_session = @pk AND c.lap_time_ms < @ms"
    )
    params = [
        {"name": "@pk", "value": partition_key_value},
        {"name": "@ms", "value": lap_time_ms},
    ]
    results = list(
        container.query_items(query=query, parameters=params, enable_cross_partition_query=False)
    )
    rank = int(results[0]) + 1 if results else 1

    return _json_response({"ok": True, "rank": rank, "updated": updated})


@app.route(route="lb-submit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def lb_submit(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.")
    return _handle_submit(body)


@app.route(route="submit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def submit(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.")
    return _handle_submit(body)


# ---------------------------------------------------------------------------
# GET /api/leaderboard/{track}/{session_type}
# ---------------------------------------------------------------------------

@app.route(route="leaderboard/{track}/{session_type}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def leaderboard(req: func.HttpRequest) -> func.HttpResponse:
    track: str = req.route_params.get("track", "").strip()
    session_type: str = req.route_params.get("session_type", "").strip()
    player_id: str = req.params.get("player_id", "").strip()

    if not track or not session_type:
        return _error("track and session_type path parameters are required.")

    partition_key_value = f"{track}|{session_type}"
    container = _get_container(LEADERBOARD_CONTAINER)

    top_query = (
        "SELECT c.player_id, c.display_name, c.lap_time, c.lap_time_ms, c.compound "
        "FROM c "
        "WHERE c.track_session = @pk "
        "ORDER BY c.track_session ASC, c.lap_time_ms ASC "
        "OFFSET 0 LIMIT 25"
    )
    top_params = [{"name": "@pk", "value": partition_key_value}]
    top_items = list(
        container.query_items(query=top_query, parameters=top_params, enable_cross_partition_query=False)
    )

    count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.track_session = @pk"
    count_results = list(
        container.query_items(query=count_query, parameters=top_params, enable_cross_partition_query=False)
    )
    total = int(count_results[0]) if count_results else 0

    entries = []
    player_in_top = False
    for i, item in enumerate(top_items):
        is_player = bool(player_id and item.get("player_id") == player_id)
        if is_player:
            player_in_top = True
        entries.append({
            "rank": i + 1,
            "display_name": item.get("display_name", ""),
            "lap_time": item.get("lap_time", ""),
            "lap_time_ms": item.get("lap_time_ms", 0),
            "compound": item.get("compound", ""),
            "is_player": is_player,
        })

    player_rank = None
    if player_id:
        if player_in_top:
            player_rank = next(e["rank"] for e in entries if e["is_player"])
        else:
            player_doc_id = f"{player_id}_{track}_{session_type}".replace(" ", "_")
            try:
                player_doc = container.read_item(item=player_doc_id, partition_key=partition_key_value)
                rank_query = (
                    "SELECT VALUE COUNT(1) FROM c "
                    "WHERE c.track_session = @pk AND c.lap_time_ms < @ms"
                )
                rank_params = [
                    {"name": "@pk", "value": partition_key_value},
                    {"name": "@ms", "value": player_doc["lap_time_ms"]},
                ]
                rank_results = list(
                    container.query_items(query=rank_query, parameters=rank_params, enable_cross_partition_query=False)
                )
                player_rank = int(rank_results[0]) + 1 if rank_results else None
            except CosmosResourceNotFoundError:
                player_rank = None

    return _json_response({
        "track": track,
        "session_type": session_type,
        "entries": entries,
        "total": total,
        "player_rank": player_rank,
    })


# ---------------------------------------------------------------------------
# GET /api/tracks
# ---------------------------------------------------------------------------

@app.route(route="tracks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def tracks(req: func.HttpRequest) -> func.HttpResponse:
    container = _get_container(LEADERBOARD_CONTAINER)
    query = "SELECT c.track, c.session_type FROM c"
    items = container.query_items(query=query, enable_cross_partition_query=True)

    seen: set = set()
    result = []
    for item in items:
        key = (item.get("track", ""), item.get("session_type", ""))
        if key not in seen:
            seen.add(key)
            result.append({"track": key[0], "session_type": key[1]})

    result.sort(key=lambda x: (x["track"], x["session_type"]))
    return _json_response(result)


# ---------------------------------------------------------------------------
# POST /api/debrief  (AI lap debrief proxy — rate limited, no client key needed)
# ---------------------------------------------------------------------------

@app.route(route="debrief", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def debrief(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.")

    player_id = str(body.get("player_id", "")).strip()
    if not player_id:
        return _error("player_id is required.")

    # ── Rate limiting — 10 debriefs per player per UTC day ───────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage_id = f"{player_id}_{today}"
    usage_container = _get_container(DEBRIEF_USAGE_CONTAINER)

    try:
        usage_doc = usage_container.read_item(item=usage_id, partition_key=player_id)
        count = int(usage_doc.get("count", 0))
    except CosmosResourceNotFoundError:
        count = 0

    if count >= DAILY_DEBRIEF_LIMIT:
        return _error(
            f"You've used all {DAILY_DEBRIEF_LIMIT} debriefs for today. Resets at midnight UTC.",
            429,
        )

    # ── IP-based rate limit — prevents bypass via new UUIDs ──────────────────
    x_forwarded = req.headers.get("X-Forwarded-For", "")
    raw_ip = x_forwarded.split(",")[0].strip() if x_forwarded else req.headers.get("X-Client-IP", "unknown")
    try:
        ipaddress.ip_address(raw_ip)
        client_ip = raw_ip
    except ValueError:
        client_ip = "invalid"
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    ip_pk = f"ip:{ip_hash}"
    ip_usage_id = f"ip_{ip_hash}_{today}"

    try:
        ip_doc = usage_container.read_item(item=ip_usage_id, partition_key=ip_pk)
        ip_count = int(ip_doc.get("count", 0))
    except CosmosResourceNotFoundError:
        ip_count = 0

    if ip_count >= DAILY_IP_DEBRIEF_LIMIT:
        return _error("Too many debrief requests from this network today. Resets at midnight UTC.", 429)

    # ── Validate lap data ─────────────────────────────────────────────────────
    laps = body.get("laps", [])
    if not laps:
        return _error("No laps provided.", 400)
    if not isinstance(laps, list) or len(laps) > 200:
        return _error("laps must be an array of at most 200 entries.", 400)

    session       = body.get("session", {})
    best_lap_ms   = body.get("best_lap_ms")
    track_pb_ms   = body.get("track_pb_ms")
    track_pb_cmp  = body.get("track_pb_compound")

    # ── Build prompt ──────────────────────────────────────────────────────────
    def _clean(s: str, max_len: int = 60) -> str:
        """Strip newlines and control characters to prevent prompt injection."""
        return str(s).replace("\n", " ").replace("\r", " ").strip()[:max_len]

    track     = _clean(session.get("track", "Unknown"))
    sess_type = _clean(session.get("session_type", "Unknown"))
    weather   = _clean(session.get("weather", "Unknown"))
    best_time = _ms_to_laptime(best_lap_ms)
    pb_time   = _ms_to_laptime(track_pb_ms) if track_pb_ms else "No record"
    pb_suffix = f" ({track_pb_cmp})" if track_pb_cmp else ""

    header = "Lap | Tyre   | Time         | Delta      | S1         | S2         | S3         | Valid"
    rows = []
    for lap in laps:
        valid = "INVALID" if lap.get("invalid") else "valid"
        rows.append(
            f"Lap {lap.get('lap_num', '?'):>3} | {(lap.get('compound') or '?'):>6} | "
            f"{lap.get('lap_time', '?')} | {lap.get('delta', ''):>9} | "
            f"{lap.get('s1', '—'):>9} | {lap.get('s2', '—'):>9} | "
            f"{lap.get('s3', '—'):>9} | {valid}"
        )

    # Build telemetry table if any laps have telem data
    telem_laps = [lap for lap in laps if lap.get("telem")]
    telem_section = ""
    if telem_laps:
        th = "Lap | MaxSpd | AvgSpd | AvgThr% | FullThr% | AvgBrk% | HvyBrk% | MaxGLat"
        trows = []
        for lap in telem_laps:
            t = lap["telem"]
            trows.append(
                f"Lap {lap.get('lap_num', '?'):>3} | "
                f"{t.get('max_speed', '—'):>6} | "
                f"{t.get('avg_speed', '—'):>6} | "
                f"{t.get('avg_throttle', '—'):>7} | "
                f"{t.get('full_throttle_pct', '—'):>8} | "
                f"{t.get('avg_brake', '—'):>7} | "
                f"{t.get('heavy_brake_pct', '—'):>7} | "
                f"{t.get('max_g_lat', '—'):>7}"
            )
        telem_section = (
            "\n\nTelemetry data (speed km/h, throttle/brake as %, G-force):\n"
            f"{th}\n" + "\n".join(trows)
        )

    has_telem = bool(telem_laps)
    telem_instruction = (
        " Where telemetry data is available, reference it specifically — "
        "comment on top speed, throttle application (full-throttle %), "
        "braking commitment (heavy-brake %), and peak lateral G as indicators of "
        "driving style and corner technique. Cross-reference with sector times to "
        "pinpoint where time is being lost."
        if has_telem else ""
    )

    prompt = (
        "You are a Formula 1 race engineer giving a post-session debrief to a sim racing driver.\n"
        "Analyse the lap and telemetry data below and give a concise, insightful debrief (3–5 short paragraphs).\n"
        "Cover: pace consistency, sector weaknesses, tyre compound performance, best lap analysis, "
        f"and one actionable recommendation for the next session.{telem_instruction}\n"
        "Use F1 engineering language. Be direct. Interpret the numbers — do not just repeat them.\n\n"
        f"Session: {track} — {sess_type} — {weather}\n"
        f"Session Best: {best_time}\n"
        f"Track PB: {pb_time}{pb_suffix}\n"
        f"Total laps: {len(laps)}\n\n"
        f"Lap data:\n{header}\n" + "\n".join(rows) + telem_section
    )

    # ── Call Azure OpenAI ─────────────────────────────────────────────────────
    endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    key        = os.environ.get("AZURE_OPENAI_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

    if not endpoint or not key:
        return _error("AI debrief not configured on server.", 503)

    aoai_url     = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-01"
    aoai_payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.7,
    }).encode()

    aoai_req = _urllib.Request(
        aoai_url,
        data=aoai_payload,
        headers={"Content-Type": "application/json", "api-key": key},
        method="POST",
    )

    try:
        with _urllib.urlopen(aoai_req, timeout=30) as resp:
            result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.error("Azure OpenAI error: %s", exc)
        return _error("AI service temporarily unavailable. Please try again.", 502)

    # ── Increment usage counters (TTL 90 000 s ≈ 25 h, auto-expires) ─────────
    usage_container.upsert_item({
        "id": usage_id,
        "player_id": player_id,
        "count": count + 1,
        "date": today,
        "ttl": 90000,
    })
    usage_container.upsert_item({
        "id": ip_usage_id,
        "player_id": ip_pk,
        "count": ip_count + 1,
        "date": today,
        "ttl": 90000,
    })

    remaining = DAILY_DEBRIEF_LIMIT - count - 1
    return _json_response({"debrief": text, "remaining": remaining})
