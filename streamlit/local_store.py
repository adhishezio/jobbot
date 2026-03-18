import json
import os
import re
import shutil
from datetime import datetime


BASE_STORAGE_DIR = "/files/job_records"


def safe_slug(value):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip())
    return cleaned.strip("_") or "record"


def build_job_folder(job_id, company_name, position):
    # Keep the folder name stable per job id so later edits do not create orphan folders.
    folder_name = f"job_{safe_slug(str(job_id))}"
    return os.path.join(BASE_STORAGE_DIR, folder_name)


def save_uploaded_file(uploaded_file, subfolder, company_name, position, suffix=None):
    if not uploaded_file:
        return None

    target_dir = os.path.join("/files", subfolder)
    os.makedirs(target_dir, exist_ok=True)

    extension = os.path.splitext(uploaded_file.name or "")[1].lower() or ".bin"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = safe_slug(suffix or os.path.splitext(uploaded_file.name or "document")[0])
    filename = f"{timestamp}_{safe_slug(company_name)}_{safe_slug(position)}_{label}{extension}"
    target_path = os.path.join(target_dir, filename)

    with open(target_path, "wb") as handle:
        handle.write(uploaded_file.getbuffer())

    return target_path


def save_uploaded_files(uploaded_files, subfolder, company_name, position, label_prefix="attachment"):
    saved_paths = []
    for index, uploaded_file in enumerate(uploaded_files or [], start=1):
        saved_path = save_uploaded_file(
            uploaded_file,
            subfolder,
            company_name,
            position,
            suffix=f"{label_prefix}_{index}",
        )
        if saved_path:
            saved_paths.append(saved_path)
    return saved_paths


def sync_job_bundle(job_id, review, analysis, screenshot_payloads=None, existing_screenshot_paths=None):
    folder_path = build_job_folder(job_id, review["company_name"], review["position"])
    os.makedirs(folder_path, exist_ok=True)

    with open(os.path.join(folder_path, "job_description.txt"), "w", encoding="utf-8") as handle:
        handle.write(review.get("jd_raw", ""))

    with open(os.path.join(folder_path, "job_review.json"), "w", encoding="utf-8") as handle:
        json.dump(review, handle, indent=2, ensure_ascii=False)

    with open(os.path.join(folder_path, "fit_analysis.json"), "w", encoding="utf-8") as handle:
        json.dump(analysis, handle, indent=2, ensure_ascii=False)

    screenshot_paths = list(existing_screenshot_paths or [])
    if screenshot_payloads:
        screenshot_dir = os.path.join(folder_path, "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_paths = []
        for index, payload in enumerate(screenshot_payloads, start=1):
            original_name = payload.get("name") or f"screenshot_{index}.png"
            extension = os.path.splitext(original_name)[1] or ".png"
            filename = f"screenshot_{index}{extension}"
            target_path = os.path.join(screenshot_dir, filename)
            with open(target_path, "wb") as handle:
                handle.write(payload["bytes"])
            screenshot_paths.append(target_path)

    return folder_path, screenshot_paths


def sync_application_bundle(
    folder_path,
    application_id,
    metadata,
    cover_letter_pdf_path=None,
    resume_pdf_path=None,
    latex_source=None,
    attachment_paths=None,
):
    application_dir = os.path.join(folder_path, f"application_{application_id}")
    os.makedirs(application_dir, exist_ok=True)

    with open(os.path.join(application_dir, "application.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)

    if latex_source:
        with open(os.path.join(application_dir, "cover_letter.tex"), "w", encoding="utf-8") as handle:
            handle.write(latex_source)

    copied_cover_letter = None
    if cover_letter_pdf_path and os.path.exists(cover_letter_pdf_path):
        copied_cover_letter = os.path.join(application_dir, "cover_letter.pdf")
        if os.path.abspath(cover_letter_pdf_path) != os.path.abspath(copied_cover_letter):
            shutil.copy2(cover_letter_pdf_path, copied_cover_letter)

    copied_resume = None
    if resume_pdf_path and os.path.exists(resume_pdf_path):
        copied_resume = os.path.join(application_dir, "resume.pdf")
        if os.path.abspath(resume_pdf_path) != os.path.abspath(copied_resume):
            shutil.copy2(resume_pdf_path, copied_resume)

    copied_attachments = []
    if attachment_paths:
        attachment_dir = os.path.join(application_dir, "attachments")
        os.makedirs(attachment_dir, exist_ok=True)
        for source_path in attachment_paths:
            if not source_path or not os.path.exists(source_path):
                continue
            target_path = os.path.join(attachment_dir, os.path.basename(source_path))
            if os.path.abspath(source_path) != os.path.abspath(target_path):
                shutil.copy2(source_path, target_path)
            copied_attachments.append(target_path)

    return application_dir, copied_cover_letter, copied_resume, copied_attachments
