import json
import os
import shutil
import subprocess
from datetime import datetime


BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "/backup")
HOST_BACKUP_ROOT = os.environ.get("HOST_BACKUP_ROOT", r"F:\jobbot_backup")
CURRENT_DIR = os.path.join(BACKUP_ROOT, "current")
TEMP_DIR = os.path.join(BACKUP_ROOT, "_current_tmp")
STATUS_PATH = "/files/backup_status.json"
DRIVE_MANIFEST_PATH = os.path.join(CURRENT_DIR, "meta", "backup_manifest.json")
ENV_PATH = "/workspace_env/.env"


def backup_available():
    return os.path.isdir(BACKUP_ROOT)


def load_backup_status():
    for path in (DRIVE_MANIFEST_PATH, STATUS_PATH):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _copy_tree_if_exists(source, destination):
    if not os.path.exists(source):
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _run_pg_dump(target_path):
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "postgres")
    command = [
        "pg_dump",
        "-h",
        os.environ.get("POSTGRES_HOST", "postgres"),
        "-p",
        os.environ.get("POSTGRES_PORT", "5432"),
        "-U",
        os.environ.get("POSTGRES_USER", "postgres"),
        "-d",
        os.environ.get("POSTGRES_DB", "jobbot_db"),
        "--no-owner",
        "--no-privileges",
        "-f",
        target_path,
    ]
    subprocess.run(command, check=True, env=env)


def run_backup(trigger="manual_ui"):
    if not backup_available():
        raise RuntimeError("The external backup drive is not mounted inside the Streamlit container.")

    if os.path.isdir(TEMP_DIR):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)

    _ensure_dir(os.path.join(TEMP_DIR, "database"))
    _ensure_dir(os.path.join(TEMP_DIR, "meta"))

    dump_path = os.path.join(TEMP_DIR, "database", "jobbot.sql")
    _run_pg_dump(dump_path)

    _copy_tree_if_exists("/files", os.path.join(TEMP_DIR, "files"))
    _copy_tree_if_exists("/secrets", os.path.join(TEMP_DIR, "secrets"))
    _copy_tree_if_exists("/n8n_exports", os.path.join(TEMP_DIR, "n8n"))
    if os.path.exists(ENV_PATH):
        shutil.copy2(ENV_PATH, os.path.join(TEMP_DIR, "meta", ".env"))

    timestamp = datetime.now().astimezone().isoformat()
    manifest = {
        "created_at": timestamp,
        "trigger": trigger,
        "backup_root": HOST_BACKUP_ROOT,
        "snapshot_root": os.path.join(HOST_BACKUP_ROOT, "current"),
        "postgres_user": os.environ.get("POSTGRES_USER", "postgres"),
        "postgres_database": os.environ.get("POSTGRES_DB", "jobbot_db"),
        "included": [
            "database SQL dump",
            "files directory",
            "secrets directory",
            ".env",
            "n8n workflow exports",
        ],
    }

    with open(os.path.join(TEMP_DIR, "meta", "backup_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    if os.path.isdir(CURRENT_DIR):
        shutil.rmtree(CURRENT_DIR, ignore_errors=True)
    os.replace(TEMP_DIR, CURRENT_DIR)

    with open(STATUS_PATH, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    return manifest
