from db import fetch_all


def _compact(value):
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def find_possible_duplicates(review, exclude_job_id=None):
    company_name = (review.get("company_name") or "").strip()
    position = (review.get("position") or "").strip()

    if not company_name:
        return []

    company_like = f"%{company_name}%"
    position_like = f"%{position}%"
    company_compact = _compact(company_name)
    company_compact_like = f"%{company_compact}%"

    pending_job_matches = fetch_all(
        """
        SELECT
            j.id,
            j.company,
            j.title AS position,
            j.created_at,
            'Saved Jobs' AS source
        FROM jobs j
        LEFT JOIN LATERAL (
            SELECT status
            FROM applications a
            WHERE a.source_job_id = j.id
            ORDER BY a.created_at DESC
            LIMIT 1
        ) latest_app ON TRUE
        WHERE (
                LOWER(COALESCE(j.status, 'pending')) IN ('', 'new', 'drafted', 'pending', 'application_saved')
                OR LOWER(COALESCE(latest_app.status, 'pending')) IN ('', 'new', 'drafted', 'pending', 'application_saved')
              )
          AND (
                regexp_replace(LOWER(COALESCE(j.company, '')), '[^a-z0-9]+', '', 'g') = %s
                OR regexp_replace(LOWER(COALESCE(j.company, '')), '[^a-z0-9]+', '', 'g') LIKE %s
                OR j.company ILIKE %s
                OR similarity(
                    regexp_replace(LOWER(COALESCE(j.company, '')), '[^a-z0-9]+', '', 'g'),
                    %s
                ) >= 0.84
              )
          AND (
                %s = ''
                OR LOWER(COALESCE(j.title, '')) = LOWER(%s)
                OR j.title ILIKE %s
                OR similarity(LOWER(COALESCE(j.title, '')), LOWER(%s)) >= 0.60
              )
          AND (%s IS NULL OR j.id <> %s)
        ORDER BY j.created_at DESC
        LIMIT 10
        """,
        (
            company_compact,
            company_compact_like,
            company_like,
            company_compact,
            position,
            position,
            position_like,
            position,
            exclude_job_id,
            exclude_job_id,
        ),
    )

    applied_matches = fetch_all(
        """
        SELECT
            a.id,
            a.company,
            a.position,
            a.created_at,
            'Applied Jobs' AS source
        FROM applications a
        WHERE LOWER(COALESCE(a.status, 'pending')) NOT IN ('', 'new', 'drafted', 'pending', 'application_saved')
          AND (
                regexp_replace(LOWER(COALESCE(a.company, '')), '[^a-z0-9]+', '', 'g') = %s
                OR regexp_replace(LOWER(COALESCE(a.company, '')), '[^a-z0-9]+', '', 'g') LIKE %s
                OR a.company ILIKE %s
                OR similarity(
                    regexp_replace(LOWER(COALESCE(a.company, '')), '[^a-z0-9]+', '', 'g'),
                    %s
                ) >= 0.84
              )
          AND (
                %s = ''
                OR LOWER(COALESCE(a.position, '')) = LOWER(%s)
                OR a.position ILIKE %s
                OR similarity(LOWER(COALESCE(a.position, '')), LOWER(%s)) >= 0.60
              )
          AND (%s IS NULL OR COALESCE(a.source_job_id, -1) <> %s)
        ORDER BY a.created_at DESC
        LIMIT 10
        """,
        (
            company_compact,
            company_compact_like,
            company_like,
            company_compact,
            position,
            position,
            position_like,
            position,
            exclude_job_id,
            exclude_job_id,
        ),
    )

    deduped = {}
    for row in pending_job_matches + applied_matches:
        deduped[(row["source"], row["id"])] = row
    return list(deduped.values())
