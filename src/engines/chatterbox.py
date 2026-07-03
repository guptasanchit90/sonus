import logging
import os
import time
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("chatterbox")

_MLX_AVAILABLE = False
try:
    import mlx.core as mx
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
    get_audio_duration,
    resolve_voice,
    scan_wav_voices,
)
from src.utils import (
    model_path as _model_path,
)

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "chatterbox")
S3_TOKENIZER_DIR = os.path.join(MODELS_DIR, "s3_tokenizer")
_MIN_REF_DURATION = 5.0


_s3_tokenizer_patched = False


def _patch_s3_tokenizer_hf():
    global _s3_tokenizer_patched
    if _s3_tokenizer_patched:
        return True
    if not os.path.isdir(S3_TOKENIZER_DIR):
        return False
    try:
        import huggingface_hub

        _orig_snapshot = huggingface_hub.snapshot_download
        _orig_hf_download = huggingface_hub.hf_hub_download

        def _patched_snapshot(repo_id, **kw):
            if repo_id == "mlx-community/S3TokenizerV2":
                return S3_TOKENIZER_DIR
            return _orig_snapshot(repo_id, **kw)

        def _patched_hf_download(repo_id, filename=None, **kw):
            if repo_id == "mlx-community/S3TokenizerV2":
                if filename:
                    p = os.path.join(S3_TOKENIZER_DIR, filename)
                    if os.path.exists(p):
                        return p
                return os.path.join(S3_TOKENIZER_DIR, "model.safetensors")
            return _orig_hf_download(repo_id, filename=filename, **kw)

        huggingface_hub.snapshot_download = _patched_snapshot
        huggingface_hub.hf_hub_download = _patched_hf_download
        _s3_tokenizer_patched = True
        return True
    except ImportError:
        return False


_patch_s3_tokenizer_hf()  # Run once at import time, safe for concurrent requests

_MODELS: dict[str, str] = {
    "chatterbox-turbo-fp16": "Chatterbox-Turbo-TTS-fp16",
    "chatterbox-turbo-4bit": "Chatterbox-Turbo-TTS-4bit",
    "chatterbox-fp16": "Chatterbox-TTS-fp16",
    "chatterbox-8bit": "Chatterbox-TTS-8bit",
}

_TURBO_MODELS = {"chatterbox-turbo-fp16", "chatterbox-turbo-4bit"}

_MULTILINGUAL_LANGUAGES = [
    "en",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "pl",
    "tr",
    "ru",
    "nl",
    "cs",
    "ar",
    "zh",
    "ja",
    "hu",
    "ko",
]

_MODEL_META: dict[str, dict] = {
    "chatterbox-turbo-fp16": {
        "id": "chatterbox-turbo",
        "name": "Chatterbox Turbo",
        "description": "High-quality English voice cloning",
        "capabilities": ["voice_clone", "temperature"],
        "languages": ["en"],
        "size": "1.2 GB",
    },
    "chatterbox-turbo-4bit": {
        "id": "chatterbox-turbo-4bit",
        "name": "Chatterbox Turbo (4-bit)",
        "description": "Lightweight English voice cloning",
        "capabilities": ["voice_clone", "temperature"],
        "languages": ["en"],
        "size": "812 MB",
    },
    "chatterbox-fp16": {
        "id": "chatterbox",
        "name": "Chatterbox",
        "description": "Multilingual voice cloning with emotion control",
        "capabilities": ["voice_clone", "emotion", "temperature"],
        "languages": _MULTILINGUAL_LANGUAGES,
        "size": "2.7 GB",
    },
    "chatterbox-8bit": {
        "id": "chatterbox-8bit",
        "name": "Chatterbox (8-bit)",
        "description": "Lightweight multilingual voice cloning",
        "capabilities": ["voice_clone", "emotion", "temperature"],
        "languages": _MULTILINGUAL_LANGUAGES,
        "size": "1.28 GB",
    },
}

_model_cache = ModelCache(ttl=30, tag="chatterbox")


def _is_turbo(model_name: str) -> bool:
    return model_name in _TURBO_MODELS


def _hf_repo(folder: str) -> str:
    return f"mlx-community/{folder}"


@register
class ChatterboxEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "chatterbox"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        cloneable = scan_wav_voices(VOICES_DIR)
        voices = {"cloneable": cloneable} if cloneable else {}
        return [
            {
                "id": _MODEL_META[model_key]["id"],
                "name": _MODEL_META[model_key]["name"],
                "engine": "chatterbox",
                "model": model_key,
                "mode": "clone",
                "capabilities": _MODEL_META[model_key]["capabilities"],
                "description": _MODEL_META[model_key]["description"],
                "size": _MODEL_META[model_key].get("size", ""),
                "available": _model_path(MODELS_DIR, folder) is not None and _MLX_AVAILABLE,
                "mlx_required": True,
                "voices": voices,
                "languages": _MODEL_META[model_key]["languages"],
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/{_hf_repo(folder)}",
                    "commands": [
                        f"hf download {_hf_repo(folder)} --local-dir models/chatterbox/{folder}",
                    ],
                },
                "install_s3_tokenizer": {
                    "source": "HuggingFace",
                    "url": "https://huggingface.co/mlx-community/S3TokenizerV2",
                    "message": "S3Tokenizer required (auto-downloaded if missing):",
                    "commands": [
                        "hf download mlx-community/S3TokenizerV2 --local-dir models/chatterbox/s3_tokenizer",
                    ],
                },
            }
            for model_key, folder in _MODELS.items()
        ]

    def list_voices(self) -> dict:
        cloneable = scan_wav_voices(VOICES_DIR)
        return {"cloneable": cloneable} if cloneable else {}

    def validate(self, request: dict) -> None:
        voice_file = request.get("sample_voice_file")
        if not voice_file:
            raise HTTPException(
                status_code=422,
                detail="'sample_voice_file' is required for Chatterbox (voice cloning engine). "
                "Specify a .wav file from the voices/ directory.",
            )
        resolved = resolve_voice(voice_file)
        if not resolved:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Voice file '{voice_file}' not found in voices/. "
                    "Place a .wav file there and retry."
                ),
            )
        duration = get_audio_duration(resolved)
        if duration < _MIN_REF_DURATION:
            raise HTTPException(
                status_code=422,
                detail=f"Reference audio must be at least {_MIN_REF_DURATION:.0f}s (got {duration:.1f}s)",
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _MLX_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Chatterbox engines require MLX (Apple Silicon only). "
                    "Use the Kokoro or Piper engine instead."
                ),
            )

        model_name = request["model"]
        temperature = request["temperature"]
        text = request["text"]
        voice_file = request.get("sample_voice_file") or ""
        req_id = request.get("req_id", "")
        segment = request.get("segment", "")

        folder = _MODELS.get(model_name)
        if not folder:
            raise HTTPException(status_code=422, detail=f"Unknown model '{model_name}'")

        resolved_path = _model_path(MODELS_DIR, folder)
        if not resolved_path:
            repo = _hf_repo(folder)
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Model folder '{folder}' not found in {MODELS_DIR}. "
                    f"Run: hf download {repo} --local-dir models/chatterbox/{folder}"
                ),
            )

        mx.random.seed(request["effective_seed"])

        t0 = time.time()
        try:
            model = _model_cache.get_or_load(model_name, lambda: load_model(Path(resolved_path)))
        except HTTPException:
            raise
        except Exception as e:
            logger.error("model_load_failed req_id=%s model=%s: %s", req_id, model_name, e)
            raise HTTPException(
                status_code=500,
                detail=f"Model load failed: {e}. Ensure the model is downloaded and MLX is working.",
            )

        ref_audio = None
        if voice_file:
            ref_audio = resolve_voice(voice_file)

        is_turbo = _is_turbo(model_name)

        try:
            kwargs: dict = {
                "text": text,
                "ref_audio": ref_audio,
                "temperature": temperature,
                "repetition_penalty": 1.2,
            }

            word_count = len(text.split())
            max_tokens_est = max(400, min(int(word_count * 25), 4096))

            if is_turbo:
                kwargs["top_p"] = 0.95
                kwargs["max_tokens"] = max_tokens_est
                kwargs["norm_loudness"] = True
            else:
                kwargs["top_p"] = 0.95
                kwargs["max_new_tokens"] = max_tokens_est
                kwargs["exaggeration"] = request.get("exaggeration", 0.1)
                kwargs["cfg_weight"] = request.get("cfg_weight", 0.0)
                kwargs["min_p"] = 0.05
                kwargs["lang_code"] = request.get("lang_code", "en")

            audio_chunks = []
            for result in model.generate(**kwargs):
                audio_chunks.append(np.array(result.audio))

            if not audio_chunks:
                raise HTTPException(status_code=500, detail="TTS produced no audio output")

            audio = np.concatenate(audio_chunks)
            wav_path = os.path.join(tmp_dir, "audio_000.wav")
            sf.write(wav_path, audio, SAMPLE_RATE)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "generation_failed req_id=%s segment=%s model=%s voice=%s: %s",
                req_id, segment, model_name, voice_file, e,
            )
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        if not os.path.exists(wav_path):
            raise HTTPException(status_code=500, detail="TTS produced no output file")

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s segment=%s model=%s voice=%s elapsed=%.2fs text_len=%d",
            req_id, segment, model_name, voice_file, elapsed, len(text),
        )
        return wav_path
