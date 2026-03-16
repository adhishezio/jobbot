import streamlit as st


def apply_ui_theme():
    if st.session_state.get("_ui_theme_applied"):
        return

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(255, 211, 163, 0.28), transparent 26%),
                radial-gradient(circle at top left, rgba(147, 197, 253, 0.24), transparent 24%),
                linear-gradient(180deg, #f7fbff 0%, #eef6f5 100%);
        }
        [data-testid="stHeader"] {
            background: rgba(247, 251, 255, 0.75);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f4fbff 0%, #eef5ff 100%);
            border-right: 1px solid rgba(15, 23, 42, 0.06);
        }
        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(15, 23, 42, 0.06);
            padding: 0.9rem 1rem;
            border-radius: 18px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.05);
        }
        [data-testid="stForm"], .stContainer, [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 18px;
        }
        .stButton > button, .stDownloadButton > button {
            border-radius: 999px;
            border: none;
            background: linear-gradient(135deg, #3a8dde 0%, #56c4a8 100%);
            color: white;
            font-weight: 600;
            box-shadow: 0 10px 24px rgba(58, 141, 222, 0.18);
        }
        .stButton > button[kind="secondary"] {
            background: white;
            color: #1f4d6b;
            border: 1px solid rgba(31, 77, 107, 0.16);
            box-shadow: none;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.6rem;
        }
        .stTabs [data-baseweb="tab"] {
            background: rgba(255, 255, 255, 0.74);
            border-radius: 999px;
            padding: 0.4rem 1rem;
            border: 1px solid rgba(15, 23, 42, 0.05);
        }
        .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg, rgba(58, 141, 222, 0.14), rgba(86, 196, 168, 0.18));
            color: #163b54;
        }
        div[data-testid="stTextArea"] textarea, div[data-testid="stTextInput"] input {
            background: rgba(255, 255, 255, 0.92);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_ui_theme_applied"] = True
