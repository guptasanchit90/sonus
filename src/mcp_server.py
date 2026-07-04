from __future__ import annotations

import contextlib
import json
import os

from mcp.server.fastmcp import FastMCP
from starlette.routing import Route

import src.engines  # noqa: F401
import src.stt  # noqa: F401
from src.engines.base import discover as discover_tts
from src.presets import _list_presets as _list_presets_raw
from src.stt.base import discover as discover_stt
from src.utils import SFX_DIR, get_audio_duration
from src.voice_descriptions import get_all_descriptions, get_model_voices

TTS_ENGINES = discover_tts()
STT_ENGINES = discover_stt()

OUTPUTS_DIR = os.path.join(os.getcwd(), "outputs", "server")

mcp = FastMCP("sonus")
import logging; logging.getLogger("mcp").setLevel(logging.WARNING)


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


def _format_sse(data: list, label: str = "list", extra: dict | None = None) -> str:
    result: dict = {"object": label, "count": len(data), "data": data}
    if extra:
        result.update(extra)
    return json.dumps(result, indent=2)


def _voices_data_for_model(model_id: str, engine_obj) -> list[dict]:
    raw = engine_obj.list_voices()
    flat = []
    for key, items in raw.items():
        if not isinstance(items, list):
            continue
        category = "built_in" if key not in ("built_in", "cloneable") else key
        language = None if key in ("built_in", "cloneable") else key
        for item in items:
            v: dict = {
                "id": item,
                "category": category,
                "model": model_id,
                "engine": engine_obj.engine_name,
            }
            if language:
                v["language"] = language
            flat.append(v)
    return flat


def _all_voices_flat() -> list[dict]:
    seen_cloneable = set()
    all_voices = []
    for engine in TTS_ENGINES:
        engine_name = engine.engine_name
        raw = engine.list_voices()
        for key, items in raw.items():
            if not isinstance(items, list):
                continue
            if key in ("built_in", "cloneable"):
                category = key
                language = None
            else:
                category = "built_in"
                language = key
            for item in items:
                if category == "cloneable":
                    if item in seen_cloneable:
                        continue
                    seen_cloneable.add(item)
                entry: dict = {"id": item, "engine": engine_name, "category": category}
                if language:
                    entry["language"] = language
                all_voices.append(entry)
    return all_voices


def _enrich_voice(entry: dict) -> dict:
    desc = get_model_voices_by_id(entry["id"], entry.get("engine", ""))
    if desc:
        for k in ("gender", "age_tier", "tone_tags", "quality_grade", "description"):
            if k in desc:
                entry[k] = desc[k]
    if entry.get("category") == "cloneable":
        from src.utils import VOICES_DIR

        path = os.path.join(VOICES_DIR, entry["id"])
        if os.path.exists(path):
            entry["size"] = os.path.getsize(path)
            entry["duration"] = round(get_audio_duration(path), 1)
            entry["url"] = f"/voice/{entry['id']}"
    return entry


def get_model_voices_by_id(voice_id: str, engine_name: str) -> dict | None:
    by_model = get_all_descriptions().get("_by_model", {})
    for entry in by_model.values():
        if entry.get("engine") == engine_name:
            for v in entry.get("voices", []):
                if v["id"] == voice_id:
                    return v
    return None


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("sonus://")
def get_root() -> str:
    return json.dumps(
        {
            "name": "Sonus MCP",
            "description": (
                "Multi-engine, offline text-to-speech server "
                "with OpenAI-compatible TTS and STT endpoints."
            ),
            "resources": {
                "sonus://": "This overview",
                "sonus://models": "TTS models with capabilities and availability",
                "sonus://voices": "All voices across every engine",
                "sonus://voices/{model_id}": "Voices for a specific model",
                "sonus://stt_models": "STT models with availability and install info",
                "sonus://engines": "All engines (TTS + STT) with model summaries",
                "sonus://sfx": "Sound effects with size/duration/format",
                "sonus://presets": "Saved voice presets",
                "sonus://outputs": "Recently generated audio outputs",
                "sonus://formats": "SSML format specification",
            },
            "tools": {
                "list_models": "List all TTS models",
                "list_voices": "List all voices across all engines",
                "list_sfx": "List all sound effects",
                "list_stt_models": "List all STT models",
                "list_outputs": "List recent generated audio outputs",
                "search_voices": "Advanced cross-engine voice search with filters",
                "preview_voice": "Get detailed description for a specific voice",
                "suggest_voice_for_character": "Find voices matching character criteria",
                "get_capabilities": "Full Sonus overview",
            },
        },
        indent=2,
    )


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
    return _format_sse(models, "model_list")


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
        return _format_sse(
            voices,
            "voice_list",
            {"model": model_id, "engine": engine_name, "mode": mode, "voice_count": len(voices)},
        )

    for engine in TTS_ENGINES:
        if engine.engine_name == engine_name:
            flat = _voices_data_for_model(model_id, engine)
            return _format_sse(
                flat,
                "voice_list",
                {"model": model_id, "engine": engine_name, "mode": mode, "voice_count": len(flat)},
            )

    return json.dumps({"error": f"No voices found for model '{model_id}'"}, indent=2)


@mcp.resource("sonus://voices")
def get_all_voices() -> str:
    all_v = _all_voices_flat()
    enriched = [_enrich_voice(v) for v in all_v]
    return _format_sse(
        enriched,
        "voice_list",
        {"voice_count": len(enriched)},
    )


@mcp.resource("sonus://presets")
def get_presets() -> str:
    presets = _list_presets_raw()
    return _format_sse(presets, "preset_list")


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
    return _format_sse(data, "sfx_list")


@mcp.resource("sonus://stt_models")
def get_stt_models() -> str:
    models = []
    for engine in STT_ENGINES:
        for m in engine.list_models():
            models.append(
                {
                    "id": m["id"],
                    "name": m.get("name", m["id"]),
                    "engine": m["engine"],
                    "mode": m.get("mode", "stt"),
                    "capabilities": m.get("capabilities", []),
                    "description": m.get("description", ""),
                    "available": m.get("available", False),
                    "languages": m.get("languages", []),
                    "size": m.get("size", ""),
                    "mlx_required": m.get("mlx_required", True),
                    "install": m.get("install"),
                }
            )
    return _format_sse(models, "stt_model_list")


@mcp.resource("sonus://engines")
def get_engines() -> str:
    engines_info = []
    for engine in TTS_ENGINES:
        name = engine.engine_name
        models = engine.list_models()
        summary = {
            "engine": name,
            "model_count": len(models),
            "models": [
                {
                    "id": m["id"],
                    "mode": m.get("mode", "speaker"),
                    "capabilities": m.get("capabilities", []),
                    "available": m.get("available", False),
                    "languages": m.get("languages", []),
                }
                for m in models
            ],
        }
        if hasattr(engine, "engine_name"):
            summary["type"] = "tts"
        engines_info.append(summary)
    for engine in STT_ENGINES:
        name = engine.engine_name
        models = engine.list_models()
        engines_info.append(
            {
                "engine": name,
                "type": "stt",
                "model_count": len(models),
                "models": [
                    {
                        "id": m["id"],
                        "mode": m.get("mode", "stt"),
                        "available": m.get("available", False),
                    }
                    for m in models
                ],
            }
        )
    return _format_sse(engines_info, "engine_list")


@mcp.resource("sonus://outputs")
def get_outputs_resource() -> str:
    data = _scan_outputs(limit=50)
    return _format_sse(data, "output_list")


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
            "example": (
                '<speak><voice name="af_bella">Hi!</voice>'
                '<voice name="am_michael">Hello.</voice></speak>'
            ),
        },
        "response_formats": {
            "mp3": "Default. High-quality compressed audio.",
            "wav": "Uncompressed PCM WAV.",
            "pcm": "Raw PCM s16le audio.",
        },
        "notes": [
            "Plain text is auto-detected - no SSML needed for simple cases.",
            "voice param is required (default); SSML voice elements override per segment.",
            "Speed range: 0.25-4.0. Temperature range: 0.0-1.0.",
            "Clone voices from voices/ dir with clone-mode models (qwen-clone*, chatterbox*).",
            "SFX files can be referenced by filename in <audio> src.",
        ],
    }
    return json.dumps(spec, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers for tools
# ---------------------------------------------------------------------------


def _scan_outputs(limit: int = 20) -> list[dict]:
    if not os.path.exists(OUTPUTS_DIR):
        return []
    entries = []
    for fname in os.listdir(OUTPUTS_DIR):
        fpath = os.path.join(OUTPUTS_DIR, fname)
        if not os.path.isfile(fpath) or fname.startswith("."):
            continue
        if fname.endswith(".json"):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in (".mp3", ".wav", ".pcm"):
            continue
        size = os.path.getsize(fpath)
        created_at = os.path.getmtime(fpath)
        params = {}
        duration = 0.0
        json_path = fpath + ".json"
        if os.path.exists(json_path):
            try:
                with open(json_path) as fh:
                    params = json.load(fh)
                duration = params.pop("_duration", 0.0)
            except (json.JSONDecodeError, OSError):
                pass
        if not duration and ext in (".wav", ".mp3"):
            duration = get_audio_duration(fpath)
        entries.append(
            {
                "name": fname,
                "size": size,
                "duration": round(duration, 1),
                "created_at": created_at,
                "url": f"/output/{fname}",
                "params": params,
            }
        )
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return entries[:limit]


def _tts_engine_for_name(name: str):
    for engine in TTS_ENGINES:
        if engine.engine_name == name:
            return engine
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_models() -> str:
    manifest = _build_manifest(available_only=False)
    return _format_sse(list(manifest.values()), "model_list")


@mcp.tool()
def list_voices() -> str:
    all_v = _all_voices_flat()
    enriched = [_enrich_voice(v) for v in all_v]
    return _format_sse(enriched, "voice_list", {"voice_count": len(enriched)})


@mcp.tool()
def list_sfx() -> str:
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
    return _format_sse(data, "sfx_list")


@mcp.tool()
def list_stt_models() -> str:
    models = []
    for stt_engine in STT_ENGINES:
        for m in stt_engine.list_models():
            models.append(
                {
                    "id": m["id"],
                    "name": m.get("name", m["id"]),
                    "engine": stt_engine.engine_name,
                    "mode": m.get("mode", "stt"),
                    "capabilities": m.get("capabilities", []),
                    "description": m.get("description", ""),
                    "available": m.get("available", False),
                    "languages": m.get("languages", []),
                    "size": m.get("size", ""),
                    "mlx_required": m.get("mlx_required", True),
                }
            )
    return _format_sse(models, "stt_model_list")


@mcp.tool()
def list_outputs() -> str:
    data = _scan_outputs(limit=20)
    return _format_sse(data, "output_list")


@mcp.tool()
def search_voices(
    query: str = "",
    language: str = "",
    gender: str = "",
    age_tier: str = "",
    quality_min: str = "",
    model_id: str = "",
    engine: str = "",
) -> str:
    if model_id:
        manifest = _build_manifest(available_only=False)
        entry = manifest.get(model_id)
        if not entry:
            return json.dumps({"error": f"Model '{model_id}' not found."}, indent=2)
        candidate_engines = {entry["engine"]}
    elif engine:
        candidate_engines = {engine}
    else:
        candidate_engines = {e.engine_name for e in TTS_ENGINES}

    descriptions = get_all_descriptions().get("_by_model", {})
    scored = []

    for group_entry in descriptions.values():
        eng = group_entry.get("engine", "")
        if eng not in candidate_engines:
            continue
        models = group_entry.get("models", [])
        if model_id and model_id not in models:
            continue
        for v in group_entry.get("voices", []):
            score = 0
            if language and v.get("locale", "").startswith(language):
                score += 3
            if gender and v.get("gender") == gender:
                score += 2
            if age_tier and v.get("age_tier") == age_tier:
                score += 2
            if query:
                ql = query.lower()
                if ql in v.get("description", "").lower():
                    score += 2
                if ql in v.get("id", "").lower():
                    score += 3
                if ql in " ".join(v.get("tone_tags", [])).lower():
                    score += 2
            if quality_min:
                quality_order = {
                    "a+": 6,
                    "a": 5,
                    "a-": 4,
                    "b+": 3,
                    "b": 3,
                    "b-": 3,
                    "c+": 2,
                    "c": 2,
                    "c-": 2,
                    "d+": 1,
                    "d": 1,
                    "d-": 1,
                    "f+": 0,
                    "f": 0,
                }
                ql_key = v.get("quality_grade", "").lower()
                ql_key = ql_key if ql_key in quality_order else "f"
                min_key = quality_min.lower()
                min_key = min_key if min_key in quality_order else "c"
                if quality_order.get(ql_key, 0) >= quality_order.get(min_key, 0):
                    score += 1
                else:
                    continue

            if score > 0:
                result = {
                    "voice_id": v["id"],
                    "score": score,
                    "engine": eng,
                    "models": models,
                    "gender": v.get("gender"),
                    "age_tier": v.get("age_tier"),
                    "language": v.get("locale"),
                    "tone_tags": v.get("tone_tags", []),
                    "quality_grade": v.get("quality_grade"),
                    "description": v.get("description", ""),
                }
                scored.append((score, result))

    scored.sort(key=lambda x: -x[0])

    if not scored:
        return json.dumps(
            {
                "result": "no_match",
                "note": "Try broader criteria or use list_voices() to see all available voices.",
            },
            indent=2,
        )

    best = [s[1] for s in scored[:10]]
    return _format_sse(
        best,
        "search_results",
        {"total_matches": len(scored), "shown": len(best)},
    )


@mcp.tool()
def preview_voice(model_id: str, voice_id: str) -> str:
    manifest = _build_manifest(available_only=False)
    if model_id not in manifest:
        return json.dumps(
            {"error": f"Model '{model_id}' not found.", "available_models": sorted(manifest)},
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


@mcp.tool()
def get_capabilities() -> str:
    manifest = _build_manifest(available_only=False)
    tts_models = list(manifest.values())

    stt_data = []
    for stt_engine in STT_ENGINES:
        for m in stt_engine.list_models():
            stt_data.append(
                {
                    "id": m["id"],
                    "engine": stt_engine.engine_name,
                    "available": m.get("available", False),
                }
            )

    available_tts = [m["id"] for m in tts_models if m.get("available")]
    available_stt = [m["id"] for m in stt_data if m.get("available")]
    all_modes = set()
    all_caps = set()
    for m in tts_models:
        all_modes.add(m.get("mode", ""))
        for c in m.get("capabilities", []):
            all_caps.add(c)

    voices = _all_voices_flat()
    voice_count = len(voices)
    lang_set = set()
    for m in tts_models:
        for lang in m.get("languages", []):
            lang_set.add(lang)

    sfx_files = []
    if os.path.exists(SFX_DIR):
        sfx_files = sorted(
            f
            for f in os.listdir(SFX_DIR)
            if not f.startswith(".") and os.path.isfile(os.path.join(SFX_DIR, f))
        )

    overview = {
        "name": "Sonus",
        "description": (
            "Multi-engine, offline text-to-speech server "
            "with OpenAI-compatible TTS and STT endpoints."
        ),
        "features": [
            "Text-to-Speech (TTS) via multiple engines (Kokoro, Qwen, Chatterbox, Piper)",
            "Speech-to-Text (STT) via Whisper (Faster Whisper / MLX Whisper)",
            "OpenAI-compatible API (/v1/audio/speech, /v1/audio/transcriptions)",
            "SSML support with voice switching, prosody, audio overlays",
            "Voice cloning from uploaded WAV samples (clone mode models)",
            "Voice design via natural language prompts (voice design models)",
            "Sound effects (SFX) management and SSML <audio> embedding",
            "Voice preset saving and loading",
            "Multi-language support (English, Chinese, Japanese, Korean, Hindi, EU languages)",
            "Voice blending (Kokoro) and emotion control (Chatterbox)",
        ],
        "tts": {
            "available_models": available_tts,
            "total_models": len(tts_models),
            "total_voices": voice_count,
            "modes": sorted(all_modes),
            "capabilities": sorted(all_caps),
            "languages": sorted(lang_set),
            "engines": list({m["engine"] for m in tts_models}),
        },
        "stt": {
            "available_models": available_stt,
            "total_models": len(stt_data),
            "engines": list({m["engine"] for m in stt_data}),
        },
        "sfx": {
            "count": len(sfx_files),
            "directory": SFX_DIR,
        },
        "resources": {
            "models": "sonus://models",
            "voices": "sonus://voices or sonus://voices/{model_id}",
            "stt_models": "sonus://stt_models",
            "engines": "sonus://engines",
            "presets": "sonus://presets",
            "sfx": "sonus://sfx",
            "outputs": "sonus://outputs",
            "formats": "sonus://formats",
        },
        "tools": [
            "list_models() - List all TTS models",
            "list_voices() - List all voices across all engines",
            "list_sfx() - List all sound effects",
            "list_stt_models() - List all STT models",
            "list_outputs() - List recent generated audio outputs",
            "search_voices(query, ...) - Advanced voice search with filters",
            "preview_voice(model_id, voice_id) - Get voice description and preview",
            "suggest_voice_for_character(...) - Find voices matching character criteria",
            "get_capabilities() - This overview",
        ],
        "api_endpoints": {
            "openai_tts": "POST /v1/audio/speech",
            "openai_stt": "POST /v1/audio/transcriptions",
            "list_models": "GET /v1/models",
            "list_voices": "GET /v1/voices",
            "list_stt_models": "GET /v1/stt/models",
            "list_sfx": "GET /v1/sfx",
            "presets_crud": "GET/POST/PUT/DELETE /presets/*",
            "voice_management": "GET/POST/PUT/DELETE /voice/*",
            "sfx_management": "GET/POST/PUT/DELETE /sfx/*",
            "output_management": "GET/DELETE /outputs/*",
            "health": "GET /health",
        },
    }
    return json.dumps(overview, indent=2)


# ---------------------------------------------------------------------------
# Streamable HTTP transport - mountable Starlette app
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
