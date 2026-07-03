from __future__ import annotations

import os
import re
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def _sanitize_text(text: str) -> str:
    text = re.sub(
        r", (it|this|that|there|we|they|he|she|I|you)\b",
        r" \1",
        text,
    )
    return text


_MLX_AVAILABLE = False
try:
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_audio.tts.generate import generate_audio
    from mlx_audio.tts.utils import load_model

    _MLX_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import (
    SAMPLE_RATE,
    VOICES_DIR,
    convert_to_wav_24k,
    resolve_voice,
)
from src.utils import (
    model_path as _model_path,
)

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "qwen")

_MODELS: dict[str, str] = {
    "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit": "custom",
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit": "design",
    "Qwen3-TTS-12Hz-1.7B-Base-8bit": "clone",
    "Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit": "custom",
    "Qwen3-TTS-12Hz-0.6B-VoiceDesign-8bit": "design",
    "Qwen3-TTS-12Hz-0.6B-Base-8bit": "clone",
    "Qwen3-TTS-12Hz-1.7B-Base-4bit": "clone",
}

_MODEL_META: dict[str, dict] = {
    "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit": {
        "id": "qwen-custom",
        "name": "Qwen3 Pro Custom Voice",
        "description": "High-quality 1.7B model with preset speakers",
        "capabilities": ["speaker", "temperature"],
        "size": "3.1 GB",
    },
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit": {
        "id": "qwen-voice",
        "name": "Qwen3 Pro Voice Design",
        "description": "Synthesize voices from natural language descriptions",
        "capabilities": ["voice_prompt", "temperature"],
        "size": "3.1 GB",
    },
    "Qwen3-TTS-12Hz-1.7B-Base-8bit": {
        "id": "qwen-clone-8bit",
        "name": "Qwen3 Pro Voice Clone (8bit)",
        "description": "High-fidelity voice cloning",
        "capabilities": ["voice_clone", "temperature"],
        "size": "3.1 GB",
    },
    "Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit": {
        "id": "qwen-lite",
        "name": "Qwen3 Lite",
        "description": "Lightweight 0.6B model with preset speakers",
        "capabilities": ["speaker", "temperature"],
        "size": "1.3 GB",
    },
    "Qwen3-TTS-12Hz-0.6B-VoiceDesign-8bit": {
        "id": "qwen-lite-voice",
        "name": "Qwen3 Lite Voice Design",
        "description": "Lightweight voice design from descriptions",
        "capabilities": ["voice_prompt", "temperature"],
        "size": "1.3 GB",
    },
    "Qwen3-TTS-12Hz-0.6B-Base-8bit": {
        "id": "qwen-lite-clone",
        "name": "Qwen3 Lite Voice Clone",
        "description": "Lightweight voice cloning",
        "capabilities": ["voice_clone", "temperature"],
        "size": "1.3 GB",
    },
    "Qwen3-TTS-12Hz-1.7B-Base-4bit": {
        "id": "qwen-clone",
        "name": "Qwen3 Pro Voice Clone",
        "description": "Clone a voice from a reference WAV sample",
        "capabilities": ["voice_clone", "temperature"],
        "size": "1.6 GB",
    },
}

_SPEAKERS: set[str] = {
    "serena",
    "vivian",
    "uncle_fu",
    "ryan",
    "aiden",
    "ono_anna",
    "sohee",
    "eric",
    "dylan",
}

_speaker_embedding_cache: dict[str, mx.array] = {}
_speaker_embedding_lock = threading.Lock()


def _clear_embeddings():
    with _speaker_embedding_lock:
        _speaker_embedding_cache.clear()


_model_cache = ModelCache(ttl=30, tag="qwen", on_evict=_clear_embeddings)


def _load_audio_for_embedding(audio_path: str):
    try:
        from mlx_audio.utils import load_audio
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="mlx-audio not installed. Run: pip install mlx-audio",
        )

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    if not convert_to_wav_24k(audio_path, tmp_path):
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail="Failed to convert voice for embedding")

    try:
        audio = load_audio(tmp_path, sample_rate=SAMPLE_RATE)
    finally:
        os.unlink(tmp_path)

    return audio


def _embedding_path(voice_file: str) -> str:
    return voice_file + ".npy"


def _load_embedding_from_disk(voice_file: str) -> mx.array | None:
    emb_path = _embedding_path(voice_file)
    if os.path.exists(emb_path):
        try:
            return mx.load(emb_path)
        except Exception:
            os.remove(emb_path)
    return None


def _save_embedding_to_disk(voice_file: str, embedding: mx.array) -> None:
    emb_path = _embedding_path(voice_file)
    try:
        mx.save(emb_path, embedding)
    except Exception:
        pass


def _get_or_compute_speaker_embedding(model, voice_file: str) -> mx.array:
    cache_key = os.path.abspath(voice_file)

    with _speaker_embedding_lock:
        if cache_key in _speaker_embedding_cache:
            return _speaker_embedding_cache[cache_key]

    embedding = _load_embedding_from_disk(voice_file)
    if embedding is None:
        audio = _load_audio_for_embedding(voice_file)
        embedding = model.extract_speaker_embedding(audio, SAMPLE_RATE)
        _save_embedding_to_disk(voice_file, embedding)

    with _speaker_embedding_lock:
        _speaker_embedding_cache[cache_key] = embedding

    return embedding


def _inject_speaker_embedding(model, embedding: mx.array) -> None:
    hidden_size = model.talker.config.hidden_size
    if embedding.shape[-1] != hidden_size:
        if not hasattr(model, "_spk_proj"):
            model._spk_proj = nn.Linear(embedding.shape[-1], hidden_size)
        embedding = model._spk_proj(embedding)

    original_method = model.extract_speaker_embedding

    def patched_extract_speaker_embedding(audio, sr=24000):
        del audio, sr
        return embedding

    model.extract_speaker_embedding = patched_extract_speaker_embedding
    model._original_spk_embed_method = original_method


def _restore_speaker_embedding(model) -> None:
    if hasattr(model, "_original_spk_embed_method"):
        model.extract_speaker_embedding = model._original_spk_embed_method
        delattr(model, "_original_spk_embed_method")


@register
class QwenEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "qwen"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        meta = _MODEL_META
        cloneable = (
            sorted(
                f
                for f in os.listdir(VOICES_DIR)
                if f.lower().endswith(".wav") and not f.startswith(".")
            )
            if os.path.exists(VOICES_DIR)
            else []
        )

        def _voices(mode: str) -> dict:
            if mode == "custom":
                return {"built_in": sorted(_SPEAKERS), "cloneable": cloneable}
            if mode == "clone":
                return {"built_in": [], "cloneable": cloneable}
            return {"built_in": [], "cloneable": []}

        return [
            {
                "id": meta[folder]["id"],
                "name": meta[folder]["name"],
                "engine": "qwen",
                "model": folder,
                "mode": mode,
                "capabilities": meta[folder]["capabilities"],
                "description": meta[folder]["description"],
                "size": meta[folder].get("size", ""),
                "available": _model_path(MODELS_DIR, folder) is not None and _MLX_AVAILABLE,
                "mlx_required": True,
                "voices": _voices(mode),
                "languages": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/mlx-community/{folder}",
                    "commands": [
                        f"hf download mlx-community/{folder} --local-dir models/qwen/{folder}",
                    ],
                },
            }
            for folder, mode in _MODELS.items()
        ]

    def list_voices(self) -> dict:
        cloneable = (
            sorted(
                f
                for f in os.listdir(VOICES_DIR)
                if f.lower().endswith(".wav") and not f.startswith(".")
            )
            if os.path.exists(VOICES_DIR)
            else []
        )

        return {
            "built_in": sorted(_SPEAKERS),
            "cloneable": cloneable,
        }

    def preload_speaker_embeddings(self) -> dict:
        result: dict = {"preloaded": [], "failed": []}

        model = _model_cache.current
        if model is None:
            result["error"] = "Model not loaded"
            return result

        cloneable = self.list_voices().get("cloneable", [])
        for voice_file in cloneable:
            voice_path = resolve_voice(voice_file)
            if voice_path:
                try:
                    _get_or_compute_speaker_embedding(model, voice_path)
                    result["preloaded"].append(voice_file)
                except Exception as e:
                    result["failed"].append({"voice": voice_file, "error": str(e)})

        return result

    def validate(self, request: dict) -> None:
        mode = _MODELS[request["model"]]

        if mode == "custom":
            speaker = request.get("speaker_name")
            if speaker and speaker not in _SPEAKERS:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown speaker '{speaker}'. Valid: {sorted(_SPEAKERS)}",
                )

        elif mode == "design":
            if not request.get("voice_description"):
                raise HTTPException(
                    status_code=422,
                    detail="'voice_description' is required for VoiceDesign models",
                )

        elif mode == "clone":
            if not request.get("sample_voice_file"):
                raise HTTPException(
                    status_code=422,
                    detail="'sample_voice_file' is required for Base (cloning) models",
                )
            if not resolve_voice(request["sample_voice_file"]):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Voice file '{request['sample_voice_file']}' not found in {VOICES_DIR}. "
                        "Place a .wav file there and retry."
                    ),
                )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _MLX_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Qwen3 engine requires MLX (Apple Silicon only). "
                    "Use the Kokoro or Piper engine instead."
                ),
            )

        model_name = request["model"]
        mode = _MODELS[model_name]
        speed = request["speed_value"]
        temperature = request["temperature"]
        text = request["text"]

        resolved_path = _model_path(MODELS_DIR, model_name)
        if not resolved_path:
            raise HTTPException(
                status_code=422,
                detail=f"Model folder '{model_name}' not found in {MODELS_DIR}",
            )

        mx.random.seed(request["effective_seed"])

        t0 = time.time()
        try:
            model = _model_cache.get_or_load(model_name, lambda: load_model(Path(resolved_path)))
        except HTTPException:
            raise
        except Exception as e:
            print(f"[qwen] Model load failed for '{model_name}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Model load failed: {e}. Ensure the model is downloaded and MLX is working.",
            )

        try:
            text = _sanitize_text(text)

            if mode == "custom":
                generate_audio(
                    model=model,
                    text=text,
                    voice=request.get("speaker_name") or "Vivian",
                    instruct=request.get("voice_description") or "Normal tone",
                    speed=speed,
                    temperature=temperature,
                    output_path=tmp_dir,
                )

            elif mode == "design":
                generate_audio(
                    model=model,
                    text=text,
                    instruct=request["voice_description"],
                    speed=speed,
                    temperature=temperature,
                    output_path=tmp_dir,
                )

            elif mode == "clone":
                voice_path = resolve_voice(request["sample_voice_file"])
                assert voice_path is not None

                ref_wav = os.path.join(tmp_dir, "ref_converted.wav")
                if not convert_to_wav_24k(voice_path, ref_wav):
                    raise HTTPException(status_code=500, detail="Failed to convert reference audio")

                txt_path = os.path.splitext(voice_path)[0] + ".txt"
                ref_text = None
                if os.path.exists(txt_path):
                    with open(txt_path, "r", encoding="utf-8") as fh:
                        ref_text = fh.read().strip() or None
                if not ref_text:
                    name = request["sample_voice_file"]
                    raise HTTPException(
                        status_code=422,
                        detail=f"No transcript found for voice '{name}'. "
                        "Re-upload the voice file so a transcript is generated, "
                        "or place a <name>.txt file alongside the WAV.",
                    )

                embedding = _get_or_compute_speaker_embedding(model, voice_path)
                _inject_speaker_embedding(model, embedding)

                try:
                    generate_audio(
                        model=model,
                        text=text,
                        ref_audio=ref_wav,
                        ref_text=ref_text,
                        speed=speed,
                        temperature=temperature,
                        output_path=tmp_dir,
                    )
                finally:
                    _restore_speaker_embedding(model)

        except HTTPException:
            raise
        except Exception as e:
            print(f"[qwen] Generation failed (mode={mode}): {e}")
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        wav_path = os.path.join(tmp_dir, "audio.wav")
        segments = sorted(
            (f for f in os.listdir(tmp_dir) if re.match(r"audio_\d+\.wav$", f)),
            key=lambda f: int(re.search(r"(\d+)", f).group(1)),
        )
        if not segments:
            raise HTTPException(status_code=500, detail="TTS produced no output file")

        if len(segments) == 1:
            os.rename(os.path.join(tmp_dir, segments[0]), wav_path)
        else:
            audio_parts = []
            for seg in segments:
                part, sr = sf.read(os.path.join(tmp_dir, seg))
                audio_parts.append(part)
            sf.write(wav_path, np.concatenate(audio_parts), sr)

        elapsed = time.time() - t0
        print(
            f"[qwen] {model_name}: generate={elapsed:.2f}s "
            f"| segments={len(segments)} | text_len={len(text)}"
        )
        return wav_path
