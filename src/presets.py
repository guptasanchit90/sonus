import json
import os
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

PRESETS_DIR = os.path.join(os.getcwd(), "presets")
os.makedirs(PRESETS_DIR, exist_ok=True)

presets_router = APIRouter(tags=["presets"])


def _sanitize_name(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    return safe[:100] if safe else ""


def _list_presets() -> list[dict]:
    presets = []
    for fname in sorted(os.listdir(PRESETS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(PRESETS_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        config = data.get("config", {})
        presets.append(
            {
                "name": data.get("name", fname[:-5]),
                "description": data.get("description", ""),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "preview": _build_preview(config),
                "size": os.path.getsize(path),
            }
        )
    presets.sort(key=lambda p: p["updated_at"], reverse=True)
    return presets


def _build_preview(config: dict) -> str:
    parts = []
    if config.get("blendMode") and config.get("blendSelections"):
        sel = config["blendSelections"]
        parts.append("Blend: " + ", ".join(f"{k}:{v:.2f}" for k, v in sel.items()))
    elif config.get("speaker_name"):
        parts.append("Voice: " + config["speaker_name"])
    if config.get("voice_description"):
        desc = config["voice_description"][:40]
        parts.append("Prompt: " + desc + ("..." if len(config["voice_description"]) > 40 else ""))
    if config.get("model"):
        parts.append("Model: " + config["model"])
    return " | ".join(parts) if parts else "(empty)"


def _preset_path(name: str) -> str:
    return os.path.join(PRESETS_DIR, name + ".json")


def _load_preset(name: str) -> dict:
    path = _preset_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    with open(path) as f:
        return json.load(f)


def _save_preset(name: str, data: dict):
    path = _preset_path(name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ── Routes ────────────────────────────────────────────────────────────────


class PresetSaveBody(BaseModel):
    name: str = ""
    description: str = ""
    config: dict


class PresetRenameBody(BaseModel):
    new_name: str


class PresetUpdateBody(BaseModel):
    description: str = ""


@presets_router.get("/presets", summary="List all presets")
def list_presets():
    return _list_presets()


@presets_router.get("/presets/{name:path}", summary="Get a preset")
def get_preset(name: str):
    return _load_preset(name)


@presets_router.post("/presets", summary="Save a preset")
def save_preset(body: PresetSaveBody):
    name = _sanitize_name(body.name.strip())
    if not name:
        name = "Preset " + time.strftime("%b %d %H:%M")
    path = _preset_path(name)
    if os.path.exists(path):
        base = name
        idx = 2
        while os.path.exists(_preset_path(f"{base} ({idx})")):
            idx += 1
        name = f"{base} ({idx})"
    now = time.time()
    data = {
        "name": name,
        "description": body.description.strip() if body.description else "",
        "created_at": now,
        "updated_at": now,
        "config": body.config,
    }
    _save_preset(name, data)
    return {"name": name, "presets": _list_presets()}


@presets_router.put("/presets/{name:path}", summary="Rename a preset")
def rename_preset(name: str, body: PresetRenameBody):
    _load_preset(name)  # ensure exists
    new_name = _sanitize_name(body.new_name.strip())
    if not new_name:
        raise HTTPException(status_code=400, detail="New name must not be empty")
    old_path = _preset_path(name)
    new_path = _preset_path(new_name)
    if old_path == new_path:
        return {"name": name}
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail=f"Preset '{new_name}' already exists")
    data = _load_preset(name)
    data["name"] = new_name
    data["updated_at"] = time.time()
    os.remove(old_path)
    _save_preset(new_name, data)
    return {"name": new_name, "presets": _list_presets()}


@presets_router.put("/presets/{name:path}/description", summary="Update preset description")
def update_preset_description(name: str, body: PresetUpdateBody):
    data = _load_preset(name)
    data["description"] = body.description.strip() if body.description else ""
    data["updated_at"] = time.time()
    _save_preset(name, data)
    return {"name": name, "description": data["description"]}


@presets_router.delete("/presets/{name:path}", summary="Delete a preset")
def delete_preset(name: str):
    path = _preset_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    os.remove(path)
    return {"deleted": name, "presets": _list_presets()}
