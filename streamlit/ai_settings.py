import json
import os
from pathlib import Path

from db import delete_setting, fetch_setting, save_setting


SETTINGS_DEFAULTS = {
    "ai_provider": "vertex",
    "gemini_key_slot": "GEMINI_API_KEY1",
    "google_generator_model": "gemini-2.5-flash",
    "google_critic_model": "gemini-2.5-flash",
    "google_refiner_model": "gemini-2.5-flash",
    "vertex_generator_model": "gemini-2.5-pro",
    "vertex_critic_model": "gemini-2.5-flash",
    "vertex_refiner_model": "gemini-2.5-pro",
}

SETTINGS_KEYS = tuple(SETTINGS_DEFAULTS.keys())

MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]


def _keys_file_path():
    for path in (
        Path("/secrets/gemini_api_keys.json"),
        Path("secrets/gemini_api_keys.json"),
    ):
        if path.parent.exists():
            return path
    return Path("secrets/gemini_api_keys.json")


def _env_keys():
    keys = {}
    env_names = [
        ("GEMINI_API_KEY1", os.environ.get("GEMINI_API_KEY") or ""),
        ("GEMINI_API_KEY2", os.environ.get("GEMINI_API_KEY2") or ""),
        ("GEMINI_API_KEY3", os.environ.get("GEMINI_API_KEY3") or ""),
    ]
    for label, value in env_names:
        value = (value or "").strip()
        if value:
            keys[label] = value
    return keys


def _read_custom_key_store():
    path = _keys_file_path()
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except Exception:
        return []
    return []


def _write_custom_key_store(keys):
    path = _keys_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def available_gemini_key_slots():
    slots = dict(_env_keys())
    custom_keys = _read_custom_key_store()
    next_index = 4
    for value in custom_keys:
        slots[f"GEMINI_API_KEY{next_index}"] = value
        next_index += 1
    return slots


def resolve_gemini_api_key(slot_label=None):
    slots = available_gemini_key_slots()
    if slot_label and slot_label in slots:
        return slots[slot_label]
    return slots.get("GEMINI_API_KEY1") or next(iter(slots.values()), "")


def add_gemini_api_key(key_value):
    value = (key_value or "").strip()
    if not value:
        raise ValueError("The API key is empty.")

    slots = available_gemini_key_slots()
    for label, existing in slots.items():
        if existing == value:
            return label

    custom_keys = _read_custom_key_store()
    custom_keys.append(value)
    _write_custom_key_store(custom_keys)
    return f"GEMINI_API_KEY{len(_env_keys()) + len(custom_keys)}"


def load_ai_settings():
    settings = dict(SETTINGS_DEFAULTS)
    for key in SETTINGS_KEYS:
        value = fetch_setting(key)
        if value:
            settings[key] = value
    if settings["gemini_key_slot"] not in available_gemini_key_slots():
        settings["gemini_key_slot"] = "GEMINI_API_KEY1"
    return settings


def save_ai_settings(settings):
    merged = dict(SETTINGS_DEFAULTS)
    merged.update(settings or {})
    for key in SETTINGS_KEYS:
        save_setting(key, merged[key])
    return merged


def reset_ai_settings():
    for key in SETTINGS_KEYS:
        delete_setting(key)
    return dict(SETTINGS_DEFAULTS)


def build_generation_ai_payload():
    settings = load_ai_settings()
    provider = settings["ai_provider"]
    if provider == "google_api":
        return {
            "ai_provider": "google_api",
            "gemini_key_slot": settings["gemini_key_slot"],
            "generator_model": settings["google_generator_model"],
            "critic_model": settings["google_critic_model"],
            "refiner_model": settings["google_refiner_model"],
        }

    return {
        "ai_provider": "vertex",
        "generator_model": settings["vertex_generator_model"],
        "critic_model": settings["vertex_critic_model"],
        "refiner_model": settings["vertex_refiner_model"],
    }
