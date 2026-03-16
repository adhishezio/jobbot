import json
import os
import re
import shutil


BASE_STORAGE_DIR = "/files/job_records"


def safe_slug(value):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip())
    return cleaned.strip("_") or "record"


def build_job_folder(job_id, company_name, position):
    folder_name = f"job_{job_id}_{safe_slug(company_name)}_{safe_slug(position)}"
    return os.path.join(BASE_STORAGE_DIR, folder_name)


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

    return application_dir, copied_cover_letter, copied_resume
