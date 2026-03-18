import os
import re
from datetime import datetime

import streamlit as st

from db import execute, execute_returning, fetch_one
from local_store import sync_job_bundle
from platforms import normalize_platform, platform_label, platform_select_options
from semantic_search import embed_text, vector_literal


FIELD_DEFAULTS = {
    "company_name": "",
    "position": "",
    "location": "",
    "salary": "",
    "posted_date": "",
    "platform": "",
    "job_url": "",
    "language": "de",
    "department": "",
    "jd_raw": "",
}

SKILL_PATTERNS = [
    ("Python", [r"\bpython\b"]),
    ("PyTorch", [r"\bpytorch\b"]),
    ("TensorFlow", [r"\btensorflow\b"]),
    ("Scikit-learn", [r"\bscikit[- ]learn\b", r"\bsklearn\b"]),
    ("Pandas", [r"\bpandas\b"]),
    ("NumPy", [r"\bnumpy\b"]),
    ("OpenCV", [r"\bopencv\b"]),
    ("Computer Vision", [r"\bcomputer vision\b"]),
    ("Machine Learning", [r"\bmachine learning\b", r"\bml\b"]),
    ("Deep Learning", [r"\bdeep learning\b"]),
    ("LLMs", [r"\bllms?\b", r"\blarge language models?\b", r"\bgenerative ai\b", r"\bgenai\b"]),
    ("RAG", [r"\brag\b", r"\bretrieval-augmented generation\b"]),
    ("LangChain", [r"\blangchain\b"]),
    ("ChromaDB", [r"\bchromadb\b"]),
    ("NLP", [r"\bnlp\b", r"\bnatural language processing\b"]),
    ("FastAPI", [r"\bfastapi\b"]),
    ("REST APIs", [r"\brest apis?\b", r"\bapi development\b"]),
    ("Docker", [r"\bdocker\b"]),
    ("Kubernetes", [r"\bkubernetes\b", r"\bk8s\b"]),
    ("Git", [r"\bgit\b"]),
    ("Linux", [r"\blinux\b"]),
    ("SQL", [r"\bsql\b"]),
    ("PostgreSQL", [r"\bpostgres(?:ql)?\b"]),
    ("Azure ML", [r"\bazure ml\b", r"\bazure machine learning\b"]),
    ("Azure", [r"\bazure\b"]),
    ("AWS", [r"\baws\b", r"\bamazon web services\b"]),
    ("GCP", [r"\bgcp\b", r"\bgoogle cloud\b"]),
    ("MLflow", [r"\bmlflow\b"]),
    ("MLOps", [r"\bmlops\b"]),
    ("YOLO", [r"\byolo(?:v\d+)?\b"]),
    ("OCR", [r"\bocr\b", r"\btesseract\b"]),
    ("ROS", [r"\bros\b"]),
    ("Kafka", [r"\bkafka\b"]),
    ("Spark", [r"\bspark\b", r"\bapache spark\b"]),
    ("Airflow", [r"\bairflow\b"]),
    ("CI/CD", [r"\bci/cd\b", r"\bcontinuous integration\b", r"\bcontinuous deployment\b"]),
]


def inject_review_styles():
    if st.session_state.get("_job_review_styles_loaded"):
        return

    st.markdown(
        """
        <style>
        .job-review-panel {
            border: 1px solid rgba(128, 128, 128, 0.22);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            background: linear-gradient(180deg, rgba(248, 250, 252, 0.9), rgba(255, 255, 255, 0.95));
            margin-bottom: 1rem;
        }
        .job-chip {
            display: inline-block;
            margin: 0 0.45rem 0.45rem 0;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            border: 1px solid transparent;
            font-size: 0.88rem;
            font-weight: 600;
        }
        .job-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-bottom: 0.7rem;
        }
        .job-chip.match {
            background: #e9f8ef;
            border-color: #b8e0c5;
            color: #17653b;
        }
        .job-chip.missing {
            background: #fff4e5;
            border-color: #f5d2a6;
            color: #9a5b00;
        }
        .job-chip.neutral {
            background: #eef4ff;
            border-color: #cbdcff;
            color: #1d4ed8;
        }
        .job-note {
            color: #5f6b7a;
            font-size: 0.92rem;
            margin-top: 0.15rem;
            margin-bottom: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_job_review_styles_loaded"] = True


def normalize_job_data(data):
    data = data or {}
    normalized = dict(FIELD_DEFAULTS)
    normalized.update(
        {
            "company_name": data.get("company_name") or data.get("company") or "",
            "position": data.get("position") or data.get("job_title") or data.get("title") or "",
            "location": data.get("location") or "",
            "salary": data.get("salary") or "",
            "posted_date": data.get("posted_date") or data.get("date_posted") or "",
            "platform": normalize_platform(data.get("platform") or ""),
            "job_url": data.get("job_url") or data.get("url") or "",
            "language": data.get("language") or "de",
            "department": data.get("department") or data.get("hiring_manager") or "",
            "jd_raw": data.get("jd_raw") or data.get("job_description") or "",
        }
    )
    return normalized


def _job_identity(review):
    return {
        "company_name": re.sub(r"\s+", " ", (review.get("company_name") or "").strip()).casefold(),
        "position": re.sub(r"\s+", " ", (review.get("position") or "").strip()).casefold(),
        "location": re.sub(r"\s+", " ", (review.get("location") or "").strip()).casefold(),
        "job_url": (review.get("job_url") or "").strip().casefold(),
        "posted_date": (review.get("posted_date") or "").strip(),
        "language": (review.get("language") or "de").strip().casefold(),
        "platform": normalize_platform(review.get("platform") or ""),
    }


def remember_saved_job(prefix, job_id, review, editing=False):
    st.session_state[f"{prefix}_saved_job_id"] = job_id
    st.session_state[f"{prefix}_saved_job_identity"] = _job_identity(review)
    if editing:
        st.session_state[f"{prefix}_editing_job_id"] = job_id
    else:
        st.session_state.pop(f"{prefix}_editing_job_id", None)


def clear_saved_job_binding(prefix, clear_application=False):
    st.session_state.pop(f"{prefix}_saved_job_id", None)
    st.session_state.pop(f"{prefix}_saved_job_identity", None)
    st.session_state.pop(f"{prefix}_editing_job_id", None)
    if clear_application:
        st.session_state.pop(f"{prefix}_saved_application_id", None)


def mark_job_for_edit(prefix, job_id, review):
    remember_saved_job(prefix, job_id, review, editing=True)


def seed_review_state(prefix, data=None, overwrite=False):
    normalized = normalize_job_data(data)
    for field, value in normalized.items():
        key = f"{prefix}_{field}"
        if overwrite or key not in st.session_state:
            st.session_state[key] = value


def _load_resume_text():
    for path in ("/files/master_resume.txt", os.path.join("files", "master_resume.txt")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            continue
    return ""


def _extract_skills(text):
    haystack = text or ""
    matches = []
    for skill_name, patterns in SKILL_PATTERNS:
        if any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(skill_name)
    return matches


def _extract_years_requirement(text):
    matches = re.findall(r"(\d+)\s*\+?\s*(?:years|year|yrs|jahre)", text or "", flags=re.IGNORECASE)
    values = [int(match) for match in matches]
    return max(values) if values else None


def _extract_resume_years(text):
    values = re.findall(r"over\s+(\d+)\s+years|(\d+)\+?\s+years", text or "", flags=re.IGNORECASE)
    flattened = [int(item) for pair in values for item in pair if item]
    return max(flattened) if flattened else None


def _build_jd_summary(jd_raw):
    compact = re.sub(r"\s+", " ", (jd_raw or "")).strip()
    if not compact:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", compact)
    summary = " ".join(sentences[:3]).strip()
    return summary[:420]


def _render_chips(title, items, tone):
    items = items or ["None detected yet"]
    st.markdown(
        f"<div class='job-note'><strong>{title}</strong><br>{', '.join(items)}</div>",
        unsafe_allow_html=True,
    )


def analyze_job_fit(review):
    resume_text = _load_resume_text()
    resume_skills = _extract_skills(resume_text)
    required_skills = _extract_skills(f"{review['position']} {review['jd_raw']}")

    matching_skills = [skill for skill in required_skills if skill in resume_skills]
    missing_skills = [skill for skill in required_skills if skill not in resume_skills]

    required_count = len(required_skills)
    matched_count = len(matching_skills)
    coverage = matched_count / required_count if required_count else 0.0

    score = 52
    if review["jd_raw"].strip():
        score += 8
    if required_count:
        score += round(coverage * 30)
        score += round(min(matched_count, 4) / 4 * 10)

    required_years = _extract_years_requirement(review["jd_raw"])
    resume_years = _extract_resume_years(resume_text)
    if required_years and resume_years:
        score += 6 if resume_years >= required_years else -4
    elif required_years:
        score -= 2

    score = max(35, min(score, 98))

    return {
        "match_score": score,
        "matching_skills": matching_skills[:8],
        "missing_skills": missing_skills[:8],
        "required_skills": required_skills[:10],
        "resume_skills": resume_skills,
        "summary": _build_jd_summary(review["jd_raw"]),
        "required_years": required_years,
        "resume_years": resume_years,
        "matched_count": matched_count,
        "required_count": required_count,
    }


def build_generation_payload(review, analysis, job_id=None):
    payload = {
        "company_name": review["company_name"],
        "position": review["position"],
        "department": review["department"],
        "language": review["language"],
        "jd_raw": review["jd_raw"],
        "location": review["location"],
        "salary": review["salary"],
        "posted_date": review["posted_date"],
        "platform": review["platform"],
        "job_url": review["job_url"],
        "match_score": analysis["match_score"],
        "keywords": analysis["required_skills"],
        "jd_summary": analysis["summary"],
    }
    if job_id:
        payload["job_id"] = job_id
    return payload


def _parse_posted_date(value):
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _build_embedding_text(review, analysis):
    parts = [
        review["position"],
        review["company_name"],
        review["location"],
        review["platform"],
        review["salary"],
        review["jd_raw"],
        analysis["summary"],
        ", ".join(analysis["required_skills"]),
    ]
    return "\n".join(part for part in parts if part)


def build_embedding_text(review, analysis):
    return _build_embedding_text(review, analysis)


def _screenshot_payloads(prefix):
    return st.session_state.get(f"{prefix}_screenshot_payloads") or []


def _sync_job_storage(job_id, prefix, review, analysis, existing_screenshot_paths=None):
    folder_path, screenshot_paths = sync_job_bundle(
        job_id,
        review,
        analysis,
        screenshot_payloads=_screenshot_payloads(prefix),
        existing_screenshot_paths=existing_screenshot_paths,
    )
    execute(
        """
        UPDATE jobs
        SET local_folder_path = %s,
            screenshot_paths = %s
        WHERE id = %s
        """,
        (
            folder_path,
            screenshot_paths or None,
            job_id,
        ),
    )
    return folder_path, screenshot_paths


def persist_job(prefix, review, analysis):
    posted_date = _parse_posted_date(review["posted_date"])
    raw_existing_id = st.session_state.get(f"{prefix}_saved_job_id")
    existing_id = None
    if raw_existing_id:
        if st.session_state.get(f"{prefix}_editing_job_id") == raw_existing_id:
            existing_id = raw_existing_id
        elif st.session_state.get(f"{prefix}_saved_job_identity") == _job_identity(review):
            existing_id = raw_existing_id
    keywords = analysis["required_skills"]
    embedding = embed_text(
        _build_embedding_text(review, analysis),
        task_type="retrieval_document",
        title=f"{review['company_name']} - {review['position']}",
    )
    embedding_literal = vector_literal(embedding)

    try:
        if existing_id:
            current = fetch_one(
                "SELECT screenshot_paths FROM jobs WHERE id = %s",
                (existing_id,),
            )
            if not current:
                existing_id = None

        if existing_id:
            execute(
                """
                UPDATE jobs
                SET title = %s,
                    company = %s,
                    location = %s,
                    platform = %s,
                    job_url = %s,
                    jd_raw = %s,
                    jd_summary = %s,
                    keywords = %s,
                    salary = %s,
                    match_score = %s,
                    jd_embedding = %s::vector,
                    posted_date = %s,
                    language_pref = %s,
                    status = 'pending'
                WHERE id = %s
                """,
                (
                    review["position"],
                    review["company_name"],
                    review["location"] or None,
                    review["platform"] or None,
                    review["job_url"] or None,
                    review["jd_raw"],
                    analysis["summary"] or None,
                    keywords or None,
                    review["salary"] or None,
                    analysis["match_score"],
                    embedding_literal,
                    posted_date,
                    review["language"],
                    existing_id,
                ),
            )
            _sync_job_storage(
                existing_id,
                prefix,
                review,
                analysis,
                existing_screenshot_paths=current["screenshot_paths"] if current else None,
            )
            remember_saved_job(
                prefix,
                existing_id,
                review,
                editing=st.session_state.get(f"{prefix}_editing_job_id") == existing_id,
            )
            return existing_id

        row = execute_returning(
            """
            INSERT INTO jobs (
                title, company, location, platform, job_url, jd_raw,
                jd_summary, keywords, salary, match_score, jd_embedding, posted_date,
                language_pref, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            RETURNING id
            """,
            (
                review["position"],
                review["company_name"],
                review["location"] or None,
                review["platform"] or None,
                review["job_url"] or None,
                review["jd_raw"],
                analysis["summary"] or None,
                keywords or None,
                review["salary"] or None,
                analysis["match_score"],
                embedding_literal,
                posted_date,
                review["language"],
                "pending",
            ),
        )
        if row:
            remember_saved_job(prefix, row["id"], review)
            _sync_job_storage(row["id"], prefix, review, analysis)
            return row["id"]
    except Exception as exc:
        st.error(f"Could not save the job yet: {exc}")

    return None


def render_job_review_editor(prefix, panel_title, generate_label="Generate Cover Letter"):
    inject_review_styles()

    st.markdown(f"### {panel_title}")
    st.markdown(
        "<div class='job-review-panel'>Review the extracted job details, edit anything you want, "
        "and use the live match analysis before generating the letter.</div>",
        unsafe_allow_html=True,
    )

    meta_col1, meta_col2, meta_col3 = st.columns(3)

    with meta_col1:
        position = st.text_input("Job Title *", key=f"{prefix}_position")
        st.caption("Required")
        company_name = st.text_input("Company Name *", key=f"{prefix}_company_name")
        st.caption("Required")
        location = st.text_input("Location", key=f"{prefix}_location")
        st.caption("Fill if known")

    with meta_col2:
        salary = st.text_input("Salary", key=f"{prefix}_salary")
        st.caption("Optional")
        posted_date = st.text_input("Posted Date", key=f"{prefix}_posted_date", placeholder="20.02.2026")
        st.caption("Optional")
        platform_options = platform_select_options()
        current_platform = normalize_platform(st.session_state.get(f"{prefix}_platform", ""))
        if current_platform and current_platform not in platform_options:
            current_platform = "other"
        platform = st.selectbox(
            "Platform",
            platform_options,
            key=f"{prefix}_platform",
            index=platform_options.index(current_platform) if current_platform in platform_options else 0,
            format_func=platform_label,
        )
        st.caption("Optional but helpful for tracking")

    with meta_col3:
        job_url = st.text_input("Job URL", key=f"{prefix}_job_url", placeholder="https://...")
        st.caption("Optional")
        department = st.text_input(
            "Department / Hiring Manager (Optional)",
            key=f"{prefix}_department",
        )
        st.caption("Leave blank to use the default recipient")
        language = st.radio(
            "Cover Letter Language",
            ["de", "en"],
            key=f"{prefix}_language",
            horizontal=True,
            format_func=lambda value: "German" if value == "de" else "English",
        )

    jd_raw = st.text_area(
        "Job Description (edit freely)",
        key=f"{prefix}_jd_raw",
        height=320,
    )

    review = {
        "company_name": company_name,
        "position": position,
        "location": location,
        "salary": salary,
        "posted_date": posted_date,
        "platform": normalize_platform(platform),
        "job_url": job_url,
        "language": language,
        "department": department,
        "jd_raw": jd_raw,
    }

    analysis = analyze_job_fit(review)

    score_col, matched_col, missing_col = st.columns(3)
    score_col.metric("Your Match Score", f"{analysis['match_score']}%")
    matched_col.metric("Matching Skills", analysis["matched_count"])
    missing_col.metric("Missing Skills", len(analysis["missing_skills"]))

    _render_chips("Matching Skills", analysis["matching_skills"], "match")
    _render_chips("Missing Skills", analysis["missing_skills"], "missing")
    _render_chips("Likely Core Requirements", analysis["required_skills"], "neutral")

    insight_bits = []
    if analysis["required_years"]:
        insight_bits.append(f"JD asks for about {analysis['required_years']}+ years of experience")
    if analysis["resume_years"]:
        insight_bits.append(f"Resume suggests about {analysis['resume_years']}+ years of experience")
    if analysis["summary"]:
        insight_bits.append(analysis["summary"])

    if insight_bits:
        st.info(" | ".join(insight_bits))

    button_col1, button_col2 = st.columns([1, 1])
    form_valid = bool(company_name and position and jd_raw.strip())

    save_clicked = button_col1.button(
        "Save Job",
        key=f"{prefix}_save_job",
        use_container_width=True,
        disabled=not form_valid,
    )
    generate_clicked = button_col2.button(
        generate_label,
        key=f"{prefix}_generate_cover_letter",
        type="primary",
        use_container_width=True,
        disabled=not form_valid,
    )

    return review, analysis, save_clicked, generate_clicked
