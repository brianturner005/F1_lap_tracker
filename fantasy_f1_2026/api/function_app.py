import json
import os
import azure.functions as func
from azure.cosmos import CosmosClient, exceptions

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

SCORING = {0: 25, 1: 10, 2: 5, 3: 2}


def get_container():
    client = CosmosClient.from_connection_string(os.environ["COSMOS_CONNECTION_STRING"])
    return client.get_database_client("fantasy_f1").get_container_client("data")


def json_response(body, status=200):
    return func.HttpResponse(
        json.dumps(body),
        status_code=status,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def score_pick(picks, result):
    total = 0
    for predicted_idx, driver_id in enumerate(picks):
        try:
            actual_idx = result.index(driver_id)
            diff = abs(predicted_idx - actual_idx)
            total += SCORING.get(diff, 0)
        except ValueError:
            pass
    return total


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

@app.route(route="players", methods=["GET", "POST", "DELETE"])
def players(req: func.HttpRequest) -> func.HttpResponse:
    container = get_container()

    if req.method == "GET":
        try:
            doc = container.read_item("players", partition_key="config")
            return json_response({"players": doc.get("players", [])})
        except exceptions.CosmosResourceNotFoundError:
            return json_response({"players": []})

    body = req.get_json()
    name = body.get("name", "").strip()
    if not name:
        return json_response({"error": "name required"}, 400)

    try:
        doc = container.read_item("players", partition_key="config")
    except exceptions.CosmosResourceNotFoundError:
        doc = {"id": "players", "type": "config", "players": []}

    if req.method == "POST":
        if name not in doc["players"]:
            doc["players"].append(name)
        container.upsert_item(doc)
        return json_response({"players": doc["players"]})

    if req.method == "DELETE":
        doc["players"] = [p for p in doc["players"] if p != name]
        container.upsert_item(doc)
        return json_response({"players": doc["players"]})


# ---------------------------------------------------------------------------
# Picks — /api/picks/{raceId}
# ---------------------------------------------------------------------------

@app.route(route="picks/{raceId}", methods=["GET", "POST"])
def picks(req: func.HttpRequest) -> func.HttpResponse:
    race_id = req.route_params.get("raceId")
    container = get_container()

    if req.method == "GET":
        query = "SELECT * FROM c WHERE c.type = 'pick' AND c.raceId = @raceId"
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@raceId", "value": race_id}],
            enable_cross_partition_query=True,
        ))
        picks_map = {item["player"]: item["order"] for item in items}
        return json_response({"picks": picks_map})

    body = req.get_json()
    player = body.get("player", "").strip()
    order = body.get("order", [])
    if not player or not order:
        return json_response({"error": "player and order required"}, 400)

    doc = {
        "id": f"pick_{race_id}_{player}",
        "type": "pick",
        "raceId": race_id,
        "player": player,
        "order": order,
    }
    container.upsert_item(doc)
    return json_response({"ok": True})


# ---------------------------------------------------------------------------
# Results — /api/results/{raceId}
# ---------------------------------------------------------------------------

@app.route(route="results/{raceId}", methods=["GET", "POST"])
def results(req: func.HttpRequest) -> func.HttpResponse:
    race_id = req.route_params.get("raceId")
    container = get_container()
    doc_id = f"result_{race_id}"

    if req.method == "GET":
        try:
            doc = container.read_item(doc_id, partition_key="result")
            return json_response({"result": doc.get("order", None)})
        except exceptions.CosmosResourceNotFoundError:
            return json_response({"result": None})

    body = req.get_json()
    order = body.get("order", [])
    if not order:
        return json_response({"error": "order required"}, 400)

    container.upsert_item({
        "id": doc_id,
        "type": "result",
        "raceId": race_id,
        "order": order,
    })
    return json_response({"ok": True})


# ---------------------------------------------------------------------------
# Leaderboard — /api/leaderboard
# ---------------------------------------------------------------------------

@app.route(route="leaderboard", methods=["GET"])
def leaderboard(req: func.HttpRequest) -> func.HttpResponse:
    container = get_container()

    results_items = list(container.query_items(
        query="SELECT * FROM c WHERE c.type = 'result'",
        enable_cross_partition_query=True,
    ))
    picks_items = list(container.query_items(
        query="SELECT * FROM c WHERE c.type = 'pick'",
        enable_cross_partition_query=True,
    ))

    results_map = {item["raceId"]: item["order"] for item in results_items}
    picks_by_race = {}
    for item in picks_items:
        picks_by_race.setdefault(item["raceId"], {})[item["player"]] = item["order"]

    scores = {}
    for race_id, result in results_map.items():
        for player, order in picks_by_race.get(race_id, {}).items():
            if player not in scores:
                scores[player] = {"total": 0, "races": {}}
            pts = score_pick(order, result)
            scores[player]["races"][race_id] = pts
            scores[player]["total"] += pts

    return json_response({"scores": scores, "results": results_map, "picksByRace": picks_by_race})
