import json
import os

import google.generativeai as genai
import pandas as pd
import streamlit as st

from components import show_address_confirmation_card
from duplicate_detection import find_possible_duplicates
from job_review import FIELD_DEFAULTS, build_generation_payload, persist_job, render_job_review_editor, seed_review_state
from post_generation import poll_cover_letter_completion, render_generated_cover_letter, start_cover_letter_generation
from screenshot_tab import render_screenshot_upload_tab
from uploaded_application import render_uploaded_application_panel
from ui import apply_ui_theme


st.set_page_config(page_title="New Application", page_icon="📝", layout="wide")
apply_ui_theme()
st.title("📝 New Application")
st.session_state["current_page"] = "new_application"

if st.session_state.get("new_application_notice"):
    st.info(st.session_state.pop("new_application_notice"))

with st.sidebar:
    show_address_confirmation_card()


def _reset_review_state(prefix):
    for field, default_value in FIELD_DEFAULTS.items():
        st.session_state[f"{prefix}_{field}"] = default_value
    st.session_state.pop(f"{prefix}_saved_job_id", None)
    st.session_state.pop(f"{prefix}_duplicate_matches", None)
    st.session_state.pop(f"{prefix}_duplicate_request", None)
    st.session_state.pop(f"{prefix}_duplicate_override", None)


def _find_duplicates(review, exclude_job_id=None):
    return find_possible_duplicates(review, exclude_job_id=exclude_job_id)


def _handle_generation_request(prefix, review, analysis, status_label):
    matches = _find_duplicates(
        review,
        exclude_job_id=st.session_state.get(f"{prefix}_saved_job_id"),
    )
    if matches and not st.session_state.get(f"{prefix}_duplicate_override"):
        st.session_state[f"{prefix}_duplicate_matches"] = matches
        st.session_state[f"{prefix}_duplicate_request"] = {
            "review": review,
            "analysis": analysis,
            "status_label": status_label,
        }
        return

    st.session_state.pop(f"{prefix}_duplicate_matches", None)
    st.session_state.pop(f"{prefix}_duplicate_request", None)
    st.session_state.pop(f"{prefix}_duplicate_override", None)

    job_id = persist_job(prefix, review, analysis)
    payload = build_generation_payload(review, analysis, job_id=job_id)
    start_cover_letter_generation(
        prefix,
        review,
        analysis,
        payload,
        job_id,
        status_label,
    )


def _render_duplicate_warning(prefix, clear_extracted=False):
    matches = st.session_state.get(f"{prefix}_duplicate_matches")
    pending = st.session_state.get(f"{prefix}_duplicate_request")
    if not matches or not pending:
        return

    st.warning("⚠️ Possible Duplicate Detected")
    st.dataframe(
        pd.DataFrame(matches)[["company", "position", "created_at", "source"]],
        hide_index=True,
        use_container_width=True,
    )
    proceed_col, cancel_col = st.columns(2)
    if proceed_col.button("✅ Proceed Anyway", key=f"{prefix}_proceed_duplicate", use_container_width=True):
        st.session_state[f"{prefix}_duplicate_override"] = True
        _handle_generation_request(
            prefix,
            pending["review"],
            pending["analysis"],
            pending["status_label"],
        )
    if cancel_col.button("❌ Cancel", key=f"{prefix}_cancel_duplicate", use_container_width=True):
        _reset_review_state(prefix)
        if clear_extracted:
            st.session_state.pop("extracted_paste_data", None)
            st.session_state["paste_raw_text"] = ""
        st.rerun()


def _extract_from_paste(raw_text):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        st.error("GEMINI_API_KEY is missing from your environment variables.")
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"""
    You are a data extraction assistant. Extract job posting information from the
    raw text below. The text may contain navigation menus, cookie notices, ads,
    footer links, and other noise — ignore all of that. Focus only on the actual
    job posting content.

    Return ONLY a valid JSON object with exactly these keys:
    - "company_name": string — the hiring company name
    - "position": string — the exact job title
    - "department": string — department or hiring manager name if mentioned, else ""
    - "language": string — "de" if job is in German, "en" if in English
    - "date_posted": string — posting date in YYYY-MM-DD format if found, else ""
    - "location": string — city and country if found, else ""
    - "platform": string — if URL or source platform is mentioned (linkedin/stepstone/indeed), else "other"
    - "jd_raw": string — the complete job description text, cleaned of navigation/footer noise

    Raw text:
    {raw_text}
    """

    response = model.generate_content(prompt)
    cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned_text)


def _show_confidence(extracted):
    fields = [
        extracted.get("company_name"),
        extracted.get("position"),
        extracted.get("jd_raw"),
        extracted.get("location"),
    ]
    score = sum(1 for field in fields if field)
    if score == 4:
        st.success("✅ High confidence extraction")
    elif score == 3:
        st.info("🟡 Medium confidence — review fields")
    else:
        st.warning("⚠️ Low confidence — manual review recommended")


seed_review_state("manual")
seed_review_state("paste")
if "paste_raw_text" not in st.session_state:
    st.session_state["paste_raw_text"] = ""

tab1, tab2, tab3 = st.tabs(["📋 Paste & Extract", "📸 Screenshot Upload", "✍️ Manual Entry"])

with tab1:
    raw_text = st.text_area(
        "Paste the full job ad text here (copied from browser, PDF, or email)",
        key="paste_raw_text",
        height=400,
        placeholder="Select all text from the job posting page and paste here...",
    )

    extract_col, clear_col = st.columns([1, 1])
    if extract_col.button("🤖 Extract with AI", type="primary", use_container_width=True):
        if not raw_text.strip():
            st.error("Paste the job text first.")
        else:
            with st.status("Gemini is extracting the job details..."):
                try:
                    extracted = _extract_from_paste(raw_text)
                    st.session_state["extracted_paste_data"] = extracted
                    seed_review_state("paste", extracted, overwrite=True)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not extract the pasted job text: {exc}")

    if clear_col.button("🔄 Clear & Paste Again", use_container_width=True):
        st.session_state.pop("extracted_paste_data", None)
        st.session_state["paste_raw_text"] = ""
        _reset_review_state("paste")
        st.rerun()

    extracted_paste_data = st.session_state.get("extracted_paste_data")
    if extracted_paste_data:
        _show_confidence(extracted_paste_data)
        paste_review, paste_analysis, paste_save_clicked, paste_generate_clicked = render_job_review_editor(
            "paste",
            "Extracted Job Detail — Review & Edit",
            generate_label="🚀 Send to Pipeline",
        )

        if paste_save_clicked:
            job_id = persist_job("paste", paste_review, paste_analysis)
            if job_id:
                st.success(f"Job saved with id {job_id}.")

        if paste_generate_clicked:
            _handle_generation_request("paste", paste_review, paste_analysis, "Initializing n8n pipeline...")

        render_uploaded_application_panel("paste", paste_review, paste_analysis)
        _render_duplicate_warning("paste", clear_extracted=True)

with tab2:
    render_screenshot_upload_tab()

with tab3:
    review, analysis, save_clicked, generate_clicked = render_job_review_editor(
        "manual",
        "Job Detail — Review & Edit",
    )

    if save_clicked:
        job_id = persist_job("manual", review, analysis)
        if job_id:
            st.success(f"Job saved with id {job_id}.")

    if generate_clicked:
        _handle_generation_request("manual", review, analysis, "Initializing n8n pipeline...")

    render_uploaded_application_panel("manual", review, analysis)
    _render_duplicate_warning("manual")

st.divider()
poll_cover_letter_completion("manual")
render_generated_cover_letter("manual")
poll_cover_letter_completion("upload")
render_generated_cover_letter("upload")
poll_cover_letter_completion("paste")
render_generated_cover_letter("paste")
