from db import fetch_all


def find_possible_duplicates(review, exclude_job_id=None):
    company_name = (review.get("company_name") or "").strip()
    position = (review.get("position") or "").strip()

    if not company_name:
        return []

    company_like = f"%{company_name}%"
    position_like = f"%{position}%"

    job_matches = fetch_all(
        """
        SELECT
            id,
            company,
            title AS position,
            created_at,
            'jobs' AS source
        FROM jobs
        WHERE (
                LOWER(company) = LOWER(%s)
                OR company ILIKE %s
                OR similarity(LOWER(company), LOWER(%s)) >= 0.72
              )
          AND (
                %s = ''
                OR LOWER(COALESCE(title, '')) = LOWER(%s)
                OR title ILIKE %s
                OR similarity(LOWER(COALESCE(title, '')), LOWER(%s)) >= 0.58
              )
          AND (%s IS NULL OR id <> %s)
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (
            company_name,
            company_like,
            company_name,
            position,
            position,
            position_like,
            position,
            exclude_job_id,
            exclude_job_id,
        ),
    )
    letter_matches = fetch_all(
        """
        SELECT
            id,
            company,
            position,
            created_at,
            'cover_letters' AS source
        FROM cover_letters
        WHERE (
                LOWER(company) = LOWER(%s)
                OR company ILIKE %s
                OR similarity(LOWER(company), LOWER(%s)) >= 0.72
              )
          AND (
                %s = ''
                OR LOWER(COALESCE(position, '')) = LOWER(%s)
                OR position ILIKE %s
                OR similarity(LOWER(COALESCE(position, '')), LOWER(%s)) >= 0.58
              )
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (
            company_name,
            company_like,
            company_name,
            position,
            position,
            position_like,
            position,
        ),
    )
    return job_matches + letter_matches
