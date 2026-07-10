import logging
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Required on Apple Silicon for unsupported MPS ops to fall back to CPU.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

logger = logging.getLogger("riffusion")

_DIFFUSERS_AVAILABLE = False
try:
    import torch
    from diffusers import DiffusionPipeline

    _DIFFUSERS_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import clean_memory, convert_to_wav_24k, model_path

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "riffusion")

_MODELS: dict[str, dict] = {
    "riffusion-v1": {
        "hf": "GitMylo/riffusion-model-v1-small",
        "name": "Riffusion v1",
        "description": "Spectrogram diffusion — fast text-to-music via SD fine-tune",
        "size": "2.5 GB",
        "capabilities": ["text_to_music"],
    },
}

# Each diffusion pass produces a fixed-length spectrogram window (~5.12 s at 44.1 kHz).
_RIFFUSION_NATIVE_DURATION = 5.12   # seconds per inference pass
_RIFFUSION_SAMPLE_RATE = 44100
_RIFFUSION_N_FFT = 2048
_RIFFUSION_HOP_LENGTH = 512
_RIFFUSION_N_MELS = 512

_DEFAULT_DURATION = 5.0
_MAX_DURATION = 30.0
_MIN_DURATION = 1.0
_DEFAULT_STEPS = 50

_install_commands: dict[str, list[str]] = {
    "riffusion-v1": [
        "hf download GitMylo/riffusion-model-v1-small --local-dir models/riffusion/riffusion-v1",
    ],
}

_model_cache: ModelCache = ModelCache(ttl=120, tag="riffusion")


def _get_device() -> str:
    if not _DIFFUSERS_AVAILABLE:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_pipeline(local_path: str) -> "DiffusionPipeline":
    """Load the Riffusion SD pipeline from a local directory or HF Hub."""
    device = _get_device()
    dtype = torch.float16 if device in ("cuda", "mps") else torch.float32
    is_local = os.path.isdir(local_path)

    logger.info("Loading riffusion pipeline from %s on %s", local_path, device)
    pipe = DiffusionPipeline.from_pretrained(
        local_path,
        torch_dtype=dtype,
        local_files_only=is_local,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe = pipe.to(device)
    pipe.enable_attention_slicing()  # reduces peak memory on MPS / low VRAM
    return pipe


def _spectrogram_image_to_audio(image) -> np.ndarray:
    """Convert a Riffusion spectrogram PIL image to a float32 mono waveform.

    Process:
      1. Grayscale -> float32 [0,1]
      2. Vertically flip (low freq -> row 0 for librosa convention)
      3. Undo log-power scaling: dB -> power
      4. Invert mel filterbank via pseudo-inverse
      5. Griffin-Lim phase reconstruction (32 iterations)
    """
    try:
        import librosa
    except ImportError as exc:
        raise ImportError(
            "librosa is required for Riffusion audio conversion. "
            "Run: pip install librosa"
        ) from exc

    img = np.array(image.convert("L")).astype(np.float32) / 255.0
    img = img[::-1]  # Riffusion: low freq at bottom; librosa expects low at index 0

    mel_db = img * 80.0 - 80.0
    mel_power = librosa.db_to_power(mel_db)

    mel_filters = librosa.filters.mel(
        sr=_RIFFUSION_SAMPLE_RATE,
        n_fft=_RIFFUSION_N_FFT,
        n_mels=_RIFFUSION_N_MELS,
    )
    pseudo_inv = np.linalg.pinv(mel_filters)
    linear_spec = np.maximum(pseudo_inv @ mel_power, 0.0)

    audio = librosa.griffinlim(
        linear_spec,
        n_iter=32,
        hop_length=_RIFFUSION_HOP_LENGTH,
        win_length=_RIFFUSION_N_FFT,
    )

    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak

    return audio.astype(np.float32)


def _generate_tiles(pipe, prompt: str, steps: int, num_tiles: int) -> np.ndarray:
    """Run num_tiles diffusion passes and concatenate the resulting audio."""
    clips = []
    for i in range(num_tiles):
        logger.debug("riffusion tile %d/%d", i + 1, num_tiles)
        result = pipe(
            prompt,
            num_inference_steps=steps,
            width=512,
            height=512,
            guidance_scale=7.5,
        )
        audio = _spectrogram_image_to_audio(result.images[0])
        clips.append(audio)
    return np.concatenate(clips)


@register
class RiffusionEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "riffusion"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        return [
            {
                "id": model_key,
                "name": _MODELS[model_key].get("name", model_key),
                "engine": "riffusion",
                "model": model_key,
                "mode": "generation",
                "capabilities": _MODELS[model_key]["capabilities"],
                "description": _MODELS[model_key]["description"],
                "size": _MODELS[model_key]["size"],
                "available": (
                    model_path(MODELS_DIR, model_key) is not None
                    and _DIFFUSERS_AVAILABLE
                ),
                "mlx_required": False,
                "voices": {},
                "languages": ["en"],
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/{_MODELS[model_key]['hf']}",
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
                detail="'input' (text prompt) is required for music generation",
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

        steps = request.get("num_inference_steps", _DEFAULT_STEPS)
        if not (10 <= steps <= 150):
            raise HTTPException(
                status_code=422,
                detail="num_inference_steps must be between 10 and 150",
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _DIFFUSERS_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Riffusion engine requires diffusers + torch. "
                    "Run: pip install diffusers torch accelerate"
                ),
            )

        model_key = request["model"]
        text = request["text"]
        duration = request.get("duration", _DEFAULT_DURATION)
        steps = request.get("num_inference_steps", _DEFAULT_STEPS)
        req_id = request.get("req_id", "")

        resolved = model_path(MODELS_DIR, model_key)
        if not resolved:
            resolved = _MODELS[model_key]["hf"]
            logger.info(
                "model_not_found_locally model=%s fallback=%s", model_key, resolved
            )

        t0 = time.time()

        try:
            pipe = _model_cache.get_or_load(
                model_key,
                lambda: _load_pipeline(resolved),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("model_load_failed req_id=%s model=%s: %s", req_id, model_key, e)
            raise HTTPException(
                status_code=500,
                detail=f"Model load failed: {e}. Ensure diffusers + torch are installed.",
            )

        clean_memory()

        import math
        num_tiles = max(1, math.ceil(duration / _RIFFUSION_NATIVE_DURATION))

        try:
            audio = _generate_tiles(pipe, text, steps, num_tiles)
        except Exception as e:
            logger.error(
                "generation_failed req_id=%s model=%s: %s", req_id, model_key, e
            )
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        # Trim to requested duration
        target_samples = int(duration * _RIFFUSION_SAMPLE_RATE)
        if len(audio) > target_samples:
            audio = audio[:target_samples]

        import soundfile as sf

        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        sf.write(wav_path, audio, _RIFFUSION_SAMPLE_RATE)

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        os.rename(wav_path, raw_path)

        if not convert_to_wav_24k(raw_path, wav_path):
            raise HTTPException(
                status_code=500, detail="Failed to convert riffusion output to 24kHz WAV"
            )

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s model=%s duration=%.1fs tiles=%d elapsed=%.2fs",
            req_id,
            model_key,
            duration,
            num_tiles,
            elapsed,
        )

        if not os.path.exists(wav_path):
            raise HTTPException(
                status_code=500, detail="Generation produced no output file"
            )

        return wav_path
