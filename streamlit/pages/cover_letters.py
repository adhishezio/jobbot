import streamlit as st
import base64
import os
from db import fetch_all

st.set_page_config(page_title="Cover Letters", layout="wide")
st.title("📄 Generated Cover Letters")

letters = fetch_all("""
    SELECT * FROM cover_letters
    ORDER BY created_at DESC
    LIMIT 50
""")

if not letters:
    st.info("No cover letters generated yet. Start by uploading a job posting.")
    st.stop()

for letter in letters:
    pdf_path = f"/files/{letter['pdf_filename']}"
    file_exists = os.path.exists(pdf_path)

    with st.expander(
        f"{'🇩🇪' if letter['language'] == 'de' else '🇬🇧'}  {letter['company']} — {letter['position']}  |  "
        f"Score: {letter['score']}/100  |  Iterations: {letter['iterations']}  |  "
        f"{letter['created_at'].strftime('%d %b %Y %H:%M')}",
        expanded=False
    ):
        col1, col2 = st.columns([3, 1])

        with col2:
            if file_exists:
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                st.download_button(
                    label="⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=letter['pdf_filename'],
                    mime="application/pdf",
                    key=f"dl_{letter['id']}",
                    use_container_width=True
                )

                # Regenerate button placeholder
                if st.button("🔄 Regenerate", key=f"regen_{letter['id']}", use_container_width=True):
                    st.info("Trigger a new run from the main page.")
            else:
                st.error("PDF file not found on disk.")

            st.metric("Quality Score", f"{letter['score']}/100")
            st.metric("Refinement Passes", letter['iterations'] - 1)

        with col1:
            if file_exists:
                # Inline PDF preview using base64 iframe
                with open(pdf_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')

                pdf_display = f"""
                    <iframe
                        src="data:application/pdf;base64,{b64}"
                        width="100%"
                        height="700px"
                        style="border: 1px solid #333; border-radius: 4px;"
                    ></iframe>
                """
                st.markdown(pdf_display, unsafe_allow_html=True)
            else:
                # Show LaTeX source as fallback
                st.caption("PDF not found — showing LaTeX source:")
                st.code(letter['latex_source'][:2000] + "...", language="latex")
