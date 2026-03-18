from datetime import datetime

import streamlit as st

from backup_runtime import backup_available, load_backup_status, run_backup
from components import show_address_confirmation_card
from ui import apply_ui_theme


BACKUP_TARGET = r"F:\jobbot_backup\current"


def _format_timestamp(value):
    if not value:
        return "Never"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %b %Y %H:%M")
    except ValueError:
        return value


st.set_page_config(page_title="Backups", page_icon="💾", layout="wide")
apply_ui_theme()
st.title("💾 Backup & Recovery")

with st.sidebar:
    show_address_confirmation_card()

status = load_backup_status()

st.markdown(
    """
    Backups are handled from the Windows host, not from inside the container.
    That keeps the external-drive copy predictable and makes restores easier if this PC fails.

    Current backup target:
    """
)
st.code(BACKUP_TARGET, language="text")

metric_col1, metric_col2 = st.columns(2)
metric_col1.metric("Last Host Backup", _format_timestamp(status.get("created_at") if status else None))
metric_col2.metric("Latest Snapshot", status.get("snapshot_root") if status else "Not found yet")

if status:
    st.success("A verified host-side backup status file was found.")
    st.json(status)
else:
    st.warning("No verified host-side backup status found yet. Run the Windows backup script once.")

st.subheader("Manual Backup")
manual_col1, manual_col2 = st.columns([1, 1])
if manual_col1.button("Run Manual Backup Now", type="primary", use_container_width=True):
    with st.spinner("Creating the rotating backup on the external drive..."):
        try:
            manifest = run_backup(trigger="manual_ui")
            st.success(f"Backup completed at {manifest['created_at']}.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

manual_col2.metric("Drive Mounted", "Yes" if backup_available() else "No")

st.write("You can also run the same backup from the Windows host machine:")
st.code(
    r"powershell -ExecutionPolicy Bypass -File .\scripts\backup_jobbot.ps1",
    language="powershell",
)
st.caption("You can also double-click `scripts\\run_backup.cmd` from Explorer.")

st.subheader("Automatic Backup")
st.write("Register a Windows Scheduled Task that runs every 2 days at midnight:")
st.code(
    r"powershell -ExecutionPolicy Bypass -File .\scripts\register_backup_task.ps1",
    language="powershell",
)

st.subheader("What Gets Backed Up")
st.markdown(
    """
    - PostgreSQL database dump
    - `/files` with resumes, cover letters, and local job records
    - `/secrets` for Gmail OAuth tokens
    - local `n8n` workflow exports
    - `.env`
    """
)

st.subheader("Restore Notes")
st.markdown(
    """
    1. Clone the repo on the new machine.
    2. Copy the backup contents into the project folders.
    3. Restore the SQL dump into PostgreSQL.
    4. Start the Docker stack again.
    """
)
