import streamlit as st

from ai_settings import (
    MODEL_OPTIONS,
    add_gemini_api_key,
    available_gemini_key_slots,
    load_ai_settings,
    reset_ai_settings,
    save_ai_settings,
)
from components import show_address_confirmation_card
from master_resume_store import load_master_resume, resume_metadata, save_master_resume
from ui import apply_ui_theme


st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
apply_ui_theme()
st.title("⚙️ Settings")
st.caption("Choose the AI provider and models for cover-letter generation. Extraction stays on Gemini API.")
st.session_state["current_page"] = "settings"

with st.sidebar:
    show_address_confirmation_card()


settings = load_ai_settings()
slots = available_gemini_key_slots()
slot_labels = list(slots.keys()) or ["GEMINI_API_KEY1"]

if "settings_master_resume_text" not in st.session_state:
    st.session_state["settings_master_resume_text"] = load_master_resume()

provider_toggle = st.toggle(
    "Use Vertex AI For Cover-Letter Generation",
    value=settings["ai_provider"] == "vertex",
    help="Turn this off to use the Gemini API keys instead.",
)
provider = "vertex" if provider_toggle else "google_api"

st.info(
    "Extraction continues to use the Gemini API path so it stays on the free-tier setup. "
    "The switch below changes the Generator, Critic, and Refiner pipeline."
)

if provider == "google_api":
    st.subheader("Gemini API")
    selected_slot = st.selectbox(
        "Active Gemini API Key Slot",
        slot_labels,
        index=slot_labels.index(settings["gemini_key_slot"]) if settings["gemini_key_slot"] in slot_labels else 0,
        help="Only the slot label is shown here. The real key value stays local.",
    )
    google_generator_model = st.selectbox(
        "Generator Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["google_generator_model"]),
        key="settings_google_generator_model",
    )
    google_critic_model = st.selectbox(
        "Critic Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["google_critic_model"]),
        key="settings_google_critic_model",
    )
    google_refiner_model = st.selectbox(
        "Refiner Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["google_refiner_model"]),
        key="settings_google_refiner_model",
    )
    vertex_generator_model = settings["vertex_generator_model"]
    vertex_critic_model = settings["vertex_critic_model"]
    vertex_refiner_model = settings["vertex_refiner_model"]

    with st.expander("Add Gemini API Key"):
        new_key = st.text_input(
            "New Gemini API Key",
            type="password",
            key="settings_new_gemini_key",
            help="The key is stored locally and only its slot label will appear in the UI.",
        )
        if st.button("Add Key", use_container_width=True):
            try:
                added_label = add_gemini_api_key(new_key)
                st.success(f"Saved locally as {added_label}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save the key: {exc}")
else:
    st.subheader("Vertex AI")
    selected_slot = settings["gemini_key_slot"]
    google_generator_model = settings["google_generator_model"]
    google_critic_model = settings["google_critic_model"]
    google_refiner_model = settings["google_refiner_model"]
    st.caption("Vertex AI does not need an API key slot here because it uses the service account setup.")
    vertex_generator_model = st.selectbox(
        "Generator Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["vertex_generator_model"]),
        key="settings_vertex_generator_model",
    )
    vertex_critic_model = st.selectbox(
        "Critic Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["vertex_critic_model"]),
        key="settings_vertex_critic_model",
    )
    vertex_refiner_model = st.selectbox(
        "Refiner Model",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(settings["vertex_refiner_model"]),
        key="settings_vertex_refiner_model",
    )

save_col, reset_col = st.columns(2)
if save_col.button("Save Settings", type="primary", use_container_width=True):
    save_ai_settings(
        {
            "ai_provider": provider,
            "gemini_key_slot": selected_slot,
            "google_generator_model": google_generator_model,
            "google_critic_model": google_critic_model,
            "google_refiner_model": google_refiner_model,
            "vertex_generator_model": vertex_generator_model,
            "vertex_critic_model": vertex_critic_model,
            "vertex_refiner_model": vertex_refiner_model,
        }
    )
    st.success("Settings saved. The next cover-letter run will use these selections.")

if reset_col.button("Reset To Default", use_container_width=True):
    reset_ai_settings()
    st.success("Settings reset to the default provider and models.")
    st.rerun()

st.divider()
st.subheader("Master Resume Editor")
st.caption(
    "Edit the main resume text JobBot uses for match scoring and cover-letter evidence. "
    "The next cover-letter run will use this updated file directly."
)

resume_meta = resume_metadata()
last_updated = (
    resume_meta["last_modified"].strftime("%d %b %Y %H:%M")
    if resume_meta["last_modified"]
    else "Not saved yet"
)
st.caption(
    f"Source: `{resume_meta['path']}` | Last updated: {last_updated} | "
    f"{resume_meta['line_count']} lines | {resume_meta['char_count']} characters"
)
st.info(
    "You do not need to rebuild Docker after saving here. JobBot reads this mounted file directly on the next run."
)

st.text_area(
    "Master Resume / Experience Source",
    key="settings_master_resume_text",
    height=460,
    help="Keep this structured and up to date. Add projects, experience, skills, achievements, and education here.",
)

resume_save_col, resume_reload_col = st.columns(2)
if resume_save_col.button("Save Resume And Apply", type="primary", use_container_width=True):
    try:
        result = save_master_resume(st.session_state["settings_master_resume_text"])
        backup_note = f" Backup saved to `{result['backup_path']}`." if result.get("backup_path") else ""
        st.success(
            "Master resume updated successfully. The next cover-letter generation will use it immediately."
            + backup_note
        )
        st.session_state["settings_master_resume_text"] = load_master_resume()
        st.rerun()
    except Exception as exc:
        st.error(f"Could not save the master resume: {exc}")

if resume_reload_col.button("Reload Resume From Disk", use_container_width=True):
    st.session_state["settings_master_resume_text"] = load_master_resume()
    st.success("Reloaded the latest saved master resume from disk.")
    st.rerun()
