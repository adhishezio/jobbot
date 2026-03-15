import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import streamlit as st  # We MUST keep this for caching and error messages!

# Connection pool — created once, reused across all calls
@st.cache_resource
def get_pool():
    return psycopg2.pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        database=os.environ.get("POSTGRES_DB", "jobbot_db"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        port="5432"
    )

def get_connection():
    return get_pool().getconn()

def release_connection(conn):
    get_pool().putconn(conn)

def fetch_all(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()
    except Exception as e:
        st.error(f"Database error: {e}")
        return []
    finally:
        release_connection(conn)

def fetch_one(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()
    except Exception as e:
        st.error(f"Database error: {e}")
        return None
    finally:
        release_connection(conn)

def execute(query, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e  
    finally:
        release_connection(conn)

def execute_returning(query, params=None):
    """For INSERT...RETURNING statements — returns the row."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            conn.commit()
            return cur.fetchone()
    except Exception as e:
        conn.rollback()
        st.error(f"Database error: {e}")
        return None
    finally:
        release_connection(conn)

def fetch_settings():
    rows = fetch_all("SELECT key, value FROM settings")
    return {row['key']: row['value'] for row in rows} if rows else {}