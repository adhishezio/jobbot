# Migration SQL:
# CREATE TABLE IF NOT EXISTS email_analyses (
#   id SERIAL PRIMARY KEY,
#   gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
#   sender TEXT,
#   subject TEXT,
#   snippet TEXT,
#   email_type VARCHAR(50),
#   company VARCHAR(255),
#   action_required TEXT,
#   suggested_reply TEXT,
#   message_date TIMESTAMP,
#   is_unread BOOLEAN DEFAULT TRUE,
#   analysed_at TIMESTAMP DEFAULT NOW()
# );

import json
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

from components import show_address_confirmation_card
from db import execute, execute_returning, fetch_all, fetch_one
from ui import apply_ui_theme


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SECRETS_DIR = "/secrets"
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SECRETS_DIR, "token.json")
REDIRECT_URI = "http://localhost"
OLLAMA_MODEL_PREFERENCES = ["qwen2.5:1.5b", "qwen2.5:0.5b", "qwen2.5:7b-instruct-q4_K_M"]
EMAIL_SYNC_HOURS = 5
MAX_EMAILS = 30
MAX_AUTO_ANALYZE = 8
VISIBLE_EMAIL_TYPES = {"interview_invite", "rejection", "offer", "follow_up", "recruiter_outreach"}

POSITIVE_PATTERNS = [
    r"\bapplication\b",
    r"\bapplied\b",
    r"\bbewerbung\b",
    r"\binterview\b",
    r"\beinladung\b",
    r"\binvite\b",
    r"\boffer\b",
    r"\bangebot\b",
    r"\brejection\b",
    r"\babsage\b",
    r"\brecruiter\b",
    r"\bhiring\b",
    r"\bjob application\b",
    r"\bapplication status\b",
    r"\bposition\b",
    r"\bkarriere\b",
]
NEGATIVE_PATTERNS = [
    r"job alert",
    r"newsletter",
    r"digest",
    r"promo",
    r"promotion",
    r"publicly accessible google api key",
    r"coffee",
    r"sale",
    r"webinar",
    r"event",
]


st.set_page_config(page_title="Job Email Inbox", page_icon="📬", layout="wide")
apply_ui_theme()
st.title("📬 Job Email Inbox")
st.session_state["current_page"] = "email_inbox"

with st.sidebar:
    show_address_confirmation_card()


def _token_credentials():
    if not os.path.exists(TOKEN_PATH):
        return None

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as handle:
            handle.write(creds.to_json())
    return creds if creds and creds.valid else None


def _oauth_flow():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    flow.redirect_uri = REDIRECT_URI
    return flow


def _start_oauth():
    flow = _oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    st.session_state["gmail_oauth_state"] = state
    st.session_state["gmail_code_verifier"] = flow.code_verifier
    st.session_state["gmail_auth_url"] = auth_url


def _finish_oauth(code):
    flow = _oauth_flow()
    flow.code_verifier = st.session_state.get("gmail_code_verifier")
    flow.fetch_token(code=code.strip())
    with open(TOKEN_PATH, "w", encoding="utf-8") as handle:
        handle.write(flow.credentials.to_json())
    st.session_state.pop("gmail_auth_url", None)
    st.session_state.pop("gmail_oauth_state", None)
    st.session_state.pop("gmail_code_verifier", None)


def _gmail_service():
    creds = _token_credentials()
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header_value(headers, name):
    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]
    return ""


def _message_date(raw_value):
    try:
        return parsedate_to_datetime(raw_value).replace(tzinfo=None)
    except Exception:
        return None


def _looks_job_related(sender, subject, snippet):
    haystack = f"{sender} {subject} {snippet}".lower()
    if any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in NEGATIVE_PATTERNS):
        return False
    return any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in POSITIVE_PATTERNS)


def _fetch_job_related_emails():
    service = _gmail_service()
    if not service:
        return []

    response = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        q="newer_than:45d -category:promotions -category:social -category:forums",
        maxResults=80,
    ).execute()

    messages = response.get("messages", [])
    collected = []
    for message in messages:
        message_data = service.users().messages().get(
            userId="me",
            id=message["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = message_data.get("payload", {}).get("headers", [])
        sender = _header_value(headers, "From")
        subject = _header_value(headers, "Subject")
        snippet = (message_data.get("snippet") or "")[:200]

        if not _looks_job_related(sender, subject, snippet):
            continue

        collected.append(
            {
                "id": message_data["id"],
                "sender": sender,
                "subject": subject,
                "date": _header_value(headers, "Date"),
                "message_date": _message_date(_header_value(headers, "Date")),
                "snippet": snippet,
                "is_unread": "UNREAD" in message_data.get("labelIds", []),
            }
        )

    collected.sort(key=lambda item: item["message_date"] or datetime.min, reverse=True)
    return collected[:MAX_EMAILS]


def _extract_json_block(text):
    text = (text or "").strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("The Ollama response did not contain JSON.")
    return json.loads(match.group(0))


def _ensure_ollama_model():
    response = requests.get("http://ollama:11434/api/tags", timeout=10)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama did not respond correctly: HTTP {response.status_code}")

    models = response.json().get("models", [])
    model_names = {model.get("name") for model in models}
    for model_name in OLLAMA_MODEL_PREFERENCES:
        if model_name in model_names:
            return model_name

    preferred = ", ".join(OLLAMA_MODEL_PREFERENCES)
    available = ", ".join(sorted(model_names)) or "none"
    raise RuntimeError(
        f"Ollama is reachable, but none of the preferred models are available. "
        f"Preferred: {preferred}. Available: {available}."
    )


def _analyze_email(email_record):
    ollama_model = _ensure_ollama_model()

    prompt = (
        "You are a job application assistant. Analyze this email and extract:\n"
        "1. Email type (interview_invite / rejection / offer / follow_up / recruiter_outreach / other)\n"
        "2. Company name\n"
        "3. Key action required (if any)\n"
        "4. Suggested reply (2-3 sentences, professional tone)\n"
        "Keep response short and structured as JSON.\n\n"
        f"Sender: {email_record['sender']}\n"
        f"Subject: {email_record['subject']}\n"
        f"Snippet: {email_record['snippet']}\n"
    )

    response = requests.post(
        "http://ollama:11434/api/generate",
        json={
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
        },
        timeout=60,
    )
    if response.status_code != 200:
        error_text = response.text[:400]
        raise RuntimeError(f"Ollama HTTP {response.status_code}: {error_text}")

    body = response.json()
    return _extract_json_block(body.get("response", ""))


def _save_analysis(email_record, analysis):
    row = execute_returning(
        """
        INSERT INTO email_analyses (
            gmail_message_id,
            sender,
            subject,
            snippet,
            email_type,
            company,
            action_required,
            suggested_reply,
            message_date,
            is_unread
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gmail_message_id) DO UPDATE
        SET sender = EXCLUDED.sender,
            subject = EXCLUDED.subject,
            snippet = EXCLUDED.snippet,
            email_type = EXCLUDED.email_type,
            company = EXCLUDED.company,
            action_required = EXCLUDED.action_required,
            suggested_reply = EXCLUDED.suggested_reply,
            message_date = EXCLUDED.message_date,
            is_unread = EXCLUDED.is_unread,
            analysed_at = NOW()
        RETURNING id
        """,
        (
            email_record["id"],
            email_record["sender"],
            email_record["subject"],
            email_record["snippet"],
            analysis.get("email_type"),
            analysis.get("company"),
            analysis.get("action_required"),
            analysis.get("suggested_reply"),
            email_record["message_date"],
            email_record["is_unread"],
        ),
    )
    return row["id"] if row else None


def _cache_email_metadata(email_record):
    execute(
        """
        INSERT INTO email_analyses (
            gmail_message_id,
            sender,
            subject,
            snippet,
            message_date,
            is_unread
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (gmail_message_id) DO UPDATE
        SET sender = EXCLUDED.sender,
            subject = EXCLUDED.subject,
            snippet = EXCLUDED.snippet,
            message_date = EXCLUDED.message_date,
            is_unread = EXCLUDED.is_unread
        """,
        (
            email_record["id"],
            email_record["sender"],
            email_record["subject"],
            email_record["snippet"],
            email_record["message_date"],
            email_record["is_unread"],
        ),
    )


def _last_ai_sync():
    row = fetch_one("SELECT value FROM settings WHERE key = %s", ("email_ai_last_sync_at",))
    if not row or not row.get("value"):
        return None
    try:
        return datetime.fromisoformat(row["value"])
    except ValueError:
        return None


def _set_last_ai_sync(timestamp):
    execute(
        """
        INSERT INTO settings (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("email_ai_last_sync_at", timestamp.isoformat()),
    )


def _saved_analysis_map():
    rows = fetch_all(
        """
        SELECT *
        FROM email_analyses
        ORDER BY COALESCE(message_date, analysed_at) DESC
        """
    )
    return {row["gmail_message_id"]: row for row in rows}


def _auto_analyze_emails(emails, force=False):
    last_sync = _last_ai_sync()
    if not force and last_sync and datetime.utcnow() - last_sync < timedelta(hours=EMAIL_SYNC_HOURS):
        return None

    saved_map = _saved_analysis_map()
    candidates = []
    for email_record in emails:
        existing = saved_map.get(email_record["id"])
        if email_record["is_unread"] or not existing or not existing.get("email_type"):
            candidates.append(email_record)

    candidates = candidates[:MAX_AUTO_ANALYZE]
    if not candidates:
        _set_last_ai_sync(datetime.utcnow())
        return {"analyzed": 0, "error": None}

    analyzed_count = 0
    for email_record in candidates:
        analysis = _analyze_email(email_record)
        _save_analysis(email_record, analysis)
        analyzed_count += 1

    _set_last_ai_sync(datetime.utcnow())
    return {"analyzed": analyzed_count, "error": None}


if not os.path.exists(CREDENTIALS_PATH):
    st.error("Missing /secrets/credentials.json. Add your Gmail OAuth client file first.")
    st.stop()


creds = _token_credentials()
if not creds:
    st.info("Complete the one-time Gmail OAuth setup to read your inbox here.")
    if st.button("Start Gmail OAuth Setup", type="primary"):
        _start_oauth()

    auth_url = st.session_state.get("gmail_auth_url")
    if auth_url:
        st.link_button("Open Google Authorization", auth_url)
        st.caption(
            "After approving access, copy the code from the redirected localhost URL and paste it below."
        )
        auth_code = st.text_input("Authorization code")
        if st.button("Save Gmail Token", use_container_width=True):
            if not auth_code.strip():
                st.error("Paste the authorization code first.")
            else:
                try:
                    _finish_oauth(auth_code)
                    st.success("Gmail token saved successfully.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not finish Gmail OAuth: {exc}")
    st.stop()


emails = _fetch_job_related_emails()
for email_record in emails:
    _cache_email_metadata(email_record)

force_refresh = st.button("Refresh AI Analysis Now", use_container_width=False)
last_sync = _last_ai_sync()
if last_sync:
    st.caption(
        f"Latest job-related emails from the last 45 days. Local AI refresh runs at most every {EMAIL_SYNC_HOURS} hours. "
        f"Last AI sync: {last_sync.strftime('%d %b %Y %H:%M')}"
    )
else:
    st.caption(
        f"Latest job-related emails from the last 45 days. Local AI refresh runs at most every {EMAIL_SYNC_HOURS} hours."
    )

analysis_error = None
if emails:
    try:
        auto_result = _auto_analyze_emails(emails, force=force_refresh)
        if auto_result and auto_result.get("analyzed"):
            st.success(f"Auto-analyzed {auto_result['analyzed']} recent job emails with local Ollama.")
    except Exception as exc:
        analysis_error = str(exc)
        st.warning(f"Ollama auto-analysis is currently unavailable: {exc}")


saved_map = _saved_analysis_map()
if not emails:
    st.info("No recent job-related emails matched the stricter inbox filter.")
    st.stop()


unread_count = sum(1 for email_record in emails if email_record["is_unread"])
st.info(f"{unread_count} unread job-related emails in the latest view.")

visible_emails = []
for email_record in emails:
    analysis = saved_map.get(email_record["id"])
    if analysis and analysis.get("email_type") in VISIBLE_EMAIL_TYPES:
        visible_emails.append(email_record)
    elif not analysis and email_record["is_unread"]:
        visible_emails.append(email_record)

if not visible_emails:
    st.info("No classified interview, rejection, offer, follow-up, or recruiter emails were found in the current inbox window.")
    st.stop()

for email_record in visible_emails:
    analysis = saved_map.get(email_record["id"])
    with st.container(border=True):
        if email_record["is_unread"]:
            st.warning("Unread")
        else:
            st.caption("Read")

        top_col, meta_col = st.columns([4, 1])
        with top_col:
            st.markdown(f"**{email_record['subject'] or '(No subject)'}**")
            st.caption(f"{email_record['sender']} | {email_record['date']}")
            st.write(email_record["snippet"] or "No snippet available.")

        with meta_col:
            if analysis and analysis.get("email_type"):
                st.metric("Type", analysis["email_type"])
            elif analysis_error:
                st.caption("AI unavailable")
            else:
                st.caption("Waiting for AI sync")

        if analysis:
            st.json(
                {
                    "email_type": analysis.get("email_type"),
                    "company": analysis.get("company"),
                    "action_required": analysis.get("action_required"),
                    "suggested_reply": analysis.get("suggested_reply"),
                }
            )
