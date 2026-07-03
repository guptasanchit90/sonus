from __future__ import annotations

import contextlib
import json
import os

from mcp.server.fastmcp import FastMCP
from starlette.routing import Route

import src.engines  # noqa: F401
from src.engines.base import discover as discover_tts
from src.presets import _list_presets as _list_presets_raw
from src.utils import SFX_DIR, get_audio_duration
from src.voice_descriptions import get_model_voices

TTS_ENGINES = discover_tts()

mcp = FastMCP("sonus")


def _build_manifest(*, available_only: bool = False) -> dict[str, dict]:
    manifest = {}
    for engine in TTS_ENGINES:
        for model in engine.list_models():
            if available_only and not model.get("available", False):
                continue
            eid = model["id"]
            manifest[eid] = {
                "id": eid,
                "name": model.get("name", eid),
                "engine": model["engine"],
                "mode": model.get("mode", "speaker"),
                "capabilities": model.get("capabilities", []),
                "description": model.get("description", ""),
                "available": model.get("available", False),
                "languages": model.get("languages", []),
                "install": model.get("install"),
                "size": model.get("size", ""),
            }
    return manifest


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("sonus://models")
def get_models() -> str:
    manifest = _build_manifest(available_only=False)
    models = []
    for eid, entry in manifest.items():
        models.append(
            {
                "id": eid,
                "name": entry.get("name", eid),
                "engine": entry["engine"],
                "mode": entry.get("mode"),
                "capabilities": entry.get("capabilities", []),
                "languages": entry.get("languages", []),
                "available": entry.get("available", False),
                "size": entry.get("size", ""),
            }
        )
    return json.dumps({"object": "list", "data": models}, indent=2)


@mcp.resource("sonus://voices/{model_id}")
def get_voices(model_id: str) -> str:
    manifest = _build_manifest(available_only=False)
    entry = manifest.get(model_id)
    if not entry:
        available = sorted(manifest)
        return json.dumps(
            {"error": f"Model '{model_id}' not found.", "available_models": available}, indent=2
        )

    engine_name = entry["engine"]
    mode = entry.get("mode", "speaker")

    voices = get_model_voices(model_id)
    if voices:
        return json.dumps(
            {
                "model": model_id,
                "engine": engine_name,
                "mode": mode,
                "voice_count": len(voices),
                "object": "list",
                "data": voices,
            },
            indent=2,
        )

    for engine in TTS_ENGINES:
        if engine.engine_name == engine_name:
            raw = engine.list_voices()
            flat = []
            for key, items in raw.items():
                if not isinstance(items, list):
                    continue
                category = "built_in" if key not in ("built_in", "cloneable") else key
                language = None if key in ("built_in", "cloneable") else key
                for item in items:
                    v = {"id": item, "category": category}
                    if language:
                        v["language"] = language
                    flat.append(v)
            return json.dumps(
                {
                    "model": model_id,
                    "engine": engine_name,
                    "mode": mode,
                    "voice_count": len(flat),
                    "object": "list",
                    "data": flat,
                },
                indent=2,
            )

    return json.dumps({"error": f"No voices found for model '{model_id}'"}, indent=2)


@mcp.resource("sonus://presets")
def get_presets() -> str:
    presets = _list_presets_raw()
    return json.dumps({"object": "list", "data": presets}, indent=2)


@mcp.resource("sonus://sfx")
def get_sfx() -> str:
    data = []
    if os.path.exists(SFX_DIR):
        for fname in sorted(os.listdir(SFX_DIR)):
            if fname.startswith("."):
                continue
            path = os.path.join(SFX_DIR, fname)
            if not os.path.isfile(path):
                continue
            data.append(
                {
                    "name": fname,
                    "size": os.path.getsize(path),
                    "duration": round(get_audio_duration(path), 1),
                    "format": os.path.splitext(fname)[1].lower(),
                }
            )
    return json.dumps({"object": "list", "data": data}, indent=2)


@mcp.resource("sonus://formats")
def get_formats() -> str:
    spec = {
        "format": "SSML (Speech Synthesis Markup Language)",
        "detection": "Input starting with <speak is parsed as SSML. Otherwise plain text.",
        "root_element": {
            "tag": "speak",
            "required": True,
            "description": "Root element wrapping all SSML content.",
        },
        "supported_tags": [
            {
                "tag": "voice",
                "attributes": {"name": "Voice ID (e.g. af_heart, serena)"},
                "description": "Switch voice mid-speech. Use IDs from sonus://voices/{model_id}.",
                "example": '<voice name="af_heart">Hello</voice>',
            },
            {
                "tag": "prosody",
                "attributes": {
                    "rate": "x-slow, slow, medium, fast, x-fast, +/-N%, or float",
                    "temperature": "Float (e.g. 0.7)",
                },
                "description": "Adjust speech rate and temperature.",
                "example": '<prosody rate="slow" temperature="0.5">Slow speech</prosody>',
            },
            {
                "tag": "break",
                "attributes": {"time": "Duration e.g. 500ms, 1.5s (default 0.5s)"},
                "description": "Insert silence/pause.",
                "example": '<break time="1s"/>',
            },
            {
                "tag": "p",
                "description": "Paragraph break. Inserts ~0.6s silence.",
                "example": "<p>First paragraph.</p><p>Second paragraph.</p>",
            },
            {
                "tag": "s",
                "description": "Sentence break. Inserts ~0.3s silence.",
                "example": "<s>First sentence.</s><s>Second sentence.</s>",
            },
            {
                "tag": "sub",
                "attributes": {"alias": "Text to speak instead"},
                "description": "Speak alias text instead of element content.",
                "example": '<sub alias="World Health Organization">WHO</sub>',
            },
            {
                "tag": "say-as",
                "attributes": {"interpret-as": "characters or spell-out"},
                "description": "Spell out text character by character.",
                "example": '<say-as interpret-as="characters">hello</say-as>',
            },
            {
                "tag": "audio",
                "attributes": {
                    "src": "URL (http/https) or filename from SFX directory",
                    "fallback_text": "Optional text to synthesize if audio source fails.",
                },
                "description": "Insert audio (SFX or URL). Falls back to TTS if source fails.",
                "example": '<audio src="door_creak.wav">*door creaks*</audio>',
            },
        ],
        "voice_switching": {
            "description": 'Use <voice name="..."> tags for multi-character dialogue.',
            "example": '<speak><voice name="af_bella">Hi!</voice><voice name="am_michael">Hello.</voice></speak>',  # noqa: E501
        },
        "response_formats": {
            "mp3": "Default. High-quality compressed audio.",
            "wav": "Uncompressed PCM WAV.",
            "pcm": "Raw PCM s16le audio.",
        },
        "notes": [
            "Plain text is auto-detected — no SSML needed for simple cases.",
            "voice param is required (default); SSML voice elements override per segment.",
            "Speed range: 0.25–4.0. Temperature range: 0.0–1.0.",
            "Clone voices from voices/ dir with clone-mode models (qwen-clone*, chatterbox*).",
            "SFX files can be referenced by filename in <audio> src.",
        ],
    }
    return json.dumps(spec, indent=2)


# ---------------------------------------------------------------------------
# Tools (optional — LLM can reason from resources alone)
# ---------------------------------------------------------------------------


@mcp.tool()
def preview_voice(model_id: str, voice_id: str) -> str:
    manifest = _build_manifest(available_only=False)
    if model_id not in manifest:
        return json.dumps(
            {
                "error": f"Model '{model_id}' not found.",
                "available_models": sorted(manifest),
            },
            indent=2,
        )

    voices = get_model_voices(model_id)
    if not voices:
        return json.dumps(
            {
                "model": model_id,
                "voice_id": voice_id,
                "note": "No descriptions for this model. Browse with sonus://voices/{model_id}.",
            },
            indent=2,
        )

    for v in voices:
        if v["id"] == voice_id:
            return json.dumps(
                {
                    "model": model_id,
                    "voice_id": voice_id,
                    "gender": v.get("gender"),
                    "age_tier": v.get("age_tier"),
                    "tone_tags": v.get("tone_tags", []),
                    "quality_grade": v.get("quality_grade"),
                    "description": v.get("description"),
                    "preview_text": v.get("description", "").split(".")[0] + ".",
                },
                indent=2,
            )

    return json.dumps(
        {
            "error": f"Voice '{voice_id}' not found for model '{model_id}'.",
            "available_voices": [v["id"] for v in voices],
        },
        indent=2,
    )


@mcp.tool()
def suggest_voice_for_character(
    model_id: str,
    gender: str = "",
    age: str = "",
    tone: str = "",
    language: str = "",
) -> str:
    voices = get_model_voices(model_id)
    if not voices:
        return json.dumps(
            {
                "model": model_id,
                "result": "no_descriptions",
                "note": "No descriptions for this model. Browse with sonus://voices/{model_id}.",
            },
            indent=2,
        )

    scored = []
    for v in voices:
        score = 0
        if gender and v.get("gender") == gender:
            score += 2
        if age and v.get("age_tier") == age:
            score += 2
        if tone and tone in v.get("tone_tags", []):
            score += 3
        if language and v.get("locale", "").startswith(language):
            score += 2
        if score > 0:
            scored.append((score, v))

    scored.sort(key=lambda x: -x[0])
    matches = [
        {
            "voice_id": v["id"],
            "match_score": s,
            "gender": v.get("gender"),
            "age_tier": v.get("age_tier"),
            "tone_tags": v.get("tone_tags", []),
            "description": v.get("description"),
        }
        for s, v in scored[:5]
    ]
    if not matches:
        return json.dumps(
            {
                "model": model_id,
                "result": "no_match",
                "note": "Try broader criteria or browse all voices at sonus://voices/{model_id}.",
            },
            indent=2,
        )

    return json.dumps({"model": model_id, "result": "matches", "data": matches}, indent=2)


# ---------------------------------------------------------------------------
# Streamable HTTP transport — mountable Starlette app
# ---------------------------------------------------------------------------


def create_mcp_handler():
    mcp.settings.streamable_http_path = "/mcp"
    sec = mcp.settings.transport_security
    if sec is not None:
        sec.enable_dns_rebinding_protection = False
    app = mcp.streamable_http_app()
    route = app.routes[0]
    assert isinstance(route, Route)
    return route.app


@contextlib.asynccontextmanager
async def mcp_lifespan(app):
    if mcp._session_manager is not None:
        async with mcp._session_manager.run():
            yield
    else:
        yield
