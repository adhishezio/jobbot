import json
from datetime import datetime, timedelta, timezone

from db import fetch_one


_STAGE_MAP = {
    "Webhook": (0.04, "Request Received"),
    "SerpAPI": (0.10, "Looking Up Company Address"),
    "Parse Address": (0.18, "Parsing Address Search Results"),
    "Save Confirmation Record": (0.22, "Saving Address Confirmation"),
    "Streamlit Notification": (0.25, "Waiting For Address Confirmation In JobBot"),
    "Wait": (0.25, "Waiting For Address Confirmation In JobBot"),
    "Fetch Final Address": (0.32, "Using Confirmed Address"),
    "Process Address Result": (0.36, "Preparing Application Data"),
    "Fetch Job Summary": (0.42, "Loading Saved Job Context"),
    "Read Resume & Merge Data": (0.48, "Loading Resume And Template"),
    "Get Vertex Access Token": (0.54, "Authenticating Vertex AI"),
    "Build Generator Request": (0.58, "Preparing Generator Prompt"),
    "GENERATOR": (0.64, "Generating First Draft"),
    "Build Critic Request": (0.72, "Preparing Critic Review"),
    "CRITIC": (0.78, "Reviewing Draft Quality"),
    "Critic Output": (0.82, "Scoring Draft"),
    "If": (0.84, "Checking Quality Gate"),
    "REFINER": (0.88, "Refining The Letter"),
    "Build Refiner Request": (0.90, "Preparing Another Review Round"),
    "Process Template": (0.93, "Rendering LaTeX Template"),
    "Compile & Save PDF": (0.96, "Compiling PDF"),
    "Execute a SQL query1": (0.98, "Saving Cover Letter"),
    "Code in JavaScript": (0.99, "Preparing Completion Notifications"),
    "Telegram Completion Notification": (0.992, "Sending Telegram Completion Notification"),
    "Execute a SQL query2": (0.996, "Saving Completion Notification"),
    "Respond to Webhook": (1.00, "Completed"),
}


def _looks_like_ref(value, parsed):
    return isinstance(value, str) and value.isdigit() and int(value) < len(parsed)


def decode_flatted(raw_value):
    if raw_value in (None, ""):
        return None

    parsed = raw_value
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)

    if not isinstance(parsed, list) or not parsed:
        return parsed

    memo = {}

    def revive(node):
        if _looks_like_ref(node, parsed):
            index = int(node)
            if index in memo:
                return memo[index]
            placeholder = {}
            memo[index] = placeholder
            resolved = revive(parsed[index])
            memo[index] = resolved
            return resolved
        if isinstance(node, list):
            return [revive(item) for item in node]
        if isinstance(node, dict):
            return {key: revive(value) for key, value in node.items()}
        return node

    return revive(parsed[0])


def find_address_confirmation(company, position, started_at, execution_id=None):
    if execution_id:
        return fetch_one(
            """
            SELECT *
            FROM address_confirmations
            WHERE execution_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(execution_id),),
        )

    if not company or not position:
        return None

    started_dt = datetime.fromtimestamp(started_at, tz=timezone.utc) - timedelta(minutes=5)
    return fetch_one(
        """
        SELECT *
        FROM address_confirmations
        WHERE company = %s
          AND position = %s
          AND created_at >= %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (company, position, started_dt),
    )


def fetch_execution_snapshot(execution_id):
    if not execution_id:
        return None

    row = fetch_one(
        """
        SELECT e.id,
               e.status,
               e."startedAt" AS started_at,
               e."stoppedAt" AS stopped_at,
               e.finished,
               d.data
        FROM execution_entity e
        LEFT JOIN execution_data d ON d."executionId" = e.id
        WHERE e.id = %s
        LIMIT 1
        """,
        (int(execution_id),),
    )
    if not row:
        return None

    decoded = None
    last_node = None
    error_info = None
    try:
        decoded = decode_flatted(row.get("data")) if row.get("data") else None
        result_data = (decoded or {}).get("resultData") or {}
        last_node = result_data.get("lastNodeExecuted")
        error_info = result_data.get("error") or None
    except Exception as exc:
        error_info = {"message": f"Could not decode n8n execution payload: {exc}"}

    node_name = None
    error_message = None
    if isinstance(error_info, dict):
        node_name = ((error_info.get("node") or {}).get("name") or last_node)
        error_message = error_info.get("message") or error_info.get("description")

    return {
        "execution_id": row["id"],
        "status": row.get("status") or "unknown",
        "finished": row.get("finished"),
        "started_at": row.get("started_at"),
        "stopped_at": row.get("stopped_at"),
        "last_node": last_node,
        "error_node": node_name,
        "error_message": error_message,
        "raw_error": error_info,
        "decoded": decoded,
    }


def describe_pipeline_progress(pending):
    company = pending.get("company")
    position = pending.get("review", {}).get("position")
    started_at = pending.get("started_at") or 0
    known_execution_id = pending.get("execution_id")

    confirmation = find_address_confirmation(company, position, started_at, known_execution_id)
    if confirmation and not known_execution_id:
        known_execution_id = confirmation.get("execution_id")
        pending["execution_id"] = known_execution_id

    execution = fetch_execution_snapshot(known_execution_id) if known_execution_id else None

    if confirmation and confirmation.get("status") == "pending":
        if confirmation.get("address_found") and confirmation.get("found_street"):
            return {
                "execution_id": known_execution_id,
                "progress": 0.25,
                "label": "Waiting For Address Confirmation In JobBot",
                "detail": f"Address found: {confirmation.get('found_street')} {confirmation.get('found_plz_city') or ''}".strip(),
                "state": "running",
                "needs_address": True,
                "execution": execution,
            }
        return {
            "execution_id": known_execution_id,
            "progress": 0.20,
            "label": "Waiting For Manual Address Entry",
            "detail": "SerpAPI could not find the address automatically. Please confirm it in the JobBot sidebar.",
            "state": "running",
            "needs_address": True,
            "execution": execution,
        }

    if confirmation and confirmation.get("status") == "confirmed":
        if execution and execution.get("status") == "error":
            stage_node = execution.get("error_node") or execution.get("last_node") or "Unknown Node"
            progress, label = _STAGE_MAP.get(stage_node, (0.0, stage_node))
            return {
                "execution_id": known_execution_id,
                "progress": progress,
                "label": label,
                "detail": execution.get("error_message") or "n8n reported an error.",
                "state": "error",
                "node": stage_node,
                "execution": execution,
            }

        if not execution or execution.get("last_node") in {"Wait", "Streamlit Notification"}:
            return {
                "execution_id": known_execution_id,
                "progress": 0.30,
                "label": "Address Confirmed - Resuming Workflow",
                "detail": "The address was confirmed in JobBot. n8n is continuing with the generation and review steps.",
                "state": "running",
                "needs_address": False,
                "execution": execution,
            }

    if execution and execution.get("status") == "error":
        stage_node = execution.get("error_node") or execution.get("last_node") or "Unknown Node"
        progress, label = _STAGE_MAP.get(stage_node, (0.0, stage_node))
        return {
            "execution_id": known_execution_id,
            "progress": progress,
            "label": label,
            "detail": execution.get("error_message") or "n8n reported an error.",
            "state": "error",
            "node": stage_node,
            "execution": execution,
        }

    if execution and execution.get("finished"):
        return {
            "execution_id": known_execution_id,
            "progress": 0.995,
            "label": "Loading Final Cover Letter",
            "detail": "n8n finished successfully. JobBot is loading the saved PDF and database record.",
            "state": "running",
            "execution": execution,
        }

    if execution:
        stage_node = execution.get("last_node") or "Webhook"
        progress, label = _STAGE_MAP.get(stage_node, (0.3, stage_node))
        return {
            "execution_id": known_execution_id,
            "progress": progress,
            "label": label,
            "detail": f"Latest completed node: {stage_node}",
            "state": "running",
            "execution": execution,
        }

    return {
        "execution_id": known_execution_id,
        "progress": 0.08,
        "label": "Starting Pipeline",
        "detail": "Waiting for n8n to create the execution record.",
        "state": "running",
        "execution": execution,
    }
