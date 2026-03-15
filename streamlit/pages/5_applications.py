import streamlit as st
import pandas as pd
from db import fetch_all
from components import show_address_confirmation_card

st.set_page_config(page_title="Applications", layout="wide")
st.title("📂 Application Pipeline")

# Add the global sidebar confirmation card
with st.sidebar:
    show_address_confirmation_card()

search = st.text_input("🔍 Search Company or Position")

# FIXED: Parameterized query to prevent SQL Injection
if search:
    apps = fetch_all(
        """SELECT company, position, language, final_score, iterations, 
           status, created_at FROM applications 
           WHERE company ILIKE %s OR position ILIKE %s 
           ORDER BY created_at DESC""",
        (f"%{search}%", f"%{search}%")
    )
else:
    apps = fetch_all(
        """SELECT company, position, language, final_score, iterations, 
           status, created_at FROM applications 
           ORDER BY created_at DESC"""
    )

if apps:
    df = pd.DataFrame(apps)
    
    st.dataframe(
        df,
        column_config={
            "company": "Company",
            "position": "Position",
            "language": "Lang",
            # FIXED: Formatted the score to look like a clean percentage (e.g., 87%)
            "final_score": st.column_config.ProgressColumn("Score", format="%d%%", min_value=0, max_value=100),
            "iterations": "Loops",
            "status": "Status",
            "created_at": st.column_config.DatetimeColumn("Date", format="D MMM YYYY")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No applications found in the database.")