import os

import psycopg2
import streamlit as st
from psycopg2 import pool
from psycopg2.extras import RealDictCursor


@st.cache_resource
def get_pool():
    return pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        database=os.environ.get("POSTGRES_DB", "jobbot_db"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        port="5432",
    )


@st.cache_resource
def ensure_runtime_schema():
    conn = get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT
                )
                """
            )
            cur.execute(
                """
                INSERT INTO settings (key, value)
                SELECT key, value
                FROM app_settings
                ON CONFLICT (key) DO NOTHING
                """
            )
            cur.execute(
                """
                ALTER TABLE applications
                ADD COLUMN IF NOT EXISTS resume_pdf_path VARCHAR(500)
                """
            )
            cur.execute(
                """
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS local_folder_path VARCHAR(500)
                """
            )
            cur.execute(
                """
                ALTER TABLE applications
                ADD COLUMN IF NOT EXISTS local_folder_path VARCHAR(500)
                """
            )
            cur.execute(
                """
                ALTER TABLE applications
                ADD COLUMN IF NOT EXISTS platform VARCHAR(50)
                """
            )
            cur.execute(
                """
                ALTER TABLE applications
                ADD COLUMN IF NOT EXISTS cover_letter_id INTEGER REFERENCES cover_letters(id)
                """
            )
            cur.execute(
                """
                ALTER TABLE applications
                ADD COLUMN IF NOT EXISTS extra_file_paths TEXT[]
                """
            )
            cur.execute("ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'pending'")
            cur.execute("ALTER TABLE applications ALTER COLUMN status SET DEFAULT 'pending'")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS email_analyses (
                    id SERIAL PRIMARY KEY,
                    gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
                    sender TEXT,
                    subject TEXT,
                    snippet TEXT,
                    email_type VARCHAR(50),
                    company VARCHAR(255),
                    action_required TEXT,
                    suggested_reply TEXT,
                    message_date TIMESTAMP,
                    is_unread BOOLEAN DEFAULT TRUE,
                    analysed_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE email_analyses
                ADD COLUMN IF NOT EXISTS snippet TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE email_analyses
                ADD COLUMN IF NOT EXISTS message_date TIMESTAMP
                """
            )
            cur.execute(
                """
                ALTER TABLE email_analyses
                ADD COLUMN IF NOT EXISTS is_unread BOOLEAN DEFAULT TRUE
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_apps_cover_letter_id
                ON applications(cover_letter_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_email_analyses_company
                ON email_analyses(company)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_embedding
                ON jobs USING hnsw (jd_embedding vector_cosine_ops)
                """
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        st.warning(f"Runtime schema update skipped: {exc}")
    finally:
        get_pool().putconn(conn)
    return True


def get_connection():
    ensure_runtime_schema()
    return get_pool().getconn()


def release_connection(conn):
    get_pool().putconn(conn)


def fetch_all(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()
    except Exception as exc:
        st.error(f"Database error: {exc}")
        return []
    finally:
        release_connection(conn)


def fetch_one(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()
    except Exception as exc:
        st.error(f"Database error: {exc}")
        return None
    finally:
        release_connection(conn)


def execute(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        release_connection(conn)


def execute_returning(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        conn.rollback()
        st.error(f"Database error: {exc}")
        return None
    finally:
        release_connection(conn)


def fetch_settings():
    rows = fetch_all("SELECT key, value FROM settings")
    return {row["key"]: row["value"] for row in rows} if rows else {}
