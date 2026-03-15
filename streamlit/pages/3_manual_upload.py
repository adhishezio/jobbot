import streamlit as st
import requests
import time
import os
import json
from db import fetch_one, execute
from components import show_address_confirmation_card
import google.generativeai as genai
from PIL import Image
import io

st.set_page_config(page_title="Upload Screenshot", page_icon="📸", layout="wide")
st.title("📸 Upload Job Posting")

with st.sidebar:
    show_address_confirmation_card()

# --- GEMINI VISION EXTRACTION ---
def extract_job_details(uploaded_files):
    """Sends multiple images to Gemini to extract structured job data."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ GEMINI_API_KEY is missing from your environment variables!")
        return None
        
    genai.configure(api_key=api_key)
    # Flash is incredibly fast and highly capable for document vision
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # Convert Streamlit uploads into PIL Images for Gemini
    images = []
    for file in uploaded_files:
        image = Image.open(io.BytesIO(file.getvalue()))
        images.append(image)

    prompt = """
    Analyze these screenshots of a job posting. They may be out of order.
    Extract the information into a valid JSON object with EXACTLY these keys:
    - "company_name": The hiring company. If not at the top, deduce it from the "about us" section or email domains.
    - "position": The specific job title.
    - "jd_raw": The complete, combined text of the job description. Include responsibilities, requirements, qualifications, and the "about the company" text. Merge it logically into one clean text block.

    Respond ONLY with the raw JSON object. Do not include markdown formatting like ```json or any other text.
    """
    
    try:
        response = model.generate_content([prompt, *images])
        # Clean up the response in case Gemini includes markdown code blocks anyway
        cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(cleaned_text)
    except Exception as e:
        st.error(f"Failed to extract text using Gemini: {e}")
        return None

# --- STEP 1: UPLOAD ---
# Notice: accept_multiple_files=True allows you to select 2+ screenshots at once!
uploaded_files = st.file_uploader("Upload screenshots of the job posting", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

if 'extracted_data' not in st.session_state:
    st.session_state['extracted_data'] = None

if uploaded_files:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.write(f"**{len(uploaded_files)} image(s) uploaded.**")
        # Display the first image just as a preview
        st.image(uploaded_files[0], caption="Preview of First Screenshot", use_container_width=True)
        
        if st.button("🔍 Extract Job Details with Gemini", type="primary"):
            with st.spinner("Gemini is reading your screenshots..."):
                result = extract_job_details(uploaded_files)
                if result:
                    st.session_state['extracted_data'] = result
                    st.rerun()

    # --- STEP 2: REVIEW & SEND TO N8N ---
    with col2:
        if st.session_state['extracted_data']:
            st.success("Extraction Complete! Review and edit if necessary:")
            
            data = st.session_state['extracted_data']
            
            company = st.text_input("Company Name", value=data.get('company_name', ''))
            position = st.text_input("Position Title", value=data.get('position', ''))
            
            # FIXED: Added Department field
            department = st.text_input("Department / Hiring Manager (Optional)", value=data.get('department', ''))
            
            # FIXED: Set German (index 0) as the default and added format_func
            language = st.radio("Language", ["de", "en"], horizontal=True, index=0,
                                format_func=lambda x: "🇩🇪 German" if x == "de" else "🇬🇧 English")
            
            jd_raw = st.text_area("Job Description", value=data.get('jd_raw', ''), height=300)
            
            if st.button("🚀 Confirm & Send to n8n Pipeline"):
                payload = {
                    "company_name": company,
                    "position": position,
                    "department": department, # FIXED: Added department to payload
                    "language": language,
                    "jd_raw": jd_raw
                }
                
                with st.status("Starting pipeline...") as status:
                    try:
                        n8n_base = os.environ.get("N8N_WEBHOOK_BASE_URL", "http://n8n:5678/webhook")
                        webhook_url = f"{n8n_base}/generate-cover-letter"
                        
                        response = requests.post(webhook_url, json=payload, timeout=20)
                        
                        if response.status_code == 200:
                            status.update(label="✅ Pipeline Started!", state="complete")
                            st.session_state['pending_app_company'] = company
                            st.session_state['app_start_time'] = time.time()
                            st.session_state['extracted_data'] = None 
                            time.sleep(1)
                            st.rerun()
                        else:
                            status.update(label=f"Failed: {response.status_code}", state="error")
                    except Exception as e:
                        status.update(label=f"Error: {e}", state="error")

st.divider()

# --- STEP 3: BACKGROUND POLLING ---
if 'pending_app_company' in st.session_state:
    company = st.session_state['pending_app_company']
    
    with st.spinner(f"Pipeline running for {company}. Check sidebar for address confirmation..."):
        notif = fetch_one("SELECT * FROM notifications WHERE type = 'cl_ready' AND title LIKE %s AND is_read = FALSE ORDER BY created_at DESC LIMIT 1", (f"%{company}%",))
        
        if notif:
            st.success(f"✅ Final Cover Letter Ready for {company}!")
            st.markdown(notif['message'])
            execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notif['id'],))
            st.balloons()
            del st.session_state['pending_app_company']
        else:
            if time.time() - st.session_state['app_start_time'] > 120:
                st.warning(f"⏱️ Generation timed out for {company}.")
                del st.session_state['pending_app_company']
            else:
                time.sleep(5)
                st.rerun()