import os
from datetime import datetime

import streamlit as st

from application_status import job_status_for_application, normalize_application_status
from db import execute, execute_returning, fetch_one
from job_review import persist_job
from local_store import build_job_folder, sync_application_bundle


UPLOAD_STATUS_OPTIONS = ["pending", "applied"]


def _safe_slug(value):
    cleaned = "".join(char if char.isalnum() else "_" for char in (value or "").strip())
    return cleaned.strip("_") or "document"


def _save_uploaded_pdf(uploaded_file, subfolder, company_name, position, suffix):
    if not uploaded_file:
        return None

    target_dir = os.path.join("/files", subfolder)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{_safe_slug(company_name)}_{_safe_slug(position)}_{suffix}.pdf"
    target_path = os.path.join(target_dir, filename)
    with open(target_path, "wb") as handle:
        handle.write(uploaded_file.getbuffer())
    return target_path


def _latest_application(job_id):
    return fetch_one(
        """
        SELECT *
        FROM applications
        WHERE source_job_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (job_id,),
    )


def save_uploaded_application(prefix, review, analysis, status, notes, uploaded_cover_letter, uploaded_resume=None):
    if uploaded_cover_letter is None:
        st.error("Upload the cover letter PDF first.")
        return None

    job_id = persist_job(prefix, review, analysis)
    if not job_id:
        return None

    existing = _latest_application(job_id)
    normalized_status = normalize_application_status(status)
    cover_letter_path = _save_uploaded_pdf(
        uploaded_cover_letter,
        "uploaded_cover_letters",
        review["company_name"],
        review["position"],
        "cover_letter",
    )
    resume_path = existing.get("resume_pdf_path") if existing else None
    if uploaded_resume is not None:
        resume_path = _save_uploaded_pdf(
            uploaded_resume,
            "resumes",
            review["company_name"],
            review["position"],
            "resume",
        )

    params = (
        review["company_name"],
        review["position"],
        review["language"],
        review["jd_raw"],
        analysis["summary"] or None,
        analysis["required_skills"] or None,
        cover_letter_path,
        normalized_status,
        notes.strip() or None,
        review.get("platform") or None,
        resume_path,
        job_id,
    )

    if existing:
        row = execute_returning(
            """
            UPDATE applications
            SET company = %s,
                position = %s,
                language = %s,
                jd_raw = %s,
                jd_summary = %s,
                keywords = %s,
                cl_pdf_path = %s,
                status = %s,
                notes = %s,
                platform = %s,
                resume_pdf_path = %s,
                source_job_id = %s,
                cover_letter_id = NULL
            WHERE id = %s
            RETURNING id
            """,
            params + (existing["id"],),
        )
        application_id = row["id"] if row else None
        local_folder = existing.get("local_folder_path")
    else:
        row = execute_returning(
            """
            INSERT INTO applications (
                company,
                position,
                language,
                jd_raw,
                jd_summary,
                keywords,
                cl_pdf_path,
                status,
                notes,
                platform,
                resume_pdf_path,
                source_job_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            params,
        )
        application_id = row["id"] if row else None
        local_folder = None

    if not application_id:
        return None

    job_folder = fetch_one("SELECT local_folder_path FROM jobs WHERE id = %s", (job_id,))
    root_folder = job_folder.get("local_folder_path") if job_folder else None
    if not root_folder:
        root_folder = build_job_folder(job_id, review["company_name"], review["position"])

    application_folder, copied_cover_letter, copied_resume = sync_application_bundle(
        root_folder,
        application_id,
        {
            "company": review["company_name"],
            "position": review["position"],
            "language": review["language"],
            "status": normalized_status,
            "notes": notes.strip() or None,
            "source_job_id": job_id,
        },
        cover_letter_pdf_path=cover_letter_path,
        resume_pdf_path=resume_path,
    )
    execute(
        """
        UPDATE applications
        SET local_folder_path = %s,
            cl_pdf_path = %s,
            resume_pdf_path = %s
        WHERE id = %s
        """,
        (
            application_folder or local_folder,
            copied_cover_letter or cover_letter_path,
            copied_resume or resume_path,
            application_id,
        ),
    )
    execute(
        """
        UPDATE jobs
        SET application_id = %s,
            status = %s
        WHERE id = %s
        """,
        (application_id, job_status_for_application(normalized_status), job_id),
    )
    st.session_state[f"{prefix}_saved_job_id"] = job_id
    return application_id


def render_uploaded_application_panel(prefix, review, analysis):
    with st.expander("Upload Existing Documents Instead of Using the Pipeline"):
        status = st.selectbox(
            "Status for this saved application",
            UPLOAD_STATUS_OPTIONS,
            key=f"{prefix}_upload_status",
        )
        notes = st.text_area(
            "Notes",
            key=f"{prefix}_upload_notes",
            height=100,
            placeholder="Add notes about follow-ups, recruiter names, or what still needs to be done.",
        )
        cover_letter = st.file_uploader(
            "Cover Letter PDF *",
            type=["pdf"],
            key=f"{prefix}_uploaded_cover_letter",
        )
        resume = st.file_uploader(
            "Resume PDF (optional)",
            type=["pdf"],
            key=f"{prefix}_uploaded_resume",
        )

        if st.button("Save Uploaded Application", key=f"{prefix}_save_uploaded_application", use_container_width=True):
            application_id = save_uploaded_application(
                prefix,
                review,
                analysis,
                status,
                notes,
                cover_letter,
                resume,
            )
            if application_id:
                label = "Applied job" if normalize_application_status(status) == "applied" else "Pending application"
                st.success(f"{label} saved with id {application_id}.")
