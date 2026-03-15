import streamlit as st
import requests
import time
import os
from db import fetch_one, execute
from components import show_address_confirmation_card

st.set_page_config(page_title="New Application", page_icon="📝", layout="wide")
st.title("📝 Generate Cover Letter")

with st.sidebar:
    show_address_confirmation_card()

col1, col2 = st.columns(2)
with col1:
    company = st.text_input("Company Name")
    position = st.text_input("Position Title")
with col2:
    language = st.radio("Language", ["de", "en"], horizontal=True, format_func=lambda x: "🇩🇪 German" if x == "de" else "🇬🇧 English")
    department = st.text_input("Department / Hiring Manager (Optional)")

jd_raw = st.text_area("Job Description (Paste Raw Text)", height=300)

# Check for required fields BEFORE the button click to avoid issues
form_valid = company and position and jd_raw

if st.button("🚀 Generate Cover Letter", type="primary"):
    if not form_valid:
        st.error("Company, Position, and JD are required!")
        st.stop()
        
    payload = {
        "company_name": company,
        "position": position,
        "department": department,
        "language": language,
        "jd_raw": jd_raw
    }
    
    # Non-blocking Status container
    with st.status("Initializing n8n Pipeline...") as status:
        try:
            st.write("Sending data to Generator...")
            
            # 1. ADD TIMEOUT and use http://n8n:5678 instead of LAN_IP inside Docker network
            n8n_base = os.environ.get("N8N_WEBHOOK_BASE_URL", "http://n8n:5678/webhook")
            webhook_url = f"{n8n_base}/generate-cover-letter"
            
            # Make the request with a timeout so it doesn't hang Streamlit
            response = requests.post(webhook_url, json=payload, timeout=20)
            
            if response.status_code == 200:
                status.update(label="✅ n8n Pipeline Started!", state="complete")
                st.info("Look at the **Sidebar** right now! The Address Confirmation card is waiting for you there.")
                st.info("You don't need Telegram—you can confirm it directly on the UI.")
                st.info("The final cover letter results will appear here shortly.")
                
                # 2. Store app data in session state so we can poll in the background
                st.session_state['pending_app_company'] = company
                st.session_state['app_start_time'] = time.time()
                
                # 3. CRUCIAL: Allow a split-second for n8n to write to DB, then RERUN.
                # A rerun allows the app.py sidebar logic to load the confirmation card!
                time.sleep(1)
                st.rerun()
                
            else:
                status.update(label=f"Failed to start pipeline: Status {response.status_code}", state="error")
                
        except Exception as e:
            status.update(label=f"Error connecting to n8n: {e}", state="error")

st.divider()

# 4. Background Polling (Moved OUTSIDE the button click)
if 'pending_app_company' in st.session_state:
    company = st.session_state['pending_app_company']
    
    # Display a non-blocking spinner in the main body
    with st.spinner(f"Pipeline running for {company}. Waiting for final feedback loop..."):
        # Check notifications table for 'cl_ready'
        # strictly look for the final cover letter, ignore address requests
        notif = fetch_one("SELECT * FROM notifications WHERE type = 'cl_ready' AND title LIKE %s AND is_read = FALSE ORDER BY created_at DESC LIMIT 1", (f"%{company}%",))
        
        if notif:
            st.success(f"✅ Final Cover Letter Ready for {company}!")
            st.markdown(notif['message'])
            # Mark as read
            execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notif['id'],))
            st.balloons()
            # Clean up session state
            del st.session_state['pending_app_company']
        else:
            # Simple timeout logic
            if time.time() - st.session_state['app_start_time'] > 120: # 2 minute timeout
                st.warning(f"⏱️ Generation is taking a while for {company}. It may still be running in the background.")
                del st.session_state['pending_app_company']
            else:
                # Tell Streamlit to automatically refresh in 5 seconds to check the DB again
                time.sleep(5)
                st.rerun()