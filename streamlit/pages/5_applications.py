import base64
import os
import shutil
from datetime import datetime

import streamlit as st

from application_status import (
    APPLICATION_STATUS_OPTIONS,
    is_pending_status,
    job_status_for_application,
    normalize_application_status,
)
from components import show_address_confirmation_card
from db import execute, execute_returning, fetch_all, fetch_one
from job_review import analyze_job_fit, build_embedding_text, seed_review_state
from local_store import build_job_folder, safe_slug, sync_application_bundle, sync_job_bundle
from semantic_search import embed_text, vector_literal
from ui import apply_ui_theme


st.set_page_config(page_title="Applications", layout="wide")
apply_ui_theme()
st.title("📂 Application Pipeline")

with st.sidebar:
    show_address_confirmation_card()


def _format_date(value):
    return value.strftime("%d %b %Y") if value else "n/a"


def _date_input_value(value):
    return value.strftime("%Y-%m-%d") if value else ""


def _parse_date_input(value):
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _bounded_score(value):
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(round(numeric, 1), 100))


def _normalize_file_path(value):
    if not value:
        return None
    if value.startswith("/files/"):
        return value
    return os.path.join("/files", os.path.basename(value))


def _read_file_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


def _preview_pdf(path, height=520):
    file_bytes = _read_file_bytes(path)
    if not file_bytes:
        st.error("PDF file not found on disk.")
        return

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    st.markdown(
        f"""
        <iframe src="data:application/pdf;base64,{b64}"
            width="100%" height="{height}px"
            style="border:1px solid #333; border-radius:8px;">
        </iframe>
        """,
        unsafe_allow_html=True,
    )


def _storage_files(folder_path):
    if not folder_path or not os.path.isdir(folder_path):
        return []

    collected = []
    for root, _, files in os.walk(folder_path):
        for file_name in files:
            full_path = os.path.join(root, file_name)
            collected.append(os.path.relpath(full_path, folder_path))
    return sorted(collected)


def _scroll_container(height=320):
    try:
        return st.container(border=True, height=height)
    except TypeError:
        return st.container(border=True)


def _detail_key():
    return "pipeline_selected_detail"


def _open_detail(record_type, record_id):
    st.session_state[_detail_key()] = {"type": record_type, "id": record_id}


def _close_detail():
    detail = st.session_state.get(_detail_key())
    if detail:
        suffix = f"{detail['type']}_{detail['id']}"
        st.session_state.pop(f"show_cover_letter_{suffix}", None)
        st.session_state.pop(f"show_resume_{suffix}", None)
    st.session_state.pop(_detail_key(), None)


def _pipeline_status_sql(job_alias="j", application_alias="latest_app"):
    return f"""
        CASE
            WHEN LOWER(COALESCE({application_alias}.status, '')) IN ('drafted', 'pending', 'application_saved') THEN 'pending'
            WHEN LOWER(COALESCE({application_alias}.status, '')) = ''
                 AND LOWER(COALESCE({job_alias}.status, '')) IN ('', 'new', 'drafted', 'pending', 'application_saved') THEN 'pending'
            WHEN LOWER(COALESCE({application_alias}.status, '')) <> '' THEN LOWER({application_alias}.status)
            ELSE LOWER(COALESCE({job_alias}.status, 'pending'))
        END
    """


def _job_query_columns(job_alias="j", application_alias="latest_app"):
    return f"""
        {job_alias}.id,
        {job_alias}.title,
        {job_alias}.company,
        {job_alias}.location,
        {job_alias}.platform,
        {job_alias}.job_url,
        {job_alias}.jd_summary,
        {job_alias}.jd_raw,
        {job_alias}.keywords,
        {job_alias}.salary,
        {job_alias}.match_score,
        {job_alias}.posted_date,
        {job_alias}.language_pref,
        {job_alias}.status,
        {job_alias}.application_id,
        {job_alias}.screenshot_paths,
        {job_alias}.local_folder_path,
        {job_alias}.created_at,
        {application_alias}.id AS latest_application_id,
        {application_alias}.status AS linked_application_status,
        {_pipeline_status_sql(job_alias, application_alias)} AS pipeline_status
    """


def _search_jobs(query, semantic_enabled):
    job_base = f"""
        FROM jobs j
        LEFT JOIN LATERAL (
            SELECT id, status
            FROM applications a
            WHERE a.source_job_id = j.id
            ORDER BY a.created_at DESC
            LIMIT 1
        ) latest_app ON TRUE
        WHERE {_pipeline_status_sql('j', 'latest_app')} = 'pending'
    """

    if not query:
        return fetch_all(
            f"""
            SELECT
                {_job_query_columns('j', 'latest_app')},
                NULL::numeric AS semantic_score
            {job_base}
            ORDER BY COALESCE(j.match_score, 0) DESC, j.created_at DESC
            LIMIT 25
            """
        )

    if semantic_enabled:
        embedding = embed_text(query, task_type="retrieval_query", title="Job search")
        vector = vector_literal(embedding)
        if vector:
            semantic_rows = fetch_all(
                f"""
                SELECT
                    {_job_query_columns('j', 'latest_app')},
                    ROUND(((1 - (j.jd_embedding <=> %s::vector)) * 100)::numeric, 1) AS semantic_score
                {job_base}
                  AND j.jd_embedding IS NOT NULL
                ORDER BY j.jd_embedding <=> %s::vector
                LIMIT 25
                """,
                (vector, vector),
            )
            if semantic_rows:
                return semantic_rows

    like = f"%{query}%"
    return fetch_all(
        f"""
        SELECT
            {_job_query_columns('j', 'latest_app')},
            NULL::numeric AS semantic_score
        {job_base}
          AND (
                j.company ILIKE %s
                OR j.title ILIKE %s
                OR COALESCE(j.jd_summary, '') ILIKE %s
                OR COALESCE(j.jd_raw, '') ILIKE %s
              )
        ORDER BY COALESCE(j.match_score, 0) DESC, j.created_at DESC
        LIMIT 25
        """,
        (like, like, like, like),
    )


def _search_applications(query):
    base_query = """
        SELECT
            a.*,
            j.location,
            j.platform,
            j.job_url,
            j.posted_date,
            j.language_pref AS job_language,
            j.match_score AS job_match_score,
            j.screenshot_paths,
            j.local_folder_path AS job_local_folder_path
        FROM applications a
        LEFT JOIN jobs j ON j.id = a.source_job_id
    """
    if not query:
        return fetch_all(
            base_query
            + """
            WHERE LOWER(COALESCE(a.status, 'pending')) NOT IN ('drafted', 'pending', 'application_saved')
            ORDER BY a.created_at DESC
            LIMIT 25
            """
        )

    like = f"%{query}%"
    return fetch_all(
        base_query
        + """
        WHERE LOWER(COALESCE(a.status, 'pending')) NOT IN ('drafted', 'pending', 'application_saved')
          AND (
                a.company ILIKE %s
                OR a.position ILIKE %s
                OR COALESCE(a.notes, '') ILIKE %s
                OR COALESCE(a.jd_summary, '') ILIKE %s
              )
        ORDER BY a.created_at DESC
        LIMIT 25
        """,
        (like, like, like, like),
    )


def _render_keywords(label, values):
    if values:
        st.caption(f"{label}: {', '.join(values)}")


def _latest_cover_letter(company, cover_letter_id=None):
    if cover_letter_id:
        letter = fetch_one("SELECT * FROM cover_letters WHERE id = %s", (cover_letter_id,))
        if letter:
            return letter

    return fetch_one(
        """
        SELECT *
        FROM cover_letters
        WHERE company = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (company,),
    )


def _latest_application_for_job(job_id):
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


def _load_job(job_id):
    return fetch_one(
        f"""
        SELECT
            {_job_query_columns('j', 'latest_app')}
        FROM jobs j
        LEFT JOIN LATERAL (
            SELECT id, status
            FROM applications a
            WHERE a.source_job_id = j.id
            ORDER BY a.created_at DESC
            LIMIT 1
        ) latest_app ON TRUE
        WHERE j.id = %s
        """,
        (job_id,),
    )


def _load_application(application_id):
    return fetch_one(
        """
        SELECT
            a.*,
            j.location,
            j.platform,
            j.job_url,
            j.posted_date,
            j.language_pref AS job_language,
            j.match_score AS job_match_score,
            j.screenshot_paths,
            j.local_folder_path AS job_local_folder_path
        FROM applications a
        LEFT JOIN jobs j ON j.id = a.source_job_id
        WHERE a.id = %s
        """,
        (application_id,),
    )


def _save_uploaded_pdf(uploaded_file, subfolder, company, position, suffix):
    if not uploaded_file:
        return None

    target_dir = os.path.join("/files", subfolder)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_slug(company)}_{safe_slug(position)}_{suffix}.pdf"
    target_path = os.path.join(target_dir, filename)

    with open(target_path, "wb") as handle:
        handle.write(uploaded_file.getbuffer())

    return target_path


def _job_folder_path(job):
    folder_path = job.get("local_folder_path")
    if folder_path:
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    folder_path = build_job_folder(job["id"], job.get("company"), job.get("title"))
    os.makedirs(folder_path, exist_ok=True)
    execute("UPDATE jobs SET local_folder_path = %s WHERE id = %s", (folder_path, job["id"]))
    return folder_path


def _sync_application_files(job, application_id, metadata, cover_letter_pdf_path=None, resume_pdf_path=None, latex_source=None):
    application_folder, copied_cover_letter, copied_resume = sync_application_bundle(
        _job_folder_path(job),
        application_id,
        metadata,
        cover_letter_pdf_path=cover_letter_pdf_path,
        resume_pdf_path=resume_pdf_path,
        latex_source=latex_source,
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
            application_folder,
            copied_cover_letter or cover_letter_pdf_path,
            copied_resume or resume_pdf_path,
            application_id,
        ),
    )


def _ensure_job_application(job):
    existing = _latest_application_for_job(job["id"])
    if existing:
        return existing

    row = execute_returning(
        """
        INSERT INTO applications (
            company,
            position,
            language,
            jd_raw,
            jd_summary,
            keywords,
            status,
            source_job_id,
            platform
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            job.get("company"),
            job.get("title"),
            job.get("language_pref") or "de",
            job.get("jd_raw") or "",
            job.get("jd_summary") or None,
            job.get("keywords") or None,
            "pending",
            job["id"],
            job.get("platform") or None,
        ),
    )
    if not row:
        return None

    execute(
        "UPDATE jobs SET application_id = %s, status = 'pending' WHERE id = %s",
        (row["id"], job["id"]),
    )
    return _load_application(row["id"])


def _remove_linked_file(path):
    normalized = _normalize_file_path(path)
    if not normalized:
        return

    removable_roots = (
        "/files/uploaded_cover_letters",
        "/files/resumes",
        "/files/job_records",
    )
    if normalized.startswith(removable_roots) and os.path.exists(normalized):
        try:
            os.remove(normalized)
        except OSError:
            pass


def _open_regeneration(job):
    review = {
        "company_name": job.get("company") or "",
        "position": job.get("title") or "",
        "location": job.get("location") or "",
        "salary": job.get("salary") or "",
        "posted_date": _date_input_value(job.get("posted_date")),
        "platform": job.get("platform") or "",
        "job_url": job.get("job_url") or "",
        "language": job.get("language_pref") or "de",
        "department": "",
        "jd_raw": job.get("jd_raw") or "",
    }
    seed_review_state("manual", review, overwrite=True)
    st.session_state["manual_saved_job_id"] = job["id"]
    st.session_state["new_application_notice"] = (
        f"Loaded {job.get('company') or 'this company'} / {job.get('title') or 'this role'} into Manual Entry."
    )
    if hasattr(st, "switch_page"):
        st.switch_page("pages/1_new_application.py")


def _pending_application_controls(job):
    application = _latest_application_for_job(job["id"])
    current_status = normalize_application_status(application.get("status") if application else "pending")
    editable_statuses = ["pending", "applied"]
    status_index = (
        editable_statuses.index(current_status)
        if current_status in editable_statuses
        else 0
    )

    st.markdown("#### Pending Application Details")
    status = st.selectbox(
        "Status",
        editable_statuses,
        index=status_index,
        key=f"job_status_select_{job['id']}",
    )
    notes = st.text_area(
        "Application Notes",
        value=(application.get("notes") or "") if application else "",
        height=120,
        key=f"job_notes_{job['id']}",
    )
    resume_upload = st.file_uploader(
        "Upload Resume PDF",
        type=["pdf"],
        key=f"job_resume_upload_{job['id']}",
    )
    cover_upload = st.file_uploader(
        "Upload Cover Letter PDF",
        type=["pdf"],
        key=f"job_cover_upload_{job['id']}",
    )

    action_col1, action_col2 = st.columns(2)
    if action_col1.button("Save Pending Details", key=f"save_pending_details_{job['id']}", type="primary"):
        if not application:
            application = _ensure_job_application(job)
        if not application:
            st.error("Could not prepare the pending application record for this job.")
            return

        resume_path = _normalize_file_path(application.get("resume_pdf_path"))
        cover_letter_path = _normalize_file_path(application.get("cl_pdf_path"))
        cover_letter_id = application.get("cover_letter_id")

        if resume_upload is not None:
            resume_path = _save_uploaded_pdf(
                resume_upload,
                "resumes",
                job.get("company"),
                job.get("title"),
                "resume",
            )
        if cover_upload is not None:
            cover_letter_path = _save_uploaded_pdf(
                cover_upload,
                "uploaded_cover_letters",
                job.get("company"),
                job.get("title"),
                "cover_letter",
            )
            cover_letter_id = None

        normalized_status = normalize_application_status(status)
        execute(
            """
            UPDATE applications
            SET company = %s,
                position = %s,
                language = %s,
                jd_raw = %s,
                jd_summary = %s,
                keywords = %s,
                status = %s,
                notes = %s,
                platform = %s,
                resume_pdf_path = %s,
                cl_pdf_path = %s,
                cover_letter_id = %s
            WHERE id = %s
            """,
            (
                job.get("company"),
                job.get("title"),
                job.get("language_pref") or "de",
                job.get("jd_raw") or "",
                job.get("jd_summary") or None,
                job.get("keywords") or None,
                normalized_status,
                notes.strip() or None,
                job.get("platform") or None,
                resume_path,
                cover_letter_path,
                cover_letter_id,
                application["id"],
            ),
        )
        execute(
            """
            UPDATE jobs
            SET application_id = %s,
                status = %s
            WHERE id = %s
            """,
            (application["id"], job_status_for_application(normalized_status), job["id"]),
        )
        _sync_application_files(
            job,
            application["id"],
            {
                "company": job.get("company"),
                "position": job.get("title"),
                "language": job.get("language_pref") or "de",
                "status": normalized_status,
                "notes": notes.strip() or None,
                "source_job_id": job["id"],
            },
            cover_letter_pdf_path=cover_letter_path,
            resume_pdf_path=resume_path,
            latex_source=application.get("cl_text"),
        )
        st.success("Pending application details updated.")
        st.rerun()

    if action_col2.button("Regenerate Cover Letter", key=f"regenerate_cover_letter_{job['id']}", use_container_width=True):
        _open_regeneration(job)

    delete_col1, delete_col2 = st.columns(2)
    if delete_col1.button("Delete Cover Letter", key=f"delete_pending_cover_{job['id']}", use_container_width=True):
        if not application:
            st.info("There is no saved cover letter linked to this pending job yet.")
            return
        _remove_linked_file(application.get("cl_pdf_path"))
        application_folder = application.get("local_folder_path")
        if application_folder:
            local_cover = os.path.join(application_folder, "cover_letter.pdf")
            if os.path.exists(local_cover):
                os.remove(local_cover)
        execute(
            "UPDATE applications SET cl_pdf_path = NULL, cl_text = NULL, cover_letter_id = NULL WHERE id = %s",
            (application["id"],),
        )
        st.success("Cover letter removed from this pending application.")
        st.rerun()

    if delete_col2.button("Delete Resume", key=f"delete_pending_resume_{job['id']}", use_container_width=True):
        if not application:
            st.info("There is no saved resume linked to this pending job yet.")
            return
        _remove_linked_file(application.get("resume_pdf_path"))
        application_folder = application.get("local_folder_path")
        if application_folder:
            local_resume = os.path.join(application_folder, "resume.pdf")
            if os.path.exists(local_resume):
                os.remove(local_resume)
        execute(
            "UPDATE applications SET resume_pdf_path = NULL WHERE id = %s",
            (application["id"],),
        )
        st.success("Resume removed from this pending application.")
        st.rerun()


def _save_job_edit(job):
    with st.expander("Edit job", expanded=True):
        with st.form(f"edit_job_form_{job['id']}"):
            title = st.text_input("Job Title", value=job["title"] or "")
            company = st.text_input("Company", value=job["company"] or "")
            location = st.text_input("Location", value=job["location"] or "")
            platform = st.text_input("Platform", value=job["platform"] or "")
            language = st.selectbox(
                "Language",
                ["de", "en"],
                index=0 if (job.get("language_pref") or "de") == "de" else 1,
            )
            posted_date = st.text_input(
                "Posted Date",
                value=_date_input_value(job.get("posted_date")),
                placeholder="YYYY-MM-DD",
            )
            jd_raw = st.text_area("Job Description", value=job.get("jd_raw") or "", height=260)
            submitted = st.form_submit_button("Update Job", type="primary")

        if submitted:
            review = {
                "company_name": company,
                "position": title,
                "location": location,
                "salary": job.get("salary") or "",
                "posted_date": posted_date,
                "platform": platform,
                "job_url": job.get("job_url") or "",
                "language": language,
                "department": "",
                "jd_raw": jd_raw,
            }
            analysis = analyze_job_fit(review)
            embedding = embed_text(
                build_embedding_text(review, analysis),
                task_type="retrieval_document",
                title=f"{company} - {title}",
            )
            embedding_literal = vector_literal(embedding)

            execute(
                """
                UPDATE jobs
                SET title = %s,
                    company = %s,
                    location = %s,
                    platform = %s,
                    language_pref = %s,
                    posted_date = %s,
                    jd_raw = %s,
                    jd_summary = %s,
                    keywords = %s,
                    match_score = %s,
                    jd_embedding = %s::vector,
                    status = 'pending'
                WHERE id = %s
                """,
                (
                    title,
                    company,
                    location or None,
                    platform or None,
                    language,
                    _parse_date_input(posted_date),
                    jd_raw,
                    analysis["summary"] or None,
                    analysis["required_skills"] or None,
                    analysis["match_score"],
                    embedding_literal,
                    job["id"],
                ),
            )

            folder_path, screenshot_paths = sync_job_bundle(
                job["id"],
                review,
                analysis,
                existing_screenshot_paths=job.get("screenshot_paths"),
            )
            execute(
                """
                UPDATE jobs
                SET local_folder_path = %s,
                    screenshot_paths = %s
                WHERE id = %s
                """,
                (folder_path, screenshot_paths or None, job["id"]),
            )
            st.success("Job updated.")
            st.session_state.pop(f"edit_job_{job['id']}", None)
            st.rerun()

        _pending_application_controls(job)


def _delete_job_panel(job):
    st.warning("Deleting this job removes it from the saved job list and also clears any pending draft linked to it.")
    confirmed = st.checkbox("I understand and want to delete this job", key=f"confirm_delete_job_{job['id']}")
    if st.button("Delete Job Now", key=f"delete_job_now_{job['id']}", type="primary"):
        if not confirmed:
            st.error("Please confirm before deleting.")
            return

        try:
            linked_applications = fetch_all(
                "SELECT id, local_folder_path FROM applications WHERE source_job_id = %s",
                (job["id"],),
            )
            execute("UPDATE jobs SET application_id = NULL WHERE id = %s", (job["id"],))
            for application in linked_applications:
                execute("DELETE FROM notifications WHERE application_id = %s", (application["id"],))
                execute("DELETE FROM applications WHERE id = %s", (application["id"],))
                if application.get("local_folder_path") and os.path.isdir(application["local_folder_path"]):
                    shutil.rmtree(application["local_folder_path"], ignore_errors=True)
            execute("DELETE FROM notifications WHERE job_id = %s", (job["id"],))
            execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
            if job.get("local_folder_path") and os.path.isdir(job["local_folder_path"]):
                shutil.rmtree(job["local_folder_path"], ignore_errors=True)
            st.success("Job deleted.")
            st.session_state.pop(f"delete_job_{job['id']}", None)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not delete this job yet: {exc}")


def _save_application_edit(application):
    with st.expander("Edit application", expanded=True):
        with st.form(f"edit_application_form_{application['id']}"):
            company = st.text_input("Company", value=application["company"] or "")
            position = st.text_input("Position", value=application["position"] or "")
            language = st.selectbox(
                "Language",
                ["de", "en"],
                index=0 if (application.get("language") or "de") == "de" else 1,
            )
            current_status = normalize_application_status(application.get("status"))
            status = st.selectbox(
                "Status",
                APPLICATION_STATUS_OPTIONS,
                index=APPLICATION_STATUS_OPTIONS.index(current_status)
                if current_status in APPLICATION_STATUS_OPTIONS
                else 0,
            )
            notes = st.text_area("Notes", value=application.get("notes") or "", height=140)
            jd_raw = st.text_area("Job Description", value=application.get("jd_raw") or "", height=220)
            submitted = st.form_submit_button("Update Application", type="primary")

        if submitted:
            normalized_status = normalize_application_status(status)
            execute(
                """
                UPDATE applications
                SET company = %s,
                    position = %s,
                    language = %s,
                    status = %s,
                    notes = %s,
                    jd_raw = %s
                WHERE id = %s
                """,
                (
                    company,
                    position,
                    language,
                    normalized_status,
                    notes or None,
                    jd_raw,
                    application["id"],
                ),
            )
            if application.get("source_job_id"):
                execute(
                    """
                    UPDATE jobs
                    SET application_id = %s,
                        status = %s
                    WHERE id = %s
                    """,
                    (
                        application["id"],
                        job_status_for_application(normalized_status),
                        application["source_job_id"],
                    ),
                )
            folder_root = application.get("job_local_folder_path")
            if not folder_root and application.get("local_folder_path"):
                folder_root = os.path.dirname(application["local_folder_path"])
            if folder_root:
                sync_application_bundle(
                    folder_root,
                    application["id"],
                    {
                        "company": company,
                        "position": position,
                        "language": language,
                        "status": normalized_status,
                        "notes": notes or None,
                    },
                    cover_letter_pdf_path=_normalize_file_path(application.get("cl_pdf_path")),
                    resume_pdf_path=_normalize_file_path(application.get("resume_pdf_path")),
                    latex_source=application.get("cl_text"),
                )
            st.success("Application updated.")
            st.session_state.pop(f"edit_application_{application['id']}", None)
            st.rerun()


def _delete_application_panel(application):
    st.warning("Deleting this application removes the saved cover-letter/resume link for this job.")
    confirmed = st.checkbox(
        "I understand and want to delete this application",
        key=f"confirm_delete_application_{application['id']}",
    )
    if st.button(
        "Delete Application Now",
        key=f"delete_application_now_{application['id']}",
        type="primary",
    ):
        if not confirmed:
            st.error("Please confirm before deleting.")
            return

        execute("UPDATE jobs SET application_id = NULL WHERE application_id = %s", (application["id"],))
        if application.get("source_job_id"):
            execute(
                "UPDATE jobs SET status = 'pending' WHERE id = %s",
                (application["source_job_id"],),
            )
        execute("DELETE FROM notifications WHERE application_id = %s", (application["id"],))
        execute("DELETE FROM applications WHERE id = %s", (application["id"],))
        if application.get("local_folder_path") and os.path.isdir(application["local_folder_path"]):
            shutil.rmtree(application["local_folder_path"], ignore_errors=True)
        st.success("Application deleted.")
        st.session_state.pop(f"delete_application_{application['id']}", None)
        st.rerun()


if hasattr(st, "dialog"):

    @st.dialog("Full Details")
    def _detail_dialog():
        detail = st.session_state.get(_detail_key())
        if not detail:
            st.info("No job selected.")
            return

        record_type = detail["type"]
        record_id = detail["id"]
        suffix = f"{record_type}_{record_id}"

        if record_type == "job":
            job = _load_job(record_id)
            application = _latest_application_for_job(record_id) if job else None
            cover_letter = _latest_cover_letter(job["company"], application["cover_letter_id"] if application else None) if job else None
            resume_path = _normalize_file_path(application.get("resume_pdf_path")) if application else None
            folder_path = job.get("local_folder_path") if job else None
            screenshot_paths = job.get("screenshot_paths") if job else []
            title = job["title"] if job else "Unknown job"
            company = job["company"] if job else "Unknown company"
            location = job.get("location") if job else None
            platform = job.get("platform") if job else None
            language = job.get("language_pref") if job else None
            posted_date = job.get("posted_date") if job else None
            match_score = job.get("match_score") if job else None
            jd_raw = job.get("jd_raw") if job else ""
        else:
            application = _load_application(record_id)
            cover_letter = _latest_cover_letter(
                application["company"],
                application.get("cover_letter_id"),
            ) if application else None
            resume_path = _normalize_file_path(application.get("resume_pdf_path")) if application else None
            folder_path = (
                application.get("local_folder_path") or application.get("job_local_folder_path")
            ) if application else None
            screenshot_paths = application.get("screenshot_paths") if application else []
            title = application["position"] if application else "Unknown application"
            company = application["company"] if application else "Unknown company"
            location = application.get("location") if application else None
            platform = application.get("platform") if application else None
            language = (
                application.get("language") or application.get("job_language")
            ) if application else None
            posted_date = application.get("posted_date") if application else None
            match_score = application.get("job_match_score") if application else None
            jd_raw = application.get("jd_raw") if application else ""

        if not (job if record_type == "job" else application):
            st.error("The selected record no longer exists.")
            if st.button("Close"):
                _close_detail()
                st.rerun()
            return

        detail_review = {
            "company_name": company or "",
            "position": title or "",
            "location": location or "",
            "salary": "",
            "posted_date": _date_input_value(posted_date),
            "platform": platform or "",
            "job_url": "",
            "language": language or "de",
            "department": "",
            "jd_raw": jd_raw or "",
        }
        detail_analysis = analyze_job_fit(detail_review)
        if match_score is None:
            match_score = detail_analysis["match_score"]

        meta_col1, meta_col2, meta_col3 = st.columns(3)
        meta_col1.metric("Company", company or "n/a")
        meta_col2.metric("Match Score", f"{_bounded_score(match_score)}%")
        meta_col3.metric("Date", _format_date(posted_date))

        st.markdown(f"### {title}")
        st.caption(" | ".join(bit for bit in [location, platform, language] if bit))

        detail_col1, detail_col2 = st.columns([2, 1])
        with detail_col1:
            st.text_area(
                "Complete Job Description",
                value=jd_raw or "",
                height=320,
                disabled=True,
            )

        with detail_col2:
            st.caption("Local Storage Folder")
            st.code(folder_path or "Not stored locally yet")
            stored_files = _storage_files(folder_path)
            if stored_files:
                st.caption("Stored Files")
                st.code("\n".join(stored_files))

        if screenshot_paths:
            st.markdown("#### Screenshots")
            with _scroll_container(340):
                for image_path in screenshot_paths:
                    normalized = _normalize_file_path(image_path)
                    if normalized and os.path.exists(normalized):
                        st.image(normalized, use_container_width=True)

        st.markdown("#### Skill Snapshot")
        skill_col1, skill_col2 = st.columns(2)
        with skill_col1:
            st.caption("Matching Skills")
            st.write(", ".join(detail_analysis["matching_skills"]) or "None detected yet")
        with skill_col2:
            st.caption("Missing Skills")
            st.write(", ".join(detail_analysis["missing_skills"]) or "None detected yet")

        if cover_letter:
            st.markdown("#### Cover Letter")
            letter_pdf_path = _normalize_file_path(cover_letter.get("pdf_filename"))
            if letter_pdf_path and not letter_pdf_path.endswith(".pdf"):
                letter_pdf_path = os.path.join("/files", cover_letter["pdf_filename"])

            action_col1, action_col2, action_col3 = st.columns(3)
            action_col1.metric("Score", f"{_bounded_score(cover_letter.get('score'))}/100")
            action_col2.metric("Iterations", cover_letter.get("iterations", 1))
            if action_col3.button("View Cover Letter", key=f"view_cover_letter_{suffix}", use_container_width=True):
                st.session_state[f"show_cover_letter_{suffix}"] = not st.session_state.get(
                    f"show_cover_letter_{suffix}",
                    False,
                )

            if letter_pdf_path and os.path.exists(letter_pdf_path):
                st.download_button(
                    "Download Cover Letter PDF",
                    data=_read_file_bytes(letter_pdf_path),
                    file_name=os.path.basename(letter_pdf_path),
                    mime="application/pdf",
                    key=f"cover_letter_download_{suffix}",
                    use_container_width=True,
                )

            if st.session_state.get(f"show_cover_letter_{suffix}") and letter_pdf_path:
                _preview_pdf(letter_pdf_path)

        if resume_path and os.path.exists(resume_path):
            st.markdown("#### Resume")
            resume_col1, resume_col2 = st.columns(2)
            if resume_col1.button("View Resume", key=f"view_resume_{suffix}", use_container_width=True):
                st.session_state[f"show_resume_{suffix}"] = not st.session_state.get(
                    f"show_resume_{suffix}",
                    False,
                )
            resume_col2.download_button(
                "Download Resume",
                data=_read_file_bytes(resume_path),
                file_name=os.path.basename(resume_path),
                mime="application/pdf",
                key=f"resume_download_{suffix}",
                use_container_width=True,
            )

            if st.session_state.get(f"show_resume_{suffix}"):
                _preview_pdf(resume_path, height=420)

        if st.button("✖ Close", key=f"close_detail_{suffix}", use_container_width=True):
            _close_detail()
            st.rerun()
else:

    def _detail_dialog():
        st.info("This Streamlit version does not support dialogs yet.")


def _render_job_card(job):
    with st.container(border=True):
        top_left, metric_one, metric_two, metric_three = st.columns([3, 1, 1, 1])

        with top_left:
            st.markdown(f"### {job['title']}")
            st.write(f"**{job['company'] or 'Unknown company'}**")
            location_bits = [job.get("location"), job.get("platform")]
            details = " | ".join(bit for bit in location_bits if bit)
            if details:
                st.caption(details)
            if job.get("job_url"):
                st.link_button("Open Job Posting", job["job_url"])

        with metric_one:
            st.metric("Resume Match", f"{job['match_score'] or 0}%")
        with metric_two:
            semantic_value = job.get("semantic_score")
            semantic_label = f"{semantic_value}%" if semantic_value is not None else "n/a"
            st.metric("Semantic Fit", semantic_label)
        with metric_three:
            st.metric("Posted", _format_date(job.get("posted_date")))

        if job.get("jd_summary"):
            st.write(job["jd_summary"])
        _render_keywords("Likely Keywords", job.get("keywords"))

        footer_bits = [
            f"Language: {job.get('language_pref') or 'n/a'}",
            f"Status: {normalize_application_status(job.get('pipeline_status') or job.get('status'))}",
        ]
        linked_application_id = job.get("application_id") or job.get("latest_application_id")
        if linked_application_id:
            footer_bits.append(f"Linked application #{linked_application_id}")
        if job.get("salary"):
            footer_bits.append(f"Salary: {job['salary']}")
        st.caption(" | ".join(footer_bits))

        action_col1, action_col2, action_col3 = st.columns(3)
        if action_col1.button("📄 View Full Details", key=f"job_detail_{job['id']}", use_container_width=True):
            _open_detail("job", job["id"])
        if action_col2.button("✏️ Edit", key=f"toggle_edit_job_{job['id']}", use_container_width=True):
            st.session_state[f"edit_job_{job['id']}"] = not st.session_state.get(f"edit_job_{job['id']}", False)
        if action_col3.button("🗑️ Delete", key=f"toggle_delete_job_{job['id']}", use_container_width=True):
            st.session_state[f"delete_job_{job['id']}"] = not st.session_state.get(
                f"delete_job_{job['id']}",
                False,
            )

        if st.session_state.get(f"edit_job_{job['id']}"):
            _save_job_edit(job)
        if st.session_state.get(f"delete_job_{job['id']}"):
            _delete_job_panel(job)


def _render_application_card(application):
    with st.container(border=True):
        top_left, metric_one, metric_two, metric_three = st.columns([3, 1, 1, 1])

        with top_left:
            st.markdown(f"### {application['position']}")
            st.write(f"**{application['company'] or 'Unknown company'}**")
            location_bits = [application.get("location"), application.get("platform")]
            details = " | ".join(bit for bit in location_bits if bit)
            if details:
                st.caption(details)
            if application.get("job_url"):
                st.link_button("Open Original Job", application["job_url"])

        with metric_one:
            st.metric("Your Match Score", f"{_bounded_score(application.get('job_match_score'))}%")
        with metric_two:
            st.metric("Quality Score", f"{_bounded_score(application.get('final_score'))}/100")
        with metric_three:
            st.metric("Saved", _format_date(application.get("created_at")))

        if application.get("jd_summary"):
            st.write(application["jd_summary"])
        _render_keywords("Keywords", application.get("keywords"))

        if application.get("notes"):
            st.info(application["notes"])

        doc_col1, doc_col2, doc_col3 = st.columns(3)
        cover_letter_path = _normalize_file_path(application.get("cl_pdf_path"))
        resume_path = _normalize_file_path(application.get("resume_pdf_path"))

        with doc_col1:
            cover_letter_bytes = _read_file_bytes(cover_letter_path)
            if cover_letter_bytes:
                st.download_button(
                    "Download Cover Letter",
                    data=cover_letter_bytes,
                    file_name=os.path.basename(cover_letter_path),
                    mime="application/pdf",
                    key=f"cover_dl_{application['id']}",
                    use_container_width=True,
                )
        with doc_col2:
            resume_bytes = _read_file_bytes(resume_path)
            if resume_bytes:
                st.download_button(
                    "Download Resume",
                    data=resume_bytes,
                    file_name=os.path.basename(resume_path),
                    mime="application/pdf",
                    key=f"resume_dl_{application['id']}",
                    use_container_width=True,
                )
        with doc_col3:
            st.caption(f"Status: {normalize_application_status(application.get('status'))}")
            st.caption(f"Refinement Passes: {max((application['iterations'] or 1) - 1, 0)}")
            if application.get("source_job_id"):
                st.caption(f"Source job id: {application['source_job_id']}")

        action_col1, action_col2, action_col3 = st.columns(3)
        if action_col1.button(
            "📄 View Full Details",
            key=f"application_detail_{application['id']}",
            use_container_width=True,
        ):
            _open_detail("application", application["id"])
        if action_col2.button(
            "✏️ Edit",
            key=f"toggle_edit_application_{application['id']}",
            use_container_width=True,
        ):
            st.session_state[f"edit_application_{application['id']}"] = not st.session_state.get(
                f"edit_application_{application['id']}",
                False,
            )
        if action_col3.button(
            "🗑️ Delete",
            key=f"toggle_delete_application_{application['id']}",
            use_container_width=True,
        ):
            st.session_state[f"delete_application_{application['id']}"] = not st.session_state.get(
                f"delete_application_{application['id']}",
                False,
            )

        if st.session_state.get(f"edit_application_{application['id']}"):
            _save_application_edit(application)
        if st.session_state.get(f"delete_application_{application['id']}"):
            _delete_application_panel(application)


jobs_tab, applications_tab = st.tabs(["Saved Jobs", "Applied Jobs"])

if st.session_state.get("current_page") != "applications":
    _close_detail()
st.session_state["current_page"] = "applications"

with jobs_tab:
    st.subheader("Saved Jobs")
    job_query = st.text_input(
        "Search saved jobs",
        placeholder="Try: computer vision in automotive, RAG engineer in Munich, ML Ops with Azure",
    )
    semantic_enabled = st.toggle(
        "Use semantic search",
        value=True,
        help="Search by meaning when embeddings are available, then fall back to normal text search.",
    )

    if semantic_enabled and job_query:
        st.caption("Semantic search uses your stored job embeddings in pgvector.")

    jobs = _search_jobs(job_query, semantic_enabled)
    if jobs:
        for job in jobs:
            _render_job_card(job)
    else:
        st.info("No saved jobs matched your search yet.")

with applications_tab:
    st.subheader("Applied Jobs")
    application_query = st.text_input(
        "Search applied jobs",
        placeholder="Search by company, role, notes, or summary",
    )
    applications = _search_applications(application_query)

    if applications:
        for application in applications:
            _render_application_card(application)
    else:
        st.info("No applied jobs found in the database.")

if st.session_state.get(_detail_key()):
    _detail_dialog()
