import io
import json
import os

import google.generativeai as genai
import pandas as pd
import streamlit as st
from PIL import Image

from duplicate_detection import find_possible_duplicates
from job_review import (
    build_generation_payload,
    clear_saved_job_binding,
    persist_job,
    render_job_review_editor,
    seed_review_state,
)
from post_generation import start_cover_letter_generation
from uploaded_application import render_uploaded_application_panel


def extract_job_details(uploaded_files):
    prompt = """
    Analyze these screenshots of a job posting. They may be out of order.
    Extract the information into a valid JSON object with EXACTLY these keys:
    - "company_name": The hiring company.
    - "position": The exact job title.
    - "location": Job location if shown.
    - "salary": Salary or compensation if shown.
    - "posted_date": Posting date if shown, keep the source format.
    - "platform": Platform or source of the posting, like LinkedIn or StepStone.
    - "job_url": The job URL only if clearly visible.
    - "department": Hiring manager name, team, or department only if clearly visible.
    - "jd_raw": The complete combined job description with responsibilities, requirements, qualifications, and company context.

    Use an empty string for any field you cannot find with confidence.
    Respond ONLY with the raw JSON object. Do not include markdown or commentary.
    """

    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            st.error("Configure GEMINI_API_KEY in .env for the extraction features.")
            return None

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        images = []
        for file_handle in uploaded_files:
            image = Image.open(io.BytesIO(file_handle.getvalue()))
            images.append(image)

        response = model.generate_content([prompt, *images])
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except Exception as exc:
        st.error(f"Failed to extract text using Gemini: {exc}")
        return None


def _find_duplicates(review):
    return find_possible_duplicates(
        review,
        exclude_job_id=st.session_state.get("upload_saved_job_id"),
    )


def _handle_generation_request(review, analysis):
    matches = _find_duplicates(review)
    if matches and not st.session_state.get("upload_duplicate_override"):
        st.session_state["upload_duplicate_matches"] = matches
        st.session_state["upload_duplicate_request"] = {
            "review": review,
            "analysis": analysis,
        }
        return

    st.session_state.pop("upload_duplicate_matches", None)
    st.session_state.pop("upload_duplicate_request", None)
    st.session_state.pop("upload_duplicate_override", None)

    job_id = persist_job("upload", review, analysis)
    payload = build_generation_payload(review, analysis, job_id=job_id)
    start_cover_letter_generation(
        "upload",
        review,
        analysis,
        payload,
        job_id,
        "Starting n8n pipeline...",
    )


def _render_duplicate_warning():
    matches = st.session_state.get("upload_duplicate_matches")
    pending = st.session_state.get("upload_duplicate_request")
    if not matches or not pending:
        return

    st.warning("⚠️ Possible Duplicate Detected")
    st.dataframe(
        pd.DataFrame(matches)[["company", "position", "created_at", "source"]],
        hide_index=True,
        use_container_width=True,
    )
    proceed_col, cancel_col = st.columns(2)
    if proceed_col.button("✅ Proceed Anyway", key="upload_proceed_duplicate", use_container_width=True):
        st.session_state["upload_duplicate_override"] = True
        _handle_generation_request(pending["review"], pending["analysis"])
    if cancel_col.button("❌ Cancel", key="upload_cancel_duplicate", use_container_width=True):
        st.session_state.pop("upload_duplicate_matches", None)
        st.session_state.pop("upload_duplicate_request", None)
        st.rerun()


def render_screenshot_upload_tab():
    uploaded_files = st.file_uploader(
        "Upload screenshots of the job posting",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="upload_tab_file_uploader",
    )

    if "extracted_data" not in st.session_state:
        st.session_state["extracted_data"] = None

    if uploaded_files:
        st.session_state["upload_screenshot_payloads"] = [
            {"name": file_handle.name, "bytes": file_handle.getvalue()}
            for file_handle in uploaded_files
        ]
        st.write(f"**{len(uploaded_files)} image(s) uploaded**")
        preview_cols = st.columns(min(len(uploaded_files), 4))
        for index, file_handle in enumerate(uploaded_files[:4]):
            preview_cols[index].image(
                file_handle,
                caption=f"Screenshot {index + 1}",
                use_container_width=True,
            )

        if st.button("Extract Job Details with Gemini", key="upload_extract_button", type="primary"):
            with st.spinner("Gemini is reading your screenshots..."):
                result = extract_job_details(uploaded_files)
                if result:
                    st.session_state["extracted_data"] = result
                    clear_saved_job_binding("upload", clear_application=True)
                    seed_review_state("upload", result, overwrite=True)
                    st.rerun()

    if st.session_state.get("extracted_data"):
        review, analysis, save_clicked, generate_clicked = render_job_review_editor(
            "upload",
            "Job Detail — Review & Edit",
        )

        if save_clicked:
            job_id = persist_job("upload", review, analysis)
            if job_id:
                st.success(f"Job saved with id {job_id}.")

        if generate_clicked:
            _handle_generation_request(review, analysis)
        render_uploaded_application_panel("upload", review, analysis)
        _render_duplicate_warning()
    else:
        st.info("Upload screenshots and extract the posting to review the job details here.")
