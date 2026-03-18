import streamlit as st

from application_status import format_application_status, job_status_for_application, normalize_application_status
from db import execute, execute_returning, fetch_one
from job_review import persist_job
from local_store import build_job_folder, save_uploaded_file, save_uploaded_files, sync_application_bundle


UPLOAD_STATUS_OPTIONS = ["pending", "applied"]


def _application_by_id(application_id):
    if not application_id:
        return None
    return fetch_one("SELECT * FROM applications WHERE id = %s", (application_id,))


def _editable_application(job_id, prefix):
    bound_application = _application_by_id(st.session_state.get(f"{prefix}_saved_application_id"))
    if bound_application and bound_application.get("source_job_id") == job_id:
        return bound_application

    linked_application = fetch_one(
        """
        SELECT a.*
        FROM jobs j
        JOIN applications a ON a.id = j.application_id
        WHERE j.id = %s
        """,
        (job_id,),
    )
    if linked_application and normalize_application_status(linked_application.get("status")) == "pending":
        return linked_application

    return None


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


def save_uploaded_application(
    prefix,
    review,
    analysis,
    status,
    notes,
    uploaded_cover_letter,
    uploaded_resume=None,
    uploaded_attachments=None,
):
    if uploaded_cover_letter is None:
        st.error("Upload the cover letter PDF first.")
        return None

    job_id = persist_job(prefix, review, analysis)
    if not job_id:
        return None

    existing = _editable_application(job_id, prefix)
    normalized_status = normalize_application_status(status)
    cover_letter_path = save_uploaded_file(
        uploaded_cover_letter,
        "uploaded_cover_letters",
        review["company_name"],
        review["position"],
        "cover_letter",
    )
    resume_path = existing.get("resume_pdf_path") if existing else None
    attachment_paths = list(existing.get("extra_file_paths") or []) if existing else []
    if uploaded_resume is not None:
        resume_path = save_uploaded_file(
            uploaded_resume,
            "resumes",
            review["company_name"],
            review["position"],
            "resume",
        )
    attachment_paths.extend(
        save_uploaded_files(
            uploaded_attachments,
            "application_attachments",
            review["company_name"],
            review["position"],
        )
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
        attachment_paths or None,
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
                extra_file_paths = %s,
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
                extra_file_paths,
                source_job_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    application_folder, copied_cover_letter, copied_resume, copied_attachments = sync_application_bundle(
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
        attachment_paths=attachment_paths,
    )
    execute(
        """
        UPDATE applications
        SET local_folder_path = %s,
            cl_pdf_path = %s,
            resume_pdf_path = %s
            , extra_file_paths = %s
        WHERE id = %s
        """,
        (
            application_folder or local_folder,
            copied_cover_letter or cover_letter_path,
            copied_resume or resume_path,
            copied_attachments or attachment_paths or None,
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
    st.session_state[f"{prefix}_saved_application_id"] = application_id
    return application_id


def render_uploaded_application_panel(prefix, review, analysis):
    with st.expander("Upload Existing Documents Instead of Using the Pipeline"):
        status = st.selectbox(
            "Status for this saved application",
            UPLOAD_STATUS_OPTIONS,
            key=f"{prefix}_upload_status",
            format_func=format_application_status,
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
        attachments = st.file_uploader(
            "Extra Files (optional)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"{prefix}_uploaded_attachments",
            help="Upload certificates, transcripts, portfolios, or screenshots.",
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
                attachments,
            )
            if application_id:
                label = "Applied Job" if normalize_application_status(status) == "applied" else "Pending Application"
                st.success(f"{label} saved with id {application_id}.")
