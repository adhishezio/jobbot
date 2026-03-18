APPLICATION_STATUS_OPTIONS = [
    "pending",
    "applied",
    "interview",
    "offer",
    "rejected",
    "closed",
]

_PENDING_ALIASES = {
    "",
    "new",
    "drafted",
    "pending",
    "application_saved",
}


def normalize_application_status(value):
    normalized = (value or "").strip().lower()
    if normalized in _PENDING_ALIASES:
        return "pending"
    return normalized or "pending"


def is_pending_status(value):
    return normalize_application_status(value) == "pending"


def job_status_for_application(value):
    return normalize_application_status(value)


def format_application_status(value):
    normalized = normalize_application_status(value)
    return normalized.replace("_", " ").title()
