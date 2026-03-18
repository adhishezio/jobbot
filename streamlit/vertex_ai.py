import json
import os

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account


VERTEX_SCOPE = ["https://www.googleapis.com/auth/cloud-platform"]


def has_vertex_service_account():
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))


def _service_account_info():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}") from exc


def _vertex_credentials():
    info = _service_account_info()
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=VERTEX_SCOPE,
    )
    credentials.refresh(Request())
    return credentials, info


def _vertex_endpoint(model_name, project_info):
    info = project_info
    project_id = os.environ.get("VERTEX_AI_PROJECT_ID") or info.get("project_id")
    location = os.environ.get("VERTEX_AI_LOCATION", "global")
    if not project_id:
        raise RuntimeError("VERTEX_AI_PROJECT_ID is missing.")
    return (
        f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}"
        f"/publishers/google/models/{model_name}:generateContent"
    )


def generate_content(parts, model_name, system_prompt=None, temperature=0.2, response_mime_type=None, timeout=90):
    credentials, info = _vertex_credentials()
    endpoint = _vertex_endpoint(model_name, info)

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature},
    }
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
    if response_mime_type:
        payload["generationConfig"]["responseMimeType"] = response_mime_type

    response = requests.post(
        endpoint,
        json=payload,
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def response_text(payload):
    return (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
