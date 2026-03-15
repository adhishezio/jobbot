import streamlit as st
import requests
import time
import os
from db import fetch_all, execute

# ← urlparse line is GONE
def _confirm_address(exec_id, resume_url_path, street, plz):
    """Updates DB and directly wakes up the n8n Wait node."""
    try:
        execute("""
            UPDATE address_confirmations
            SET status = 'confirmed',
                found_street = %s,
                found_plz_city = %s
            WHERE execution_id = %s
        """, (street, plz, exec_id))

        # ✅ SIMPLEST FIX: n8n Wait node URL is ALWAYS /webhook-waiting/{execution_id}
        # No need to store, parse, or reconstruct anything
        n8n_host = os.environ.get("N8N_INTERNAL_URL", "http://n8n:5678")
        wake_url = f"{n8n_host}/webhook-waiting/{exec_id}"

        st.info(f"Waking n8n at: {wake_url}")

        response = requests.get(wake_url, timeout=10)

        if response.status_code == 200:
            st.success("✅ Address confirmed — pipeline continuing!")
            return True
        else:
            st.error(f"n8n returned status {response.status_code}: {response.text[:200]}")
            return False

    except requests.exceptions.Timeout:
        st.error("⏱️ n8n did not respond in time.")
        st.stop()
        return False
    except Exception as e:
        st.error(f"🛑 Error: {e}")
        st.stop()
        return False

def show_address_confirmation_card():
    pending = fetch_all("""
        SELECT * FROM address_confirmations
        WHERE status = 'pending' AND expires_at > NOW()
        ORDER BY created_at DESC
    """)

    if not pending:
        return

    for conf in pending:
        with st.sidebar.container(border=True):
            st.warning(f"📍 Action Needed — **{conf['company']}**")
            st.caption(f"For: {conf['position']}")

            if conf['address_found'] and conf['found_street']:
                st.write("**Address found:**")
                st.code(f"{conf['found_street']}\n{conf['found_plz_city']}")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Confirm", key=f"confirm_{conf['execution_id']}"):
                        success = _confirm_address(
                            conf['execution_id'],
                            conf['resume_webhook_url'],
                            conf['found_street'],
                            conf['found_plz_city']
                        )
                        if success:
                            time.sleep(1.5)
                            st.rerun()
                with col2:
                    if st.button("✏️ Edit", key=f"edit_{conf['execution_id']}"):
                        st.session_state[f"editing_{conf['execution_id']}"] = True
            else:
                st.error("Address not found. Please enter:")
                st.session_state[f"editing_{conf['execution_id']}"] = True

            if st.session_state.get(f"editing_{conf['execution_id']}", False):
                new_street = st.text_input(
                    "Street + Number",
                    value=conf['found_street'] or '',
                    key=f"street_{conf['execution_id']}"
                )
                new_plz = st.text_input(
                    "PLZ + City",
                    value=conf['found_plz_city'] or '',
                    key=f"plz_{conf['execution_id']}"
                )
                if st.button("💾 Submit", key=f"submit_{conf['execution_id']}"):
                    if new_street and new_plz:
                        success = _confirm_address(
                            conf['execution_id'],
                            conf['resume_webhook_url'],
                            new_street,
                            new_plz
                        )
                        if success:
                            time.sleep(1.5)
                            st.rerun()
                    else:
                        st.error("Both fields required.")

def show_cover_letter_badge():
    """Shows count of cover letters generated today in the sidebar."""
    recent = fetch_all("""
        SELECT COUNT(*) as count FROM cover_letters
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """)
    count = recent[0]['count'] if recent else 0
    if count > 0:
        st.sidebar.success(f"📄 {count} cover letter{'s' if count > 1 else ''} generated today")
        if st.sidebar.button("View Cover Letters →"):
            st.switch_page("pages/cover_letters.py")

