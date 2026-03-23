from __future__ import annotations

from datetime import datetime
from pathlib import Path


DEFAULT_RESUME_TEXT = (
    "Add your professional summary, experience, projects, education, and skills here.\n"
    "JobBot uses this file to estimate your match score and to ground cover-letter evidence.\n"
)


def _candidate_paths():
    return [
        Path("/files/master_resume.txt"),
        Path("files/master_resume.txt"),
    ]


def resolve_master_resume_path():
    for path in _candidate_paths():
        if path.exists():
            return path
    for path in _candidate_paths():
        if path.parent.exists():
            return path
    return Path("files/master_resume.txt")


def _history_dir(resume_path: Path):
    return resume_path.parent / "resume_history"


def load_master_resume(path: str | Path | None = None):
    resume_path = Path(path) if path else resolve_master_resume_path()
    try:
        return resume_path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_RESUME_TEXT


def resume_metadata(path: str | Path | None = None):
    resume_path = Path(path) if path else resolve_master_resume_path()
    text = load_master_resume(resume_path)
    exists = resume_path.exists()
    last_modified = None
    if exists:
        try:
            last_modified = datetime.fromtimestamp(resume_path.stat().st_mtime)
        except OSError:
            last_modified = None
    return {
        "path": str(resume_path),
        "exists": exists,
        "last_modified": last_modified,
        "line_count": len(text.splitlines()) if text else 0,
        "char_count": len(text),
    }


def save_master_resume(content: str, path: str | Path | None = None):
    resume_path = Path(path) if path else resolve_master_resume_path()
    resume_path.parent.mkdir(parents=True, exist_ok=True)

    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = f"{normalized}\n" if normalized else DEFAULT_RESUME_TEXT

    backup_path = None
    if resume_path.exists():
        current_text = resume_path.read_text(encoding="utf-8")
        if current_text != normalized:
            history_dir = _history_dir(resume_path)
            history_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = history_dir / f"master_resume_{stamp}.txt"
            backup_path.write_text(current_text, encoding="utf-8")

    resume_path.write_text(normalized, encoding="utf-8")
    meta = resume_metadata(resume_path)
    meta["backup_path"] = str(backup_path) if backup_path else None
    return meta
