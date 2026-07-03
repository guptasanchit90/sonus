from __future__ import annotations

import json
from pathlib import Path

_DESCRIPTIONS_FILE = Path(__file__).parent / "voice_descriptions.json"


def _load() -> dict:
    if _DESCRIPTIONS_FILE.exists():
        try:
            with open(_DESCRIPTIONS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_voice_description(engine: str, voice_id: str) -> dict | None:
    descriptions = _load()
    for entry in descriptions.get("_by_model", {}).values():
        if entry.get("engine") == engine:
            for v in entry.get("voices", []):
                if v["id"] == voice_id:
                    return v
    return None


def get_model_voices(model_id: str) -> list[dict] | None:
    descriptions = _load()
    by_model = descriptions.get("_by_model", {})
    for entry in by_model.values():
        if model_id in entry.get("models", []):
            return entry.get("voices", [])
    return None


def get_engine_voices_for_model(engine_name: str, model_mode: str, voice_id: str) -> dict | None:
    return get_voice_description(engine_name, voice_id)


def get_all_descriptions() -> dict:
    return _load()
