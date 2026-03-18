import streamlit as st

from components import show_address_confirmation_card
from db import fetch_all, fetch_one
from ui import apply_ui_theme


st.set_page_config(page_title="JobBot AI", page_icon="🤖", layout="wide")
apply_ui_theme()
st.title("🤖 JobBot AI")
st.caption("Your local control center for job search, cover letters, applications, and inbox follow-ups.")
st.session_state["current_page"] = "home"

with st.sidebar:
    st.divider()
    show_address_confirmation_card()


def _metric_value(query):
    row = fetch_one(query)
    return row["value"] if row else 0


total_jobs = _metric_value(
    """
    SELECT COUNT(*) AS value
    FROM jobs
    WHERE LOWER(COALESCE(status, 'pending')) IN ('', 'new', 'drafted', 'pending', 'application_saved')
    """
)
total_applications = _metric_value(
    """
    SELECT COUNT(*) AS value
    FROM applications
    WHERE LOWER(COALESCE(status, 'pending')) NOT IN ('drafted', 'pending', 'application_saved')
    """
)
unread_notifications = _metric_value("SELECT COUNT(*) AS value FROM email_analyses WHERE is_unread = TRUE")
recent_cover_letters = _metric_value(
    "SELECT COUNT(*) AS value FROM cover_letters WHERE created_at > NOW() - INTERVAL '7 days'"
)
pending_confirmations = _metric_value(
    "SELECT COUNT(*) AS value FROM address_confirmations WHERE status = 'pending' AND expires_at > NOW()"
)

metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
metric_col1.metric("Saved Jobs", total_jobs)
metric_col2.metric("Applied Jobs", total_applications)
metric_col3.metric("Unread Alerts", unread_notifications)
metric_col4.metric("Cover Letters (7d)", recent_cover_letters)
metric_col5.metric("Pending Address Checks", pending_confirmations)
metric_col3.page_link("pages/6_email_inbox.py", label="Open Inbox")

st.divider()

left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("Recent Pipeline Activity")
    recent_items = fetch_all(
        """
        SELECT 'application' AS item_type, company, position AS primary_label, created_at
        FROM applications
        UNION ALL
        SELECT 'job' AS item_type, company, title AS primary_label, created_at
        FROM jobs
        ORDER BY created_at DESC
        LIMIT 8
        """
    )

    if recent_items:
        for item in recent_items:
            with st.container(border=True):
                st.markdown(f"**{item['company'] or 'Unknown company'}**")
                st.write(item["primary_label"])
                st.caption(f"{item['item_type'].title()} | {item['created_at'].strftime('%d %b %Y %H:%M')}")
    else:
        st.info("No jobs or applications saved yet.")

with right_col:
    st.subheader("Quick Start")
    with st.container(border=True):
        st.markdown("**New Application**")
        st.write("Paste text, upload screenshots, or enter details manually, then review the fit score and trigger the pipeline.")
    with st.container(border=True):
        st.markdown("**Application Dashboard**")
        st.write("Track funnel conversion, score distribution, platform breakdown, and weekly activity in one place.")
    with st.container(border=True):
        st.markdown("**Application Pipeline**")
        st.write("Search saved jobs semantically, open full details, and manage applied jobs from one place.")
    with st.container(border=True):
        st.markdown("**Job Email Inbox**")
        st.write("Review inbox messages, classify them with Ollama, and save structured follow-up insights.")
