import json
import logging
import os
import urllib.request as _urllib
from datetime import datetime, timezone

import azure.functions as func
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

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
DAILY_DEBRIEF_LIMIT = 10


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
# POST /api/submit  (leaderboard PB submission)
# ---------------------------------------------------------------------------

@app.route(route="submit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def submit(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.")

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

    if not player_id:
        return _error("player_id must not be empty.")
    if not display_name or len(display_name) > 32:
        return _error("display_name must be between 1 and 32 characters.")
    if not track:
        return _error("track must not be empty.")
    if not session_type:
        return _error("session_type must not be empty.")
    if not isinstance(lap_time_ms, int) or not (30_000 <= lap_time_ms <= 600_000):
        return _error("lap_time_ms must be an integer between 30000 and 600000.")

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

    # ── Validate lap data ─────────────────────────────────────────────────────
    laps = body.get("laps", [])
    if not laps:
        return _error("No laps provided.", 400)

    session       = body.get("session", {})
    best_lap_ms   = body.get("best_lap_ms")
    track_pb_ms   = body.get("track_pb_ms")
    track_pb_cmp  = body.get("track_pb_compound")

    # ── Build prompt ──────────────────────────────────────────────────────────
    track     = session.get("track", "Unknown")
    sess_type = session.get("session_type", "Unknown")
    weather   = session.get("weather", "Unknown")
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

    prompt = (
        "You are a Formula 1 race engineer giving a post-session debrief to a sim racing driver.\n"
        "Analyse the lap data below and give a concise, insightful debrief (3–5 short paragraphs).\n"
        "Cover: pace consistency, sector weaknesses, tyre compound performance, best lap analysis, "
        "and one actionable recommendation for the next session.\n"
        "Use F1 engineering language. Be direct. Interpret the numbers — do not just repeat them.\n\n"
        f"Session: {track} — {sess_type} — {weather}\n"
        f"Session Best: {best_time}\n"
        f"Track PB: {pb_time}{pb_suffix}\n"
        f"Total laps: {len(laps)}\n\n"
        f"Lap data:\n{header}\n" + "\n".join(rows)
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
        "max_tokens": 600,
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
        return _error(f"AI service error: {str(exc)}", 502)

    # ── Increment usage counter (TTL 90 000 s ≈ 25 h, auto-expires) ──────────
    usage_container.upsert_item({
        "id": usage_id,
        "player_id": player_id,
        "count": count + 1,
        "date": today,
        "ttl": 90000,
    })

    remaining = DAILY_DEBRIEF_LIMIT - count - 1
    return _json_response({"debrief": text, "remaining": remaining})
