import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings

logger = logging.getLogger("server")

os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import uvicorn
    from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, field_validator
except ImportError:
    print("Error: 'fastapi' or 'uvicorn' not found.")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)

import xml.etree.ElementTree as ET

import src.engines  # noqa: F401
import src.stt  # noqa: F401
from src.audio import (
    convert_to_wav_matching,
    generate_silence,
    merge_wav_files,
    normalize_loudness,
    trim_silence,
    wav_to_mp3,
    wav_to_pcm,
)
from src.engines.base import discover as discover_tts
from src.mcp_server import create_sse_app
from src.presets import presets_router
from src.ssml import needs_ssml, to_ssml
from src.stt.base import discover as discover_stt
from src.utils import (
    SFX_DIR,
    VOICES_DIR,
    convert_to_wav_24k,
    get_audio_duration,
    resolve_voice,
)
from src.voice_descriptions import get_voice_description

TTS_ENGINES = discover_tts()
STT_ENGINES = discover_stt()

OUTPUTS_DIR = os.path.join(os.getcwd(), "outputs", "server")

# Simple TTL cache for /outputs/detail
_outputs_cache = {"ts": 0, "data": None}
OUTPUTS_CACHE_TTL = 2.0


def _invalidate_outputs_cache():
    _outputs_cache["ts"] = 0


SPEED_MAP = {
    "slow": 0.8,
    "normal": 1.0,
    "fast": 1.3,
}

os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(SFX_DIR, exist_ok=True)
os.makedirs(VOICES_DIR, exist_ok=True)

_VOICE_META_FILE = os.path.join(VOICES_DIR, ".metadata.json")


def _load_voice_metadata() -> dict[str, dict]:
    if os.path.exists(_VOICE_META_FILE):
        try:
            with open(_VOICE_META_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_voice_metadata(meta: dict[str, dict]):
    with open(_VOICE_META_FILE, "w") as f:
        json.dump(meta, f, indent=2, default=str)


app = FastAPI(
    title="Sonus",
    description=(
        "Sonus — Speak freely. Multi-engine, offline text-to-speech server "
        "with OpenAI-compatible TTS and STT endpoints."
    ),
    version="1.0.0",
    docs_url="/api-docs",
    openapi_tags=[
        {
            "name": "models-and-voices",
            "description": "Explore available models, voices, and engine capabilities.",
        },
        {
            "name": "voice-management",
            "description": "Upload, read, rename, and delete voice cloning samples.",
        },
        {
            "name": "output-management",
            "description": "List, retrieve, and delete previously generated audio files.",
        },
        {
            "name": "system",
            "description": "Health check and server status utilities.",
        },
        {
            "name": "speech-to-text",
            "description": "Transcribe audio and list available STT models.",
        },
        {
            "name": "presets",
            "description": "Save, list, rename, and delete voice configuration presets.",
        },
    ],
)

app.include_router(presets_router)

# ---------------------------------------------------------------------------
# Model manifest — built dynamically from each engine's list_models()
# ---------------------------------------------------------------------------


def _build_manifest(*, available_only: bool = True) -> dict[str, dict]:
    manifest = {}
    for engine in TTS_ENGINES:
        for m in engine.list_models():
            if available_only and not m.get("available", False):
                continue
            eid = m["id"]
            manifest[eid] = {
                "id": eid,
                "name": m.get("name", eid),
                "engine": m["engine"],
                "model": m["model"],
                "mode": m.get("mode", "speaker"),
                "capabilities": m.get("capabilities", []),
                "description": m.get("description", ""),
                "available": m.get("available", False),
                "voices": m.get("voices", {}),
                "languages": m.get("languages", []),
                "install": m.get("install"),
                "size": m.get("size", ""),
            }
    return manifest


# Optional mapping from OpenAI standard names to our aliases
OPENAI_MODEL_ALIASES: dict[str, str] = {
    "tts-1": "kokoro",
    "tts-1-hd": "qwen-voice",
}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class OpenAIRequest(BaseModel):
    model: str
    input: str
    voice: str | None = None
    response_format: str = "mp3"
    speed: float = 1.0
    temperature: float | None = None
    exaggeration: float | None = None
    cfg_weight: float | None = None

    @field_validator("input")
    @classmethod
    def input_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'input' must not be empty")
        return v

    @field_validator("response_format")
    @classmethod
    def format_valid(cls, v: str) -> str:
        if v not in ("mp3", "wav", "pcm"):
            raise ValueError(f"Unsupported response_format '{v}' — must be mp3, wav, or pcm")
        return v

    @field_validator("speed")
    @classmethod
    def speed_in_range(cls, v: float) -> float:
        if v < 0.25 or v > 4.0:
            raise ValueError("'speed' must be between 0.25 and 4.0")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_engine(model: str):
    for engine in TTS_ENGINES:
        if engine.claims(model):
            return engine
    known = sorted(m["model"] for e in TTS_ENGINES for m in e.list_models())
    raise HTTPException(
        status_code=422,
        detail=f"Unknown model '{model}'. Known models: {known}",
    )


def _find_stt_engine(model: str):
    for engine in STT_ENGINES:
        if engine.claims(model):
            return engine
    known = sorted(m["model"] for e in STT_ENGINES for m in e.list_models())
    raise HTTPException(
        status_code=422,
        detail=f"Unknown STT model '{model}'. Known: {known}",
    )


def _resolve_openai_model(model_input: str) -> dict:
    resolved = OPENAI_MODEL_ALIASES.get(model_input, model_input)
    manifest = _build_manifest()
    entry = manifest.get(resolved)
    if not entry:
        known = sorted(manifest)
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model '{model_input}'. Known: {known}",
        )
    return entry


class TextSegment:
    def __init__(
        self,
        text: str,
        voice: str | None = None,
        speed: float | None = None,
        temperature: float | None = None,
    ):
        self.text = text
        self.voice = voice
        self.speed = speed
        self.temperature = temperature

    def __repr__(self) -> str:
        return (
            f"TextSegment(text={repr(self.text)}, voice={repr(self.voice)}, "
            f"speed={self.speed}, temp={self.temperature})"
        )


class SilenceSegment:
    def __init__(self, duration: float):
        self.duration = duration

    def __repr__(self) -> str:
        return f"SilenceSegment(duration={self.duration})"


class AudioSegment:
    def __init__(
        self,
        src: str,
        fallback_text: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        temperature: float | None = None,
        async_play: bool = False,
        volume: float = 0.3,
    ):
        self.src = src
        self.fallback_text = fallback_text
        self.voice = voice
        self.speed = speed
        self.temperature = temperature
        self.async_play = async_play
        self.volume = volume

    def __repr__(self) -> str:
        return (
            f"AudioSegment(src={repr(self.src)}, fallback_text={repr(self.fallback_text)}, "
            f"voice={repr(self.voice)}, speed={self.speed}, temp={self.temperature}, "
            f"async={self.async_play}, volume={self.volume})"
        )


def parse_ssml(
    ssml_text: str,
    default_voice: str | None = None,
    default_speed: float = 1.0,
    default_temp: float = 0.7,
) -> list[TextSegment | SilenceSegment | AudioSegment]:
    try:
        root = ET.fromstring(ssml_text)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid SSML XML syntax: {e}")

    tag = root.tag.split("}")[-1]
    if tag != "speak":
        raise HTTPException(status_code=400, detail="Root element of SSML must be <speak>")

    def traverse(
        node, current_voice, current_speed, current_temp
    ) -> list[TextSegment | SilenceSegment | AudioSegment]:
        segments = []
        node_tag = node.tag.split("}")[-1]

        node_voice = current_voice
        node_speed = current_speed
        node_temp = current_temp

        if node_tag == "voice":
            node_voice = node.attrib.get("name") or node.attrib.get("value") or current_voice
        elif node_tag == "prosody":
            rate_val = node.attrib.get("rate")
            if rate_val:
                if rate_val.endswith("%"):
                    try:
                        pct = float(rate_val[:-1])
                        node_speed = current_speed * (1.0 + pct / 100.0)
                    except ValueError:
                        pass
                elif rate_val.startswith("+") or rate_val.startswith("-"):
                    try:
                        pct = float(rate_val)
                        node_speed = current_speed * (1.0 + pct / 100.0)
                    except ValueError:
                        pass
                else:
                    try:
                        node_speed = float(rate_val)
                    except ValueError:
                        if rate_val == "x-slow":
                            node_speed = 0.5
                        elif rate_val == "slow":
                            node_speed = 0.75
                        elif rate_val == "medium":
                            node_speed = 1.0
                        elif rate_val == "fast":
                            node_speed = 1.25
                        elif rate_val == "x-fast":
                            node_speed = 1.5
            temp_val = node.attrib.get("temperature")
            if temp_val:
                try:
                    node_temp = float(temp_val)
                except ValueError:
                    pass
        elif node_tag == "break":
            time_val = node.attrib.get("time", "0.5s")
            duration = 0.5
            if time_val.endswith("ms"):
                try:
                    duration = float(time_val[:-2]) / 1000.0
                except ValueError:
                    pass
            elif time_val.endswith("s"):
                try:
                    duration = float(time_val[:-1])
                except ValueError:
                    pass
            else:
                try:
                    duration = float(time_val)
                except ValueError:
                    pass
            segments.append(SilenceSegment(duration))
        elif node_tag == "sub":
            alias = node.attrib.get("alias")
            if alias:
                node.text = alias
        elif node_tag == "say-as":
            interpret_as = node.attrib.get("interpret-as")
            if interpret_as in ("characters", "spell-out") and node.text:
                node.text = " ".join(list(node.text.strip()))
        elif node_tag == "audio":
            src = node.attrib.get("src")
            if src:
                fallback = node.text.strip() if node.text else None
                async_play = "async" in node.attrib
                volume = 0.3
                vol_str = node.attrib.get("volume")
                if vol_str:
                    try:
                        volume = float(vol_str)
                    except ValueError:
                        pass
                segments.append(
                    AudioSegment(
                        src=src,
                        fallback_text=fallback,
                        voice=node_voice,
                        speed=node_speed,
                        temperature=node_temp,
                        async_play=async_play,
                        volume=volume,
                    )
                )
                if node.tail and node.tail.strip():
                    segments.append(
                        TextSegment(node.tail.strip(), current_voice, current_speed, current_temp)
                    )
                return segments

        if node.text and node.text.strip():
            segments.append(TextSegment(node.text.strip(), node_voice, node_speed, node_temp))

        for child in node:
            segments.extend(traverse(child, node_voice, node_speed, node_temp))

        if node_tag == "p":
            segments.append(SilenceSegment(0.6))
        elif node_tag == "s":
            segments.append(SilenceSegment(0.3))

        if node.tail and node.tail.strip():
            segments.append(
                TextSegment(node.tail.strip(), current_voice, current_speed, current_temp)
            )

        return segments

    raw_segments = traverse(root, default_voice, default_speed, default_temp)

    merged_segments = []
    for seg in raw_segments:
        if isinstance(seg, TextSegment):
            if (
                merged_segments
                and isinstance(merged_segments[-1], TextSegment)
                and merged_segments[-1].voice == seg.voice
                and merged_segments[-1].speed == seg.speed
                and merged_segments[-1].temperature == seg.temperature
            ):
                merged_segments[-1].text += " " + seg.text
            else:
                merged_segments.append(seg)
        elif isinstance(seg, SilenceSegment):
            if merged_segments and isinstance(merged_segments[-1], SilenceSegment):
                merged_segments[-1].duration = max(merged_segments[-1].duration, seg.duration)
            else:
                merged_segments.append(seg)
        else:
            merged_segments.append(seg)

    return merged_segments


def _openai_to_internal(req: OpenAIRequest, manifest: dict) -> dict:
    if req.speed <= 0.8:
        speed_key = "slow"
    elif req.speed >= 1.21:
        speed_key = "fast"
    else:
        speed_key = "normal"

    d: dict = {
        "text": req.input,
        "speed": speed_key,
        "speed_value": req.speed,
        "temperature": req.temperature if req.temperature is not None else 0.7,
        "seed": None,
        "speaker_name": None,
        "voice_description": None,
        "sample_voice_file": None,
    }

    caps = manifest["capabilities"]

    if not manifest["model"]:
        d["model"] = req.voice or ""
    else:
        d["model"] = manifest["model"]

    if req.voice:
        if "voice_clone" in caps:
            d["sample_voice_file"] = req.voice
        elif "voice_prompt" in caps:
            d["voice_description"] = req.voice
        elif "speaker" in caps or "voice_blend" in caps:
            d["speaker_name"] = req.voice

    if "emotion" in caps:
        if req.exaggeration is not None:
            d["exaggeration"] = req.exaggeration
        if req.cfg_weight is not None:
            d["cfg_weight"] = req.cfg_weight

    return d


# ---------------------------------------------------------------------------
# Routes — original API (backward compatible)
# ---------------------------------------------------------------------------


@app.delete("/outputs", summary="Delete all generated audio files", tags=["output-management"])
def delete_outputs():
    deleted = []
    errors = []
    try:
        entries = os.listdir(OUTPUTS_DIR)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not read outputs directory: {e}")

    for filename in entries:
        filepath = os.path.join(OUTPUTS_DIR, filename)
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
                deleted.append(filename)
            except OSError as e:
                errors.append({"file": filename, "error": str(e)})

    response: dict = {"deleted": len(deleted), "files": deleted}
    if errors:
        response["errors"] = errors
    _invalidate_outputs_cache()
    return JSONResponse(content=response)


@app.get("/health", summary="Health check", tags=["system"])
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — voice management
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE = 50 * 1024 * 1024


class StageUrlRequest(BaseModel):
    url: str
    name: str | None = None


async def _transcribe_voice(path: str, name: str):
    for stt in STT_ENGINES:
        models = [m["model"] for m in stt.list_models() if m.get("available")]
        try:
            if not models:
                models = [m["model"] for m in stt.list_models()]
            result = await asyncio.to_thread(stt.transcribe, path, models[0], None, 0.0)
            transcript = (result.get("text") or "").strip()
            if transcript:
                txt_path = os.path.splitext(path)[0] + ".txt"
                with open(txt_path, "w", encoding="utf-8") as fh:
                    fh.write(transcript)
                logger.info("transcribed_voice voice=%s text_len=%d", name, len(transcript))
            break
        except Exception as e:
            logger.error("auto_transcribe_failed voice=%s stt=%s: %s", name, type(stt).__name__, e)


@app.post("/voice", summary="Upload a voice file (any audio format)", tags=["voice-management"])
async def upload_voice(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    description: str | None = Form(None),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=422, detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit"
        )

    stem = name if name else (file.filename or "voice")
    stem = (
        "".join(c for c in stem.rsplit(".", 1)[0] if c.isalnum() or c in "-_.").rstrip(".")
        or "voice"
    )
    safe_name = stem + ".wav"

    target = os.path.join(VOICES_DIR, safe_name)
    if os.path.exists(target):
        raise HTTPException(
            status_code=409,
            detail=f"Voice '{safe_name}' already exists. Use DELETE /voice/{safe_name} first to replace it.",
        )

    is_wav = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE"

    if is_wav:
        try:
            with open(target, "wb") as f:
                f.write(content)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    else:
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or ".dat")[1])
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
            if not convert_to_wav_24k(tmp_path, target):
                if os.path.exists(target):
                    os.unlink(target)
                raise HTTPException(
                    status_code=422,
                    detail="Could not convert file to WAV — is it a valid audio file? ffmpeg must be installed.",
                )
        finally:
            os.unlink(tmp_path)

    duration = get_audio_duration(target)
    size = os.path.getsize(target)
    created_at = os.path.getmtime(target)
    url = f"/voice/{safe_name}"

    if description:
        meta = _load_voice_metadata()
        meta[safe_name] = meta.get(safe_name, {})
        meta[safe_name]["description"] = description
        _save_voice_metadata(meta)

    await _transcribe_voice(target, safe_name)

    return {
        "name": safe_name,
        "duration": round(duration, 1),
        "size": size,
        "created_at": created_at,
        "url": url,
        "description": description or "",
    }


STAGE_DIR = os.path.join(VOICES_DIR, ".staging")


@app.post(
    "/voice/stage",
    summary="Upload a voice file to staging (preview before save)",
    tags=["voice-management"],
)
async def stage_voice(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    description: str | None = Form(None),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=422, detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit"
        )

    stem = name if name else (file.filename or "voice")
    stem = (
        "".join(c for c in stem.rsplit(".", 1)[0] if c.isalnum() or c in "-_.").rstrip(".")
        or "voice"
    )
    safe_name = stem + ".wav"
    os.makedirs(STAGE_DIR, exist_ok=True)
    target = os.path.join(STAGE_DIR, safe_name)

    is_wav = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE"
    if is_wav:
        try:
            with open(target, "wb") as f:
                f.write(content)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    else:
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or ".dat")[1])
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
            if not convert_to_wav_24k(tmp_path, target):
                if os.path.exists(target):
                    os.unlink(target)
                raise HTTPException(
                    status_code=422,
                    detail="Could not convert file to WAV — is it a valid audio file? ffmpeg must be installed.",
                )
        finally:
            os.unlink(tmp_path)

    duration = get_audio_duration(target)
    size = os.path.getsize(target)
    created_at = os.path.getmtime(target)

    meta = _load_voice_metadata()
    stage_key = f".staging/{safe_name}"
    if description:
        meta[stage_key] = meta.get(stage_key, {})
        meta[stage_key]["description"] = description
    elif stage_key in meta:
        meta.pop(stage_key)
    _save_voice_metadata(meta)

    return {
        "name": safe_name,
        "duration": round(duration, 1),
        "size": size,
        "created_at": created_at,
        "url": f"/voice/stage/{safe_name}",
    }


@app.post(
    "/voice/stage/url",
    summary="Download a voice file from a URL and stage it",
    tags=["voice-management"],
)
def stage_voice_url(req: StageUrlRequest):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422, detail="Invalid URL — must start with http:// or https://"
        )

    parsed = urllib.parse.urlparse(url)
    url_filename = os.path.basename(parsed.path) or ""
    stem = (
        req.name.strip()
        if req.name and req.name.strip()
        else (url_filename.replace(".", "_") or "voice")
    )
    stem = (
        "".join(c for c in stem.rsplit(".", 1)[0] if c.isalnum() or c in "-_.").rstrip(".")
        or "voice"
    )
    safe_name = stem + ".wav"

    fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(url_filename or ".dat")[1])
    os.close(fd)

    try:
        resp = urllib.request.urlopen(url, timeout=30)
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_UPLOAD_SIZE:
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=422, detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit"
            )

        downloaded = 0
        with open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_UPLOAD_SIZE:
                    os.unlink(tmp_path)
                    raise HTTPException(
                        status_code=422,
                        detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit",
                    )
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise HTTPException(status_code=422, detail=f"HTTP {e.code} — {e.reason}")
    except urllib.error.URLError as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise HTTPException(status_code=422, detail=f"URL error — {e.reason}")

    os.makedirs(STAGE_DIR, exist_ok=True)
    target = os.path.join(STAGE_DIR, safe_name)

    with open(tmp_path, "rb") as f:
        header = f.read(12)

    is_wav = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if is_wav:
        shutil.move(tmp_path, target)
    else:
        try:
            if not convert_to_wav_24k(tmp_path, target):
                raise HTTPException(
                    status_code=422,
                    detail="Could not convert file to WAV — is it a valid audio file? ffmpeg must be installed.",
                )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    duration = get_audio_duration(target)
    size = os.path.getsize(target)
    created_at = os.path.getmtime(target)

    return {
        "name": safe_name,
        "duration": round(duration, 1),
        "size": size,
        "created_at": created_at,
        "url": f"/voice/stage/{safe_name}",
    }


@app.get("/voice/stage/{name:path}", summary="Get a staged voice file", tags=["voice-management"])
def get_stage_voice(name: str):
    safe = name if name.endswith(".wav") else name + ".wav"
    path = os.path.join(STAGE_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Staged voice '{name}' not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(STAGE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(path, media_type="audio/wav")


@app.delete(
    "/voice/stage/{name:path}", summary="Delete a staged voice file", tags=["voice-management"]
)
def delete_stage_voice(name: str):
    safe = name if name.endswith(".wav") else name + ".wav"
    path = os.path.join(STAGE_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Staged voice '{name}' not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(STAGE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    os.remove(path)
    return {"deleted": safe}


@app.post(
    "/voice/stage/{name:path}/save",
    summary="Save a staged voice permanently",
    tags=["voice-management"],
)
async def save_stage_voice(name: str):
    safe = name if name.endswith(".wav") else name + ".wav"
    stage_path = os.path.join(STAGE_DIR, safe)
    if not os.path.exists(stage_path):
        raise HTTPException(status_code=404, detail=f"Staged voice '{name}' not found")
    real = os.path.realpath(stage_path)
    if not real.startswith(os.path.realpath(STAGE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")

    target = os.path.join(VOICES_DIR, safe)
    if os.path.exists(target):
        raise HTTPException(
            status_code=409,
            detail=f"Voice '{safe}' already exists. Use DELETE /voice/{safe} first to replace it.",
        )

    shutil.move(stage_path, target)

    meta = _load_voice_metadata()
    if safe in meta:
        meta.pop(safe)
    stage_meta_key = f".staging/{safe}"
    if stage_meta_key in meta:
        meta[safe] = meta.pop(stage_meta_key)
        _save_voice_metadata(meta)

    duration = get_audio_duration(target)
    size = os.path.getsize(target)
    created_at = os.path.getmtime(target)
    url = f"/voice/{safe}"

    await _transcribe_voice(target, safe)

    return {
        "name": safe,
        "duration": round(duration, 1),
        "size": size,
        "created_at": created_at,
        "url": url,
    }


@app.get("/voice/{name:path}", summary="Get a voice file", tags=["voice-management"])
def get_voice(name: str):
    path = resolve_voice(name)
    if not path:
        raise HTTPException(status_code=404, detail=f"Voice '{name}' not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(VOICES_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(path, media_type="audio/wav")


@app.put("/voice/{name:path}", summary="Rename a voice file", tags=["voice-management"])
def rename_voice(name: str, new_name: str, description: str | None = None):
    path = resolve_voice(name)
    if not path:
        raise HTTPException(status_code=404, detail=f"Voice '{name}' not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(VOICES_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")

    safe_new = "".join(c for c in new_name if c.isalnum() or c in "-_.").rstrip(".") or "voice"
    if not safe_new.endswith(".wav"):
        safe_new += ".wav"

    new_path = os.path.join(VOICES_DIR, safe_new)
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail=f"Voice '{safe_new}' already exists")

    old_name = os.path.basename(path)
    meta = _load_voice_metadata()
    if old_name in meta:
        meta[safe_new] = meta.pop(old_name)
    if description is not None:
        meta.setdefault(safe_new, {})["description"] = description
        _save_voice_metadata(meta)

    os.rename(path, new_path)
    old_emb = path + ".npy"
    if os.path.exists(old_emb):
        os.rename(old_emb, new_path + ".npy")
    return {"name": safe_new, "url": f"/voice/{safe_new}"}


@app.delete("/voice/{name:path}", summary="Delete a voice file", tags=["voice-management"])
def delete_voice(name: str):
    path = resolve_voice(name)
    if not path:
        raise HTTPException(status_code=404, detail=f"Voice '{name}' not found")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(VOICES_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    os.remove(path)
    embedding = path + ".npy"
    if os.path.exists(embedding):
        os.remove(embedding)
    vfile = os.path.basename(path)
    meta = _load_voice_metadata()
    if vfile in meta:
        del meta[vfile]
        _save_voice_metadata(meta)
    return {"deleted": name}


# ---------------------------------------------------------------------------
# Routes — sound effects (SFX) management
# ---------------------------------------------------------------------------


@app.post(
    "/sfx",
    summary="Upload a sound effect file (any audio format)",
    tags=["sfx-management"],
)
async def upload_sfx(file: UploadFile = File(...), name: str | None = Form(None)):
    os.makedirs(SFX_DIR, exist_ok=True)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit",
        )

    stem = name if name else (file.filename or "sfx")
    stem = (
        "".join(c for c in stem.rsplit(".", 1)[0] if c.isalnum() or c in "-_.").rstrip(".") or "sfx"
    )
    safe_name = stem + ".wav"

    target = os.path.join(SFX_DIR, safe_name)
    if os.path.exists(target):
        raise HTTPException(
            status_code=409,
            detail=(
                f"SFX '{safe_name}' already exists. Use DELETE /sfx/{safe_name} "
                "first to replace it."
            ),
        )

    is_wav = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE"

    if is_wav:
        try:
            with open(target, "wb") as f:
                f.write(content)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    else:
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or ".dat")[1])
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
            if not convert_to_wav_24k(tmp_path, target):
                if os.path.exists(target):
                    os.unlink(target)
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Could not convert file to WAV — is it a valid audio file? "
                        "ffmpeg must be installed."
                    ),
                )
        finally:
            os.unlink(tmp_path)

    duration = get_audio_duration(target)
    size = os.path.getsize(target)
    created_at = os.path.getmtime(target)
    url = f"/sfx/{safe_name}"

    return {
        "name": safe_name,
        "duration": round(duration, 1),
        "size": size,
        "created_at": created_at,
        "url": url,
    }


@app.get(
    "/v1/sfx",
    summary="List all sound effects",
    tags=["sfx-management"],
)
def list_sfx_files():
    os.makedirs(SFX_DIR, exist_ok=True)
    data = []
    for fname in os.listdir(SFX_DIR):
        if fname.lower().endswith(tuple(AUDIO_EXTS)):
            path = os.path.join(SFX_DIR, fname)
            entry = {
                "name": fname,
                "size": os.path.getsize(path),
                "duration": round(get_audio_duration(path), 1),
                "created_at": os.path.getmtime(path),
                "url": f"/sfx/{fname}",
            }
            data.append(entry)
    data.sort(key=lambda e: e["name"])
    return JSONResponse(content={"object": "list", "data": data})


@app.get(
    "/sfx/{name:path}",
    summary="Get a sound effect file",
    tags=["sfx-management"],
)
def get_sfx_file(name: str):
    fpath = os.path.join(SFX_DIR, name)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(SFX_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail=f"SFX '{name}' not found")

    ext = os.path.splitext(name)[1].lower()
    media_type = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".pcm": "audio/L16"}.get(
        ext, "application/octet-stream"
    )
    return FileResponse(real, media_type=media_type)


@app.put("/sfx/{name:path}", summary="Rename an SFX file", tags=["sfx-management"])
def rename_sfx(name: str, new_name: str):
    fpath = os.path.join(SFX_DIR, name)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(SFX_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail=f"SFX '{name}' not found")

    stem = (
        "".join(c for c in new_name.rsplit(".", 1)[0] if c.isalnum() or c in "-_.").rstrip(".")
        or "sfx"
    )
    safe_new = stem + ".wav"

    new_path = os.path.join(SFX_DIR, safe_new)
    if os.path.exists(new_path) and safe_new != name:
        raise HTTPException(status_code=409, detail=f"SFX '{safe_new}' already exists.")

    os.rename(real, new_path)
    return {"name": safe_new, "url": f"/sfx/{safe_new}"}


@app.delete(
    "/sfx/{name:path}",
    summary="Delete a sound effect file",
    tags=["sfx-management"],
)
def delete_sfx(name: str):
    fpath = os.path.join(SFX_DIR, name)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(SFX_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail=f"SFX '{name}' not found")
    os.remove(real)
    return {"deleted": name}


# ---------------------------------------------------------------------------
# Routes — output management
# ---------------------------------------------------------------------------

AUDIO_EXTS = {".mp3", ".wav", ".pcm"}


@app.get(
    "/outputs/detail", summary="List generated outputs with metadata", tags=["output-management"]
)
def list_outputs_detail():
    now = time.time()
    if now - _outputs_cache["ts"] < OUTPUTS_CACHE_TTL and _outputs_cache["data"] is not None:
        return JSONResponse(content=_outputs_cache["data"])

    if not os.path.exists(OUTPUTS_DIR):
        _outputs_cache["ts"] = now
        _outputs_cache["data"] = []
        return JSONResponse(content=[])

    entries = []
    for fname in os.listdir(OUTPUTS_DIR):
        fpath = os.path.join(OUTPUTS_DIR, fname)
        if not os.path.isfile(fpath) or fname.startswith("."):
            continue
        if fname.endswith(".json"):
            continue

        ext = os.path.splitext(fname)[1].lower()
        if ext not in AUDIO_EXTS:
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
    _outputs_cache["ts"] = now
    _outputs_cache["data"] = entries
    return JSONResponse(content=entries)


@app.get(
    "/output/{filename:path}", summary="Get a generated output file", tags=["output-management"]
)
def get_output(filename: str):
    fpath = os.path.join(OUTPUTS_DIR, filename)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(OUTPUTS_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail=f"Output '{filename}' not found")

    ext = os.path.splitext(filename)[1].lower()
    media_type = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".pcm": "audio/L16"}.get(
        ext, "application/octet-stream"
    )
    return FileResponse(real, media_type=media_type)


@app.delete(
    "/output/{filename:path}", summary="Delete a generated output file", tags=["output-management"]
)
def delete_output(filename: str):
    fpath = os.path.join(OUTPUTS_DIR, filename)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(OUTPUTS_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail=f"Output '{filename}' not found")
    os.remove(real)
    json_path = real + ".json"
    if os.path.exists(json_path):
        os.remove(json_path)
    _invalidate_outputs_cache()
    return {"deleted": filename}


# ---------------------------------------------------------------------------
# Routes — speech-to-text
# ---------------------------------------------------------------------------


@app.get(
    "/v1/stt/models",
    summary="List available STT models",
    tags=["speech-to-text"],
)
def list_stt_models():
    models = []
    for engine in STT_ENGINES:
        models.extend(engine.list_models())
    return JSONResponse(content={"object": "list", "data": models})


@app.post(
    "/v1/audio/transcriptions",
    summary="Transcribe audio (OpenAI-compatible)",
    tags=["speech-to-text"],
)
async def transcribe_audio(
    file: UploadFile = File(...),
    model: str = Form(...),
    language: str | None = Form(None),
    temperature: float = Form(0.0),
    response_format: str = Form("json"),
    request: Request = None,
):
    stt_engine = _find_stt_engine(model)
    stt_engine.validate({"model": model, "language": language, "temperature": temperature})

    fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or ".wav")[1])
    os.close(fd)
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        result = await asyncio.to_thread(
            stt_engine.transcribe, tmp_path, model, language, temperature
        )

        save_output = (
            request.headers.get("x-save-output", "false").lower() == "true" if request else False
        )
        if save_output:
            output_id = uuid.uuid4().hex
            json_path = os.path.join(OUTPUTS_DIR, f"{output_id}.json")
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            try:
                with open(json_path, "w") as fh:
                    json.dump(result, fh)
            except OSError:
                pass

        if response_format == "text":
            return PlainTextResponse(content=result["text"])
        elif response_format == "verbose_json":
            return JSONResponse(content=result)
        else:
            return JSONResponse(content={"text": result["text"]})
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Routes — output metadata (E2E results)
# ---------------------------------------------------------------------------


@app.put(
    "/output/{filename:path}/meta",
    summary="Update output metadata (e.g. E2E validation results)",
    tags=["output-management"],
)
def update_output_meta(filename: str, body: dict = Body(...)):
    fpath = os.path.join(OUTPUTS_DIR, filename)
    real = os.path.realpath(fpath)
    if not real.startswith(os.path.realpath(OUTPUTS_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    json_path = real + ".json"
    existing = {}
    if os.path.exists(json_path):
        try:
            with open(json_path) as fh:
                existing = json.load(fh)
            existing.update(body)
        except (json.JSONDecodeError, OSError):
            existing = body
    else:
        existing = body
    try:
        with open(json_path, "w") as fh:
            json.dump(existing, fh)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write metadata: {e}")
    _invalidate_outputs_cache()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routes — OpenAI-compatible API
# ---------------------------------------------------------------------------


@app.get(
    "/v1/models", summary="List available models (OpenAI-compatible)", tags=["models-and-voices"]
)
def list_v1_models(extras: bool = False):
    manifest = _build_manifest(available_only=not extras)
    now = int(time.time())

    data = []
    for eid, entry in manifest.items():
        base = {
            "id": eid,
            "object": "model",
            "created": now,
            "owned_by": entry["engine"],
        }
        if extras:
            base.update(
                {
                    "name": entry.get("name", eid),
                    "engine": entry["engine"],
                    "model": entry["model"],
                    "mode": entry.get("mode", "speaker"),
                    "capabilities": entry.get("capabilities", []),
                    "description": entry.get("description", ""),
                    "available": entry.get("available", False),
                    "voices": entry.get("voices", {}),
                    "languages": entry.get("languages", []),
                    "install": entry.get("install"),
                    "size": entry.get("size", ""),
                }
            )
        data.append(base)

    for alias, real_model in OPENAI_MODEL_ALIASES.items():
        if real_model not in manifest:
            base = {
                "id": alias,
                "object": "model",
                "created": now,
                "owned_by": "openai",
            }
            if extras:
                base.update(
                    {
                        "name": alias,
                        "available": False,
                        "capabilities": [],
                    }
                )
            data.append(base)

    return JSONResponse(content={"object": "list", "data": data})


@app.get(
    "/v1/models/{model_id:path}",
    summary="Get model details (OpenAI-compatible)",
    tags=["models-and-voices"],
)
def get_v1_model(model_id: str, extras: bool = False):
    manifest = _build_manifest()
    entry = manifest.get(model_id)
    if not entry:
        known = sorted(manifest)
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' not found. Known: {known}",
        )
    now = int(time.time())
    result = {
        "id": model_id,
        "object": "model",
        "created": now,
        "owned_by": entry["engine"],
    }
    if extras:
        result.update(
            {
                "name": entry.get("name", model_id),
                "engine": entry["engine"],
                "model": entry["model"],
                "mode": entry.get("mode", "speaker"),
                "capabilities": entry.get("capabilities", []),
                "description": entry.get("description", ""),
                "available": entry.get("available", False),
                "voices": entry.get("voices", {}),
                "languages": entry.get("languages", []),
                "install": entry.get("install"),
                "size": entry.get("size", ""),
            }
        )
    return JSONResponse(content=result)


@app.get(
    "/v1/voices",
    summary="List all voices (OpenAI-compatible)",
    tags=["models-and-voices"],
)
def list_v1_voices(model_id: str | None = None):
    voice_meta = _load_voice_metadata()
    data = []
    seen_cloneable = set()
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

                desc = get_voice_description(engine_name, item)
                if desc:
                    entry["gender"] = desc.get("gender")
                    entry["age_tier"] = desc.get("age_tier")
                    entry["tone_tags"] = desc.get("tone_tags", [])
                    entry["quality_grade"] = desc.get("quality_grade")
                    entry["description"] = desc.get("description")
                elif category == "cloneable":
                    vmeta = voice_meta.get(item, {})
                    if vmeta.get("description"):
                        entry["description"] = vmeta["description"]

                if category == "cloneable":
                    path = os.path.join(VOICES_DIR, item)
                    if os.path.exists(path):
                        entry["size"] = os.path.getsize(path)
                        entry["duration"] = round(get_audio_duration(path), 1)
                        entry["created_at"] = os.path.getmtime(path)
                        entry["url"] = f"/voice/{item}"
                data.append(entry)
    data.sort(key=lambda e: (0 if e["category"] == "built_in" else 1, e["engine"], e["id"]))
    return JSONResponse(content={"object": "list", "data": data})


def prepare_segment_request(
    base_req: dict, segment: TextSegment, caps: list, manifest: dict
) -> dict:
    d = base_req.copy()
    d["text"] = segment.text

    if segment.voice:
        d["sample_voice_file"] = None
        d["voice_description"] = None
        d["speaker_name"] = None

        if not manifest.get("model"):
            d["model"] = segment.voice

        if "voice_clone" in caps:
            d["sample_voice_file"] = segment.voice
        elif "voice_prompt" in caps:
            d["voice_description"] = segment.voice
        elif "speaker" in caps or "voice_blend" in caps:
            d["speaker_name"] = segment.voice

    if segment.speed is not None:
        d["speed_value"] = segment.speed
        if segment.speed <= 0.8:
            d["speed"] = "slow"
        elif segment.speed >= 1.21:
            d["speed"] = "fast"
        else:
            d["speed"] = "normal"

    if segment.temperature is not None:
        d["temperature"] = segment.temperature

    return d


def download_audio_url(url: str, dest_path: str) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Sonus/0.1.0 Speech-Stitcher"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(response, f)
        return True
    except Exception as e:
        logger.error("audio_download_failed url=%s: %s", url, e)
        return False


@app.post("/v1/preview-ssml", summary="Preview auto-SSML conversion", tags=["text-to-speech"])
def preview_ssml(text: str = Body(..., embed=True)):
    try:
        result = to_ssml(text)
        return PlainTextResponse(result, media_type="application/xml")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/v1/parse-ssml",
    summary="Parse SSML into segment list (including async audio)",
    tags=["text-to-speech"],
)
def parse_ssml_endpoint(body: str = Body(..., embed=True)):
    try:
        segments = parse_ssml(body)
        result = []
        for seg in segments:
            if isinstance(seg, TextSegment):
                result.append({"type": "text", "text": seg.text, "voice": seg.voice})
            elif isinstance(seg, SilenceSegment):
                result.append({"type": "silence", "duration": seg.duration})
            elif isinstance(seg, AudioSegment):
                entry: dict = {
                    "type": "audio",
                    "src": seg.src,
                    "async": seg.async_play,
                    "volume": seg.volume,
                }
                if seg.fallback_text:
                    entry["fallback_text"] = seg.fallback_text
                result.append(entry)
        return JSONResponse(content={"segments": result})
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid SSML: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/v1/audio/speech", summary="Generate speech (OpenAI-compatible)", tags=["text-to-speech"]
)
async def openai_speech(req: OpenAIRequest, request: Request):
    manifest = _resolve_openai_model(req.model)

    caps = manifest.get("capabilities", [])

    if not req.voice:
        if "voice_clone" in caps:
            detail = (
                "'voice' is required for voice cloning models. "
                "Specify a .wav filename from the voices/ directory."
            )
        elif "voice_prompt" in caps:
            detail = (
                "'voice' is required for voice design models. "
                "Specify a natural language voice description."
            )
        else:
            detail = "'voice' is required. Specify a voice name from the available voices."
        raise HTTPException(status_code=422, detail=detail)

    request_dict = _openai_to_internal(req, manifest)

    auto_ssml = request.headers.get("x-auto-ssml", "true").lower() == "true"
    if auto_ssml and not req.input.strip().startswith("<speak"):
        if needs_ssml(req.input):
            ssml_text = to_ssml(req.input)
            req.input = ssml_text
            request_dict["text"] = ssml_text

    engine = _find_engine(request_dict["model"])
    req_id = uuid.uuid4().hex[:8]
    request_dict["req_id"] = req_id

    effective_seed = int(time.time() * 1000) & 0xFFFFFFFF
    request_dict["effective_seed"] = effective_seed

    is_ssml_input = req.input.strip().startswith("<speak")
    if is_ssml_input:
        default_voice = req.voice
        default_speed = req.speed
        default_temp = req.temperature if req.temperature is not None else 0.7
        segments = parse_ssml(req.input, default_voice, default_speed, default_temp)
        has_text = any(isinstance(seg, TextSegment) for seg in segments)
        if not has_text:
            raise HTTPException(
                status_code=400,
                detail="SSML must contain at least one text segment to generate speech.",
            )
    else:
        segments = [
            TextSegment(
                req.input,
                req.voice,
                req.speed,
                req.temperature if req.temperature is not None else 0.7,
            )
        ]

    # Pre-validate all segments before generating
    for seg in segments:
        if isinstance(seg, TextSegment):
            seg_req = prepare_segment_request(request_dict, seg, caps, manifest)
            engine.validate(seg_req)
        elif isinstance(seg, AudioSegment):
            is_url = seg.src.startswith("http://") or seg.src.startswith("https://")
            if not is_url:
                resolved_local = seg.src
                if not os.path.isabs(resolved_local):
                    sfx_path = os.path.join(SFX_DIR, seg.src)
                    if os.path.exists(sfx_path):
                        resolved_local = sfx_path
                    else:
                        resolved_local = os.path.join(os.getcwd(), seg.src)
                if not os.path.exists(resolved_local):
                    if seg.fallback_text:
                        fallback_seg = TextSegment(
                            seg.fallback_text, seg.voice, seg.speed, seg.temperature
                        )
                        seg_req = prepare_segment_request(
                            request_dict, fallback_seg, caps, manifest
                        )
                        engine.validate(seg_req)
                    else:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"Local audio file '{seg.src}' does not exist "
                                "and no fallback text was provided."
                            ),
                        )
            else:
                if seg.async_play:
                    pre_path = os.path.join(tempfile.gettempdir(), f"prefetch_{uuid.uuid4().hex}")
                    ok = await asyncio.to_thread(download_audio_url, seg.src, pre_path)
                    try:
                        os.unlink(pre_path)
                    except OSError:
                        pass
                    if not ok:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Async audio URL '{seg.src}' is unreachable.",
                        )
                elif seg.fallback_text:
                    fallback_seg = TextSegment(
                        seg.fallback_text, seg.voice, seg.speed, seg.temperature
                    )
                    seg_req = prepare_segment_request(request_dict, fallback_seg, caps, manifest)
                    engine.validate(seg_req)

    tmp_dir = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        t0 = time.time()
        generated_paths: dict[int, str] = {}
        async_overlays: dict[int, tuple[str, float]] = {}

        # 1. Generate text segments
        total_text_segs = sum(1 for s in segments if isinstance(s, TextSegment))
        text_seg_count = 0
        for idx, seg in enumerate(segments):
            if isinstance(seg, TextSegment):
                text_seg_count += 1
                seg_req = prepare_segment_request(request_dict, seg, caps, manifest)
                seg_req["segment"] = f"{text_seg_count}/{total_text_segs}"
                seg_dir = os.path.join(tmp_dir, f"seg_{idx}")
                os.makedirs(seg_dir, exist_ok=True)
                seg_wav = await asyncio.to_thread(engine.generate, seg_req, seg_dir)
                generated_paths[idx] = seg_wav

        # 2. Determine sample rate of generated segments
        sample_rate = 24000
        for path in generated_paths.values():
            if os.path.exists(path):
                try:
                    import soundfile as sf

                    _, info_sr = sf.read(path, frames=1)
                    sample_rate = info_sr
                    break
                except Exception:
                    pass

        # 3. Process silence segments and audio segments
        for idx, seg in enumerate(segments):
            if isinstance(seg, SilenceSegment):
                silence_path = os.path.join(tmp_dir, f"silence_{idx}.wav")
                generate_silence(seg.duration, sample_rate, silence_path)
                generated_paths[idx] = silence_path

            elif isinstance(seg, AudioSegment):
                is_url = seg.src.startswith("http://") or seg.src.startswith("https://")
                audio_file_path = None

                if is_url:
                    download_path = os.path.join(tmp_dir, f"download_{idx}")
                    success = await asyncio.to_thread(download_audio_url, seg.src, download_path)
                    if success and os.path.exists(download_path):
                        audio_file_path = download_path
                else:
                    resolved_local = seg.src
                    if not os.path.isabs(resolved_local):
                        sfx_path = os.path.join(SFX_DIR, seg.src)
                        if os.path.exists(sfx_path):
                            resolved_local = sfx_path
                        else:
                            resolved_local = os.path.join(os.getcwd(), seg.src)
                    if os.path.exists(resolved_local):
                        audio_file_path = resolved_local

                conversion_success = False
                if audio_file_path:
                    dest_wav = os.path.join(tmp_dir, f"audio_seg_{idx}.wav")
                    conversion_success = await asyncio.to_thread(
                        convert_to_wav_matching, audio_file_path, dest_wav, sample_rate
                    )

                if seg.async_play and conversion_success and os.path.exists(dest_wav):
                    async_overlays[idx] = (dest_wav, seg.volume)
                elif conversion_success and os.path.exists(dest_wav):
                    generated_paths[idx] = dest_wav
                elif seg.fallback_text:
                    fallback_seg = TextSegment(
                        seg.fallback_text, seg.voice, seg.speed, seg.temperature
                    )
                    seg_req = prepare_segment_request(request_dict, fallback_seg, caps, manifest)
                    seg_dir = os.path.join(tmp_dir, f"fallback_{idx}")
                    os.makedirs(seg_dir, exist_ok=True)
                    seg_wav = await asyncio.to_thread(engine.generate, seg_req, seg_dir)
                    generated_paths[idx] = seg_wav
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            f"Failed to process SSML audio source '{seg.src}' "
                            "and no fallback text was provided."
                        ),
                    )

        # 4. Merge all sync segment files
        sorted_indices = sorted(generated_paths.keys())
        sorted_paths = [generated_paths[i] for i in sorted_indices]

        wav_path = os.path.join(tmp_dir, "audio.wav")
        if len(sorted_paths) == 1:
            shutil.copy2(sorted_paths[0], wav_path)
        else:
            merge_wav_files(sorted_paths, wav_path)

        # 5. Mix async overlays into output
        if async_overlays:
            import numpy as np
            import soundfile as sf

            main_data, sr = sf.read(wav_path)
            main_data = main_data.astype(np.float64)

            frame_pos = 0
            for idx, seg in enumerate(segments):
                path = generated_paths.get(idx)
                if path and os.path.exists(path):
                    seg_frames = int(get_audio_duration(path) * sr)
                elif isinstance(seg, SilenceSegment):
                    seg_frames = int(seg.duration * sr)
                else:
                    seg_frames = 0

                if idx in async_overlays:
                    overlay_path, vol = async_overlays[idx]
                    overlay_data, _ = sf.read(overlay_path)

                    overlay_data = overlay_data.astype(np.float64) * vol

                    if main_data.ndim > 1 and overlay_data.ndim == 1:
                        overlay_data = np.tile(overlay_data[:, None], (1, main_data.shape[1]))
                    elif main_data.ndim == 1 and overlay_data.ndim > 1:
                        overlay_data = np.mean(overlay_data, axis=1)

                    end = frame_pos + len(overlay_data)
                    if end > len(main_data):
                        pad_shape = (
                            (end - len(main_data), main_data.shape[1])
                            if main_data.ndim > 1
                            else (end - len(main_data),)
                        )
                        main_data = np.concatenate(
                            [main_data, np.zeros(pad_shape, dtype=np.float64)]
                        )

                    chunk = main_data[frame_pos : frame_pos + len(overlay_data)]
                    if chunk.ndim > 1 and overlay_data.ndim == 1:
                        overlay_data = np.tile(overlay_data[:, None], (1, chunk.shape[1]))
                    main_data[frame_pos : frame_pos + len(overlay_data)] += overlay_data
                    del overlay_data

                frame_pos += seg_frames

            np.clip(main_data, -1.0, 1.0, out=main_data)
            sf.write(wav_path, main_data.astype(np.float32), sr)

        gen_time = time.time() - t0
        t1 = time.time()
        normalize_loudness(wav_path)
        trim_silence(wav_path)
        duration = get_audio_duration(wav_path)
        post_time = time.time() - t1
        total_time = time.time() - t0
        logger.info(
            "req_id=%s model=%s voice=%s gen=%.2fs post=%.2fs total=%.2fs audio=%.1fs",
            req_id, req.model, req.voice, gen_time, post_time, total_time, duration,
        )

        save_output = request.headers.get("x-save-output", "false").lower() == "true"

        content_type = "audio/mpeg"
        filename = "speech.mp3"

        if save_output:
            output_id = uuid.uuid4().hex
            if req.response_format == "wav":
                output_path = os.path.join(OUTPUTS_DIR, f"{output_id}.wav")
                shutil.copy2(wav_path, output_path)
                content_type = "audio/wav"
                filename = "speech.wav"
            elif req.response_format == "pcm":
                output_path = os.path.join(OUTPUTS_DIR, f"{output_id}.pcm")
                if not wav_to_pcm(wav_path, output_path):
                    raise HTTPException(
                        status_code=500,
                        detail="WAV-to-PCM conversion failed — is ffmpeg installed?",
                    )
                content_type = "audio/L16"
                filename = "speech.pcm"
            else:
                output_path = os.path.join(OUTPUTS_DIR, f"{output_id}.mp3")
                if not wav_to_mp3(wav_path, output_path):
                    raise HTTPException(
                        status_code=500,
                        detail="WAV-to-MP3 conversion failed — is ffmpeg installed?",
                    )

            real_out = os.path.realpath(output_path)
            if not real_out.startswith(os.path.realpath(OUTPUTS_DIR)):
                raise HTTPException(status_code=500, detail="Output path outside allowed directory")

            params = {
                "model": req.model,
                "input": req.input,
                "voice": req.voice,
                "speed": req.speed,
                "seed": effective_seed,
                "_duration": round(duration, 1),
            }
            batch_id = request.headers.get("x-batch-id")
            if batch_id:
                params["batch_id"] = batch_id
                params["batch_seq"] = int(request.headers.get("x-batch-seq", 0))
            try:
                with open(output_path + ".json", "w") as fh:
                    json.dump(params, fh)
            except OSError:
                pass
            _invalidate_outputs_cache()
        else:
            if req.response_format == "wav":
                output_path = wav_path
                content_type = "audio/wav"
                filename = "speech.wav"
            elif req.response_format == "pcm":
                output_path = os.path.join(tmp_dir, "output.pcm")
                if not wav_to_pcm(wav_path, output_path):
                    raise HTTPException(
                        status_code=500,
                        detail="WAV-to-PCM conversion failed — is ffmpeg installed?",
                    )
                content_type = "audio/L16"
                filename = "speech.pcm"
            else:
                output_path = os.path.join(tmp_dir, "output.mp3")
                if not wav_to_mp3(wav_path, output_path):
                    raise HTTPException(
                        status_code=500,
                        detail="WAV-to-MP3 conversion failed — is ffmpeg installed?",
                    )
            # read into memory before cleanup removes tmp_dir
            with open(output_path, "rb") as f:
                response_data = f.read()
            response_content_type = content_type
            response_filename = filename
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "openai_speech_failed req_id=%s model=%s voice=%s: %s",
            req_id, req.model, req.voice, e,
        )
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if save_output:
        return FileResponse(
            path=output_path,
            media_type=content_type,
            filename=filename,
            headers={"X-Seed": str(effective_seed), "X-Audio-Duration": str(duration)},
        )
    else:
        return Response(
            content=response_data,
            media_type=response_content_type,
            headers={
                "X-Seed": str(effective_seed),
                "X-Audio-Duration": str(duration),
                "Content-Disposition": f'inline; filename="{response_filename}"',
            },
        )


mcp_app = create_sse_app()
app.mount("/mcp", mcp_app, name="mcp")

app.mount("/", StaticFiles(directory="static", html=True), name="ui")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
