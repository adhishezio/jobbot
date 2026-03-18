import re


PLATFORM_LABELS = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "stepstone": "StepStone",
    "xing": "XING",
    "company_website": "Company Website",
    "glassdoor": "Glassdoor",
    "wellfound": "Wellfound",
    "instaffo": "Instaffo",
    "honeypot": "Honeypot",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "monster": "Monster",
    "arbeitsagentur": "Arbeitsagentur",
    "other": "Other",
}

PLATFORM_ALIASES = {
    "linked in": "linkedin",
    "linkedin": "linkedin",
    "indeed": "indeed",
    "step stone": "stepstone",
    "stepstone": "stepstone",
    "xing": "xing",
    "company website": "company_website",
    "company site": "company_website",
    "career site": "company_website",
    "careers page": "company_website",
    "website": "company_website",
    "glassdoor": "glassdoor",
    "wellfound": "wellfound",
    "angellist": "wellfound",
    "instaffo": "instaffo",
    "honeypot": "honeypot",
    "greenhouse": "greenhouse",
    "lever": "lever",
    "monster": "monster",
    "arbeitsagentur": "arbeitsagentur",
    "agentur fur arbeit": "arbeitsagentur",
    "agentur fuer arbeit": "arbeitsagentur",
    "bundesagentur fur arbeit": "arbeitsagentur",
    "bundesagentur fuer arbeit": "arbeitsagentur",
    "other": "other",
    "unknown": "other",
}

PLATFORM_OPTIONS = list(PLATFORM_LABELS.keys())


def normalize_platform(value):
    raw = (value or "").strip()
    if not raw:
        return ""

    lowered = re.sub(r"[_\-]+", " ", raw.casefold())
    lowered = re.sub(r"\s+", " ", lowered).strip()

    if lowered in PLATFORM_ALIASES:
        return PLATFORM_ALIASES[lowered]

    for candidate, normalized in PLATFORM_ALIASES.items():
        if candidate and candidate in lowered:
            return normalized

    return "other"


def platform_label(value):
    normalized = normalize_platform(value)
    if not normalized:
        return "Not Specified"
    return PLATFORM_LABELS.get(normalized, "Other")


def platform_select_options(include_blank=True):
    options = list(PLATFORM_OPTIONS)
    if include_blank:
        return [""] + options
    return options
