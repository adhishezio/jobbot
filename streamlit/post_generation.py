import base64
import os
import time

import requests
import streamlit as st

from application_status import (
    APPLICATION_STATUS_OPTIONS,
    format_application_status,
    job_status_for_application,
    normalize_application_status,
)
from db import execute, execute_returning, fetch_one
from local_store import build_job_folder, save_uploaded_file, save_uploaded_files, sync_application_bundle
from n8n_runtime import describe_pipeline_progress


APPLICATION_STATUSES = APPLICATION_STATUS_OPTIONS


def _pending_key(prefix):
    return f"{prefix}_pending_generation"


def _ready_key(prefix):
    return f"{prefix}_ready_generation"


def _error_key(prefix):
    return f"{prefix}_generation_error"


def _history_key(prefix):
    return f"{prefix}_pipeline_history"


def _pdf_path(letter):
    filename = letter.get("pdf_filename") or ""
    return os.path.join("/files", filename) if filename else ""


def _bounded_score(value):
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(round(numeric, 1), 100))


def _existing_application(letter_id):
    return fetch_one(
        """
        SELECT *
        FROM applications
        WHERE cover_letter_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (letter_id,),
    )


def _save_application(prefix, ready_state, status, notes, uploaded_resume, uploaded_attachments):
    letter = ready_state["letter"]
    context = ready_state["context"]
    existing = _existing_application(letter["id"])
    review = context["review"]
    analysis = context["analysis"]
    normalized_status = normalize_application_status(status)
    job_folder = None
    if context.get("job_id"):
        job_row = fetch_one(
            "SELECT local_folder_path FROM jobs WHERE id = %s",
            (context["job_id"],),
        )
        if job_row:
            job_folder = job_row.get("local_folder_path")
    if not job_folder:
        job_folder = build_job_folder(
            context.get("job_id") or f"adhoc_{letter['id']}",
            review["company_name"],
            review["position"],
        )

    resume_path = existing["resume_pdf_path"] if existing else None
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

    pdf_path = _pdf_path(letter) or None
    params = (
        review["company_name"] or letter["company"],
        None,
        review["position"] or letter["position"],
        letter["language"] or review["language"],
        review["jd_raw"],
        analysis["summary"] or None,
        analysis["required_skills"] or None,
        letter.get("latex_source"),
        pdf_path,
        _bounded_score(letter.get("score")),
        letter.get("iterations"),
        normalized_status,
        notes.strip() or None,
        context.get("job_id"),
        review.get("platform") or None,
        resume_path,
        attachment_paths or None,
        letter["id"],
        existing["local_folder_path"] if existing else None,
    )

    if existing:
        row = execute_returning(
            """
            UPDATE applications
            SET company = %s,
                company_address = %s,
                position = %s,
                language = %s,
                jd_raw = %s,
                jd_summary = %s,
                keywords = %s,
                cl_text = %s,
                cl_pdf_path = %s,
                final_score = %s,
                iterations = %s,
                status = %s,
                notes = %s,
                source_job_id = %s,
                platform = %s,
                resume_pdf_path = %s,
                extra_file_paths = %s,
                cover_letter_id = %s,
                local_folder_path = %s
            WHERE id = %s
            RETURNING id
            """,
            params + (existing["id"],),
        )
    else:
        row = execute_returning(
            """
            INSERT INTO applications (
                company,
                company_address,
                position,
                language,
                jd_raw,
                jd_summary,
                keywords,
                cl_text,
                cl_pdf_path,
                final_score,
                iterations,
                status,
                notes,
                source_job_id,
                platform,
                resume_pdf_path,
                extra_file_paths,
                cover_letter_id,
                local_folder_path
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            params,
        )

    if row and context.get("job_id"):
        execute(
            """
            UPDATE jobs
            SET application_id = %s,
                status = %s
            WHERE id = %s
            """,
            (
                row["id"],
                job_status_for_application(normalized_status),
                context["job_id"],
            ),
        )

    if row:
        application_folder, copied_cover_letter, copied_resume, copied_attachments = sync_application_bundle(
            job_folder,
            row["id"],
            {
                "company": review["company_name"] or letter["company"],
                "position": review["position"] or letter["position"],
                "language": letter["language"] or review["language"],
                "status": normalized_status,
                "notes": notes.strip() or None,
                "source_job_id": context.get("job_id"),
            },
            cover_letter_pdf_path=pdf_path,
            resume_pdf_path=resume_path,
            latex_source=letter.get("latex_source"),
            attachment_paths=attachment_paths,
        )
        execute(
            """
            UPDATE applications
            SET cl_pdf_path = %s,
                resume_pdf_path = %s,
                local_folder_path = %s,
                extra_file_paths = %s
            WHERE id = %s
            """,
            (
                copied_cover_letter or pdf_path,
                copied_resume or resume_path,
                application_folder,
                copied_attachments or attachment_paths or None,
                row["id"],
            ),
        )
        st.session_state[f"{prefix}_saved_application_id"] = row["id"]
        ready_state["saved_application_id"] = row["id"]
        ready_state["resume_pdf_path"] = copied_resume or resume_path
        ready_state["extra_file_paths"] = copied_attachments or attachment_paths or []
        ready_state["application_status"] = normalized_status
        return row["id"]

    return None


if hasattr(st, "dialog"):

    @st.dialog("Save Application")
    def _save_application_dialog(prefix):
        ready_state = st.session_state.get(_ready_key(prefix))
        if not ready_state:
            st.info("No generated cover letter is ready to save.")
            return

        letter = ready_state["letter"]
        context = ready_state["context"]
        existing = _existing_application(letter["id"])

        default_status = normalize_application_status(existing["status"] if existing else "pending")
        default_notes = existing["notes"] if existing else ""
        default_resume = existing["resume_pdf_path"] if existing else None
        default_attachments = existing["extra_file_paths"] if existing else []
        status_index = (
            APPLICATION_STATUSES.index(default_status)
            if default_status in APPLICATION_STATUSES
            else 0
        )

        st.markdown(
            f"**{context['review']['company_name']}**  \n"
            f"{context['review']['position']}  \n"
            f"Score: {_bounded_score(letter.get('score'))}/100"
        )
        if default_resume:
            st.caption(f"Current resume on file: {default_resume}")
        if default_attachments:
            st.caption(f"Current extra files: {len(default_attachments)}")

        with st.form(f"{prefix}_save_application_form"):
            status = st.selectbox(
                "Application Status",
                APPLICATION_STATUSES,
                index=status_index,
                format_func=format_application_status,
            )
            notes = st.text_area(
                "Notes",
                value=default_notes,
                placeholder="Add follow-up notes, recruiter details, interview prep notes, etc.",
                height=120,
            )
            uploaded_resume = st.file_uploader(
                "Resume PDF (optional)",
                type=["pdf"],
                key=f"{prefix}_resume_upload",
                help="Upload a tailored resume to store with this application.",
            )
            uploaded_attachments = st.file_uploader(
                "Extra Files (optional)",
                type=["pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key=f"{prefix}_extra_files_upload",
                help="Upload certificates, transcripts, portfolios, or supporting images.",
            )
            submitted = st.form_submit_button(
                "Save Application",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            application_id = _save_application(
                prefix,
                ready_state,
                status,
                notes,
                uploaded_resume,
                uploaded_attachments,
            )
            if application_id:
                st.success(f"Application saved with id {application_id}.")
                time.sleep(0.8)
                st.rerun()
else:

    def _save_application_dialog(prefix):
        st.info("This Streamlit version does not support dialogs yet.")


def start_cover_letter_generation(prefix, review, analysis, payload, job_id, status_label):
    st.session_state.pop(_error_key(prefix), None)
    st.session_state.pop(_history_key(prefix), None)
    with st.status(status_label) as status:
        try:
            n8n_base = os.environ.get("N8N_WEBHOOK_BASE_URL", "http://n8n:5678/webhook")
            webhook_url = f"{n8n_base}/generate-cover-letter"
            response = requests.post(webhook_url, json=payload, timeout=30)
            response_text = (response.text or "").strip()
            execution_id = None
            try:
                response_json = response.json()
                execution_id = response_json.get("execution_id") or response_json.get("executionId")
            except Exception:
                response_json = None

            if response.status_code == 200:
                status.update(label="Pipeline started", state="complete")
                st.session_state[_pending_key(prefix)] = {
                    "company": review["company_name"],
                    "review": review,
                    "analysis": analysis,
                    "payload": payload,
                    "job_id": job_id,
                    "started_at": time.time(),
                    "execution_id": execution_id,
                    "initial_response": response_json or response_text,
                }
                st.session_state.pop(_ready_key(prefix), None)
                st.info(
                    "Address confirmation will stay inside JobBot if needed, and this page will show the live n8n stage plus the exact error if anything fails."
                )
                time.sleep(1)
                st.rerun()

            status.update(label=f"Pipeline failed: {response.status_code}", state="error")
            st.session_state[_error_key(prefix)] = {
                "context": {
                    "company": review["company_name"],
                    "review": review,
                    "analysis": analysis,
                    "payload": payload,
                    "job_id": job_id,
                },
                "label": "Pipeline Start Failed",
                "node": "Webhook",
                "message": response_text[:1000] or "n8n returned an empty error response.",
            }
            st.error(response_text[:1000] or "n8n returned an empty error response.")
        except Exception as exc:
            status.update(label=f"Error connecting to n8n: {exc}", state="error")
            st.session_state[_error_key(prefix)] = {
                "context": {
                    "company": review["company_name"],
                    "review": review,
                    "analysis": analysis,
                    "payload": payload,
                    "job_id": job_id,
                },
                "label": "Could Not Reach n8n",
                "node": "Webhook",
                "message": str(exc),
            }


def poll_cover_letter_completion(prefix, timeout_seconds=600):
    pending = st.session_state.get(_pending_key(prefix))
    if not pending:
        return

    company = pending["company"]
    position = pending.get("review", {}).get("position")
    with st.spinner(f"Pipeline running for {company}. Waiting for the final result..."):
        snapshot = describe_pipeline_progress(pending)
        history = st.session_state.setdefault(_history_key(prefix), [])
        signature = (
            snapshot.get("label"),
            snapshot.get("node"),
            snapshot.get("detail"),
            snapshot.get("state"),
        )
        if not history or history[-1].get("signature") != signature:
            history.append(
                {
                    "signature": signature,
                    "label": snapshot.get("label"),
                    "detail": snapshot.get("detail"),
                    "progress": snapshot.get("progress", 0),
                }
            )
        progress_value = max(0.03, min(snapshot.get("progress", 0.05), 0.995))
        progress_pct = int(progress_value * 100)
        st.progress(progress_value, text=f"{progress_pct}% - {snapshot.get('label', 'Running Pipeline')}")
        if snapshot.get("detail"):
            st.caption(snapshot["detail"])
        if history:
            labels = [item["label"] for item in history if item.get("label")]
            if labels:
                st.caption("Seen so far: " + " -> ".join(labels[-6:]))

        if snapshot.get("state") == "error":
            st.session_state[_error_key(prefix)] = {
                "context": pending,
                "label": snapshot.get("label") or "Pipeline Error",
                "node": snapshot.get("node") or snapshot.get("label"),
                "message": snapshot.get("detail") or "n8n reported an error.",
                "execution_id": snapshot.get("execution_id"),
            }
            st.session_state.pop(_pending_key(prefix), None)
            st.rerun()

        notif = fetch_one(
            """
            SELECT *
            FROM notifications
            WHERE type = 'cl_ready'
              AND title LIKE %s
              AND is_read = FALSE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (f"%{company}%",),
        )

        letter = None
        if notif:
            execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notif["id"],))
            letter = fetch_one(
                """
                SELECT *
                FROM cover_letters
                WHERE company = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (company,),
            )
        else:
            letter = fetch_one(
                """
                SELECT *
                FROM cover_letters
                WHERE company = %s
                  AND position = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (company, position),
            )

        if letter:
            if not history or history[-1].get("label") != "Loading Final Cover Letter":
                history.append(
                    {
                        "signature": ("Loading Final Cover Letter", None, None, "running"),
                        "label": "Loading Final Cover Letter",
                        "detail": "JobBot found the saved cover letter and is opening it now.",
                        "progress": 0.995,
                    }
                )
            history.append(
                {
                    "signature": ("Completed", None, None, "complete"),
                    "label": "Completed",
                    "detail": "Cover letter saved and ready in JobBot.",
                    "progress": 1.0,
                }
            )
            st.session_state[_ready_key(prefix)] = {
                "context": pending,
                "letter": dict(letter),
                "history": history,
                "saved_application_id": st.session_state.get(
                    f"{prefix}_saved_application_id"
                ),
            }
            st.session_state.pop(_pending_key(prefix), None)
            st.session_state.pop(_error_key(prefix), None)
            st.balloons()
            st.rerun()

        elapsed = time.time() - pending["started_at"]
        if elapsed > timeout_seconds:
            st.info(
                f"This run is still active after {int(elapsed)} seconds. The live stage above will keep updating until it completes or errors."
            )

        next_poll_seconds = 5 if snapshot.get("needs_address") else 1
        time.sleep(next_poll_seconds)
        st.rerun()


def render_generated_cover_letter(prefix):
    ready_state = st.session_state.get(_ready_key(prefix))
    error_state = st.session_state.get(_error_key(prefix))
    if not ready_state and error_state:
        context = error_state.get("context") or {}
        st.error(f"Pipeline Error - {context.get('review', {}).get('company_name') or context.get('company') or 'Unknown Company'}")
        if error_state.get("node"):
            st.caption(f"Failed At: {error_state['node']}")
        if error_state.get("label"):
            st.write(f"**Stage:** {error_state['label']}")
        if error_state.get("execution_id"):
            st.caption(f"n8n Execution Id: {error_state['execution_id']}")
        if error_state.get("message"):
            st.code(error_state["message"])

        retry_col, dismiss_col = st.columns(2)
        if retry_col.button("Retry Generation", key=f"{prefix}_retry_error", use_container_width=True):
            start_cover_letter_generation(
                prefix,
                context["review"],
                context["analysis"],
                context["payload"],
                context.get("job_id"),
                "Restarting n8n pipeline...",
            )
        if dismiss_col.button("Dismiss Error", key=f"{prefix}_dismiss_error", use_container_width=True):
            st.session_state.pop(_error_key(prefix), None)
            st.rerun()
        return

    if not ready_state:
        return

    letter = ready_state["letter"]
    context = ready_state["context"]
    history = ready_state.get("history") or st.session_state.get(_history_key(prefix), [])
    pdf_path = _pdf_path(letter)
    existing = _existing_application(letter["id"])
    if existing and existing.get("resume_pdf_path") and not ready_state.get("resume_pdf_path"):
        ready_state["resume_pdf_path"] = existing["resume_pdf_path"]
    if existing and existing.get("id") and not ready_state.get("saved_application_id"):
        ready_state["saved_application_id"] = existing["id"]
    if existing and existing.get("status") and not ready_state.get("application_status"):
        ready_state["application_status"] = existing["status"]

    st.success(f"Cover Letter Ready - {context['review']['company_name']}")
    if history:
        labels = [item["label"] for item in history if item.get("label")]
        if labels:
            st.caption("Pipeline stages: " + " -> ".join(labels))
    col1, col2 = st.columns([3, 1])

    with col2:
        st.metric("Quality Score", f"{_bounded_score(letter.get('score'))}/100")
        st.metric("Refinement Passes", max((letter["iterations"] or 1) - 1, 0))
        if existing or ready_state.get("saved_application_id"):
            status_label = "Applied Job" if ready_state.get("application_status") == "applied" else "Saved Application"
            st.caption(
                f"{status_label} id {ready_state.get('saved_application_id') or existing['id']}."
            )
        if ready_state.get("resume_pdf_path"):
            st.caption(f"Resume saved: {ready_state['resume_pdf_path']}")

        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as file_handle:
                pdf_bytes = file_handle.read()
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name=letter["pdf_filename"],
                mime="application/pdf",
                use_container_width=True,
            )

        if st.button("Regenerate", key=f"{prefix}_regen", use_container_width=True):
            start_cover_letter_generation(
                prefix,
                context["review"],
                context["analysis"],
                context["payload"],
                context["job_id"],
                "Restarting n8n pipeline...",
            )

        if st.button("Save Application", key=f"{prefix}_save_app", use_container_width=True):
            _save_application_dialog(prefix)

        if st.button("Dismiss", key=f"{prefix}_dismiss", use_container_width=True):
            st.session_state.pop(_ready_key(prefix), None)
            st.session_state.pop(_history_key(prefix), None)
            st.rerun()

    with col1:
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as file_handle:
                b64 = base64.b64encode(file_handle.read()).decode("utf-8")
            st.markdown(
                f"""
                <iframe src="data:application/pdf;base64,{b64}"
                    width="100%" height="700px"
                    style="border:1px solid #333; border-radius:4px;">
                </iframe>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.error("PDF file not found on disk.")
