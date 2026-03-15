import streamlit as st
from components import show_address_confirmation_card

# This sets up the whole browser tab
st.set_page_config(page_title="JobBot AI", page_icon="🤖", layout="wide")

# Main page content
st.title("🤖 Welcome to JobBot AI")
st.write("Welcome to your automated job application engine!")
st.write("👈 Use the sidebar menu on the left to start a new application or view past ones.")

# This forces the Address Confirmation card to always show up in the sidebar
# no matter which page you navigate to!
with st.sidebar:
    st.divider()
    show_address_confirmation_card()