import logging
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("musicgen")

_MLX_AVAILABLE = False
try:
    from mlx_audiocraft import AudioGen, MusicGen

    _MLX_AVAILABLE = True
except ImportError:
    try:
        from mlx_audiocraft.models.audiogen import AudioGen
        from mlx_audiocraft.models.musicgen import MusicGen

        _MLX_AVAILABLE = True
    except ImportError:
        pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import (
    clean_memory,
    convert_to_wav_24k,
    mlx_lock,
    model_path,
)

MODELS_DIR = os.path.join(os.getcwd(), "models", "musicgen")

from .base import BaseEngine, register

_MUSICGEN_TAG = "musicgen"
_AUDIOGEN_TAG = "audiogen"

_MODELS: dict[str, dict] = {
    "musicgen-small": {
        "hf": "facebook/musicgen-small",
        "name": "MusicGen Small",
        "tag": _MUSICGEN_TAG,
        "description": "Lightweight 300M model — fast, good quality",
        "size": "1.2 GB",
        "capabilities": ["text_to_music"],
    },
    "musicgen-medium": {
        "hf": "facebook/musicgen-medium",
        "name": "MusicGen Medium",
        "tag": _MUSICGEN_TAG,
        "description": "Balanced 1.5B model — better musical coherence",
        "size": "3.2 GB",
        "capabilities": ["text_to_music"],
    },
    "musicgen-large": {
        "hf": "facebook/musicgen-large",
        "name": "MusicGen Large",
        "tag": _MUSICGEN_TAG,
        "description": "Best quality 3.3B model — richest output",
        "size": "6.5 GB",
        "capabilities": ["text_to_music"],
    },
    "audiogen-medium": {
        "hf": "facebook/audiogen-medium",
        "name": "AudioGen Medium",
        "tag": _AUDIOGEN_TAG,
        "description": "Text-to-sound-effects 1.5B model",
        "size": "3.6 GB",
        "capabilities": ["text_to_sfx"],
    },
}

_DEFAULT_DURATION = 10.0
_MAX_DURATION = 30.0
_MIN_DURATION = 1.0

# AudioGen runs at 50 fps (vs MusicGen ~25 fps) with 4 codebooks.
# Default cfg_coef=3.0 doubles every forward pass → silent Metal OOM on long clips.
# Cap duration and disable two_step_cfg to halve memory pressure.
_AUDIOGEN_DEFAULT_DURATION = 5.0
_AUDIOGEN_MAX_DURATION = 10.0

_install_commands: dict[str, list[str]] = {
    "musicgen-small": [
        "hf download facebook/musicgen-small --local-dir models/musicgen/musicgen-small",
    ],
    "musicgen-medium": [
        "hf download facebook/musicgen-medium --local-dir models/musicgen/musicgen-medium",
    ],
    "musicgen-large": [
        "hf download facebook/musicgen-large --local-dir models/musicgen/musicgen-large",
    ],
    "audiogen-medium": [
        "hf download facebook/audiogen-medium --local-dir models/musicgen/audiogen-medium",
    ],
}

_model_cache = ModelCache(ttl=60, tag="musicgen")


def _get_cls(model_key: str):
    tag = _MODELS[model_key]["tag"]
    if tag == _AUDIOGEN_TAG:
        return AudioGen
    return MusicGen


def _hf_repo(model_key: str) -> str:
    return _MODELS[model_key]["hf"]


@register
class MusicgenEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "musicgen"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        return [
            {
                "id": model_key,
                "name": _MODELS[model_key].get("name", model_key),
                "engine": "musicgen",
                "model": model_key,
                "mode": "generation",
                "capabilities": _MODELS[model_key]["capabilities"],
                "description": _MODELS[model_key]["description"],
                "size": _MODELS[model_key]["size"],
                "available": model_path(MODELS_DIR, model_key) is not None and _MLX_AVAILABLE,
                "mlx_required": True,
                "voices": {},
                "languages": ["en"],
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/{_hf_repo(model_key)}",
                    "commands": _install_commands[model_key],
                },
            }
            for model_key in _MODELS
        ]

    def list_voices(self) -> dict:
        return {}

    def validate(self, request: dict) -> None:
        model_key = request["model"]
        if model_key not in _MODELS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown model '{model_key}'. Valid: {sorted(_MODELS)}",
            )

        text = request.get("text") or ""
        if not text.strip():
            raise HTTPException(
                status_code=422,
                detail="'input' (text prompt) is required for music/sfx generation",
            )

        duration = request.get("duration", _DEFAULT_DURATION)
        if not (_MIN_DURATION <= duration <= _MAX_DURATION):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Duration must be between {_MIN_DURATION}s "
                    f"and {_MAX_DURATION}s (got {duration}s)"
                ),
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _MLX_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "MusicGen engine requires MLX (Apple Silicon only). "
                    "mlx-audiocraft package not found. Run: pip install mlx-audiocraft"
                ),
            )

        model_key = request["model"]
        text = request["text"]
        duration = request.get("duration", _DEFAULT_DURATION)
        req_id = request.get("req_id", "")

        resolved_path = model_path(MODELS_DIR, model_key)
        if not resolved_path:
            resolved_path = _hf_repo(model_key)
            logger.info("model_not_found_locally model=%s fallback=%s", model_key, resolved_path)

        cls = _get_cls(model_key)

        with mlx_lock:
            t0 = time.time()
            try:
                model = _model_cache.get_or_load(
                    model_key,
                    lambda: cls.get_pretrained(resolved_path),
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error("model_load_failed req_id=%s model=%s: %s", req_id, model_key, e)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Model load failed: {e}. "
                        "Ensure the model is downloaded and MLX is working."
                    ),
                )

            clean_memory()

            try:
                tag = _MODELS[model_key].get("tag", "")
                if tag == _AUDIOGEN_TAG:
                    # AudioGen: 50 fps × 4 codebooks × CFG doubles compute.
                    # two_step_cfg=False cuts memory in half; cfg_coef still applied.
                    max_dur = _AUDIOGEN_MAX_DURATION
                    actual_dur = min(duration, max_dur)
                    model.set_generation_params(
                        duration=actual_dur,
                        cfg_coef=3.0,
                        two_step_cfg=False,
                    )
                else:
                    model.set_generation_params(duration=duration)
                audio = model.generate([text])
            except HTTPException:
                raise
            except Exception as e:
                logger.error(
                    "generation_failed req_id=%s model=%s: %s",
                    req_id,
                    model_key,
                    e,
                )
                raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

            _model_cache.touch()

        native_sr = model.sample_rate
        wav_path = os.path.join(tmp_dir, "audio_000.wav")

        if isinstance(audio, np.ndarray):
            arr = audio
        elif isinstance(audio, list):
            arr = audio[0] if len(audio) > 0 else np.array([])
        else:
            try:
                arr = audio.cpu().numpy() if hasattr(audio, "cpu") else np.array(audio)
            except Exception:
                arr = np.array(audio)

        if arr.ndim == 3:
            arr = arr[0]
            arr = arr.T
            if arr.shape[1] == 1:
                arr = arr.squeeze(axis=1)
        elif arr.ndim > 1:
            arr = np.mean(arr, axis=0)

        import soundfile as sf

        sf.write(wav_path, arr, native_sr)

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        os.rename(wav_path, raw_path)

        if not convert_to_wav_24k(raw_path, wav_path):
            raise HTTPException(status_code=500, detail="Failed to convert output to 24kHz WAV")

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s model=%s duration=%.1fs elapsed=%.2fs",
            req_id,
            model_key,
            duration,
            elapsed,
        )

        if not os.path.exists(wav_path):
            raise HTTPException(status_code=500, detail="Generation produced no output file")

        return wav_path
