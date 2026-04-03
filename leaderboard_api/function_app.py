import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
}

DB_NAME = "f1tracker"
CONTAINER_NAME = "leaderboard"


def _get_container():
    """Create a Cosmos DB container client from the connection string env var."""
    conn_str = os.environ["COSMOS_CONNECTION_STRING"]
    client = CosmosClient.from_connection_string(conn_str)
    db = client.get_database_client(DB_NAME)
    container = db.get_container_client(CONTAINER_NAME)
    return container


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(data),
        status_code=status_code,
        headers=CORS_HEADERS,
        mimetype="application/json",
    )


def _error(message: str, status_code: int = 400) -> func.HttpResponse:
    return _json_response({"ok": False, "error": message}, status_code)


# ---------------------------------------------------------------------------
# POST /api/submit
# ---------------------------------------------------------------------------

@app.route(route="submit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def submit(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.")

    # --- Required field validation ---
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

    container = _get_container()
    updated = False

    try:
        existing = container.read_item(item=doc_id, partition_key=partition_key_value)
        if lap_time_ms < existing.get("lap_time_ms", float("inf")):
            container.upsert_item(document)
            updated = True
        # else: existing record is faster — do not update
    except CosmosResourceNotFoundError:
        container.upsert_item(document)
        updated = True

    # Count entries faster than this submission to determine rank (1-based).
    query = (
        "SELECT VALUE COUNT(1) FROM c "
        "WHERE c.track_session = @pk AND c.lap_time_ms < @ms"
    )
    params = [
        {"name": "@pk", "value": partition_key_value},
        {"name": "@ms", "value": lap_time_ms},
    ]
    results = list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=False,
        )
    )
    faster_count = results[0] if results else 0
    rank = int(faster_count) + 1

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
    container = _get_container()

    # Top 25 entries ordered by lap time ascending.
    top_query = (
        "SELECT c.player_id, c.display_name, c.lap_time, c.lap_time_ms, c.compound "
        "FROM c "
        "WHERE c.track_session = @pk "
        "ORDER BY c.track_session ASC, c.lap_time_ms ASC "
        "OFFSET 0 LIMIT 25"
    )
    top_params = [{"name": "@pk", "value": partition_key_value}]

    top_items = list(
        container.query_items(
            query=top_query,
            parameters=top_params,
            enable_cross_partition_query=False,
        )
    )

    # Total count in this partition.
    count_query = (
        "SELECT VALUE COUNT(1) FROM c WHERE c.track_session = @pk"
    )
    count_results = list(
        container.query_items(
            query=count_query,
            parameters=top_params,
            enable_cross_partition_query=False,
        )
    )
    total = int(count_results[0]) if count_results else 0

    entries = []
    player_in_top = False
    for i, item in enumerate(top_items):
        is_player = bool(player_id and item.get("player_id") == player_id)
        if is_player:
            player_in_top = True
        entries.append(
            {
                "rank": i + 1,
                "display_name": item.get("display_name", ""),
                "lap_time": item.get("lap_time", ""),
                "lap_time_ms": item.get("lap_time_ms", 0),
                "compound": item.get("compound", ""),
                "is_player": is_player,
            }
        )

    # Compute player rank if they exist but are outside top 25.
    player_rank = None
    if player_id:
        if player_in_top:
            player_rank = next(e["rank"] for e in entries if e["is_player"])
        else:
            # Count how many entries are faster than the player's best.
            player_doc_id = f"{player_id}_{track}_{session_type}".replace(" ", "_")
            try:
                player_doc = container.read_item(
                    item=player_doc_id, partition_key=partition_key_value
                )
                rank_query = (
                    "SELECT VALUE COUNT(1) FROM c "
                    "WHERE c.track_session = @pk AND c.lap_time_ms < @ms"
                )
                rank_params = [
                    {"name": "@pk", "value": partition_key_value},
                    {"name": "@ms", "value": player_doc["lap_time_ms"]},
                ]
                rank_results = list(
                    container.query_items(
                        query=rank_query,
                        parameters=rank_params,
                        enable_cross_partition_query=False,
                    )
                )
                player_rank = int(rank_results[0]) + 1 if rank_results else None
            except CosmosResourceNotFoundError:
                player_rank = None

    return _json_response(
        {
            "track": track,
            "session_type": session_type,
            "entries": entries,
            "total": total,
            "player_rank": player_rank,
        }
    )


# ---------------------------------------------------------------------------
# GET /api/tracks
# ---------------------------------------------------------------------------

@app.route(route="tracks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def tracks(req: func.HttpRequest) -> func.HttpResponse:
    container = _get_container()

    # Cosmos DB SQL does not support DISTINCT natively for projected fields,
    # so we fetch track/session_type from all documents and deduplicate in Python.
    # For large datasets this is acceptable; for very large ones a separate
    # summary container would be preferable.
    query = "SELECT c.track, c.session_type FROM c"
    items = container.query_items(
        query=query,
        enable_cross_partition_query=True,
    )

    seen: set = set()
    result = []
    for item in items:
        key = (item.get("track", ""), item.get("session_type", ""))
        if key not in seen:
            seen.add(key)
            result.append({"track": key[0], "session_type": key[1]})

    result.sort(key=lambda x: (x["track"], x["session_type"]))
    return _json_response(result)
