import logging
import math
import os
import time
import warnings

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Required on Apple Silicon for unsupported MPS ops to fall back to CPU.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

logger = logging.getLogger("riffusion")

_DIFFUSERS_AVAILABLE = False
try:
    import torch
    from diffusers import StableDiffusionPipeline  # type: ignore[reportPrivateImportUsage]

    _DIFFUSERS_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import clean_memory, convert_to_wav_24k

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "riffusion")

_CKPT_FILENAME = "riffusion-model-v1-small.ckpt"
_CONFIG_DIRNAME = "riffusion-v1-config"

_MODELS: dict[str, dict] = {
    "riffusion-v1": {
        "hf": "GitMylo/riffusion-model-v1-small",
        "hf_url": "https://huggingface.co/GitMylo/riffusion-model-v1-small/resolve/main/riffusion-model-v1-small.ckpt",
        "name": "Riffusion v1 (small)",
        "description": "Spectrogram diffusion — text-to-music via SD fine-tune (stripped ckpt)",
        "size": "2.13 GB",
        "capabilities": ["text_to_music"],
    },
}

_RIFFUSION_SAMPLE_RATE = 44100
# Parameters derived from Riffusion's SpectrogramParams defaults:
#   step_size_ms=10  → hop_length = 44100 * 10 / 1000 = 441
#   window_duration_ms=100 → win_length = 44100 * 100 / 1000 = 4410
#   padded_duration_ms=400 → n_fft = 44100 * 400 / 1000 = 17640
_RIFFUSION_HOP_LENGTH = 441
_RIFFUSION_WIN_LENGTH = 4410
_RIFFUSION_N_FFT = 17640
_RIFFUSION_N_MELS = 512
_RIFFUSION_FMIN = 0
_RIFFUSION_FMAX = 10000
_RIFFUSION_POWER_FOR_IMAGE = 0.25
# Width of the spectrogram image produced by the SD pipeline.
_RIFFUSION_IMAGE_WIDTH = 512
# Seconds of audio per inference pass: (W - 1) * hop / sr
_RIFFUSION_NATIVE_DURATION = (
    (_RIFFUSION_IMAGE_WIDTH - 1) * _RIFFUSION_HOP_LENGTH / _RIFFUSION_SAMPLE_RATE
)

_DEFAULT_GUIDANCE_SCALE = 7.5
_DEFAULT_DURATION = 5.0
_MAX_DURATION = 30.0
_MIN_DURATION = 1.0
_DEFAULT_STEPS = 50

_install_commands: dict[str, list[str]] = {
    "riffusion-v1": [
        f"hf download {_MODELS['riffusion-v1']['hf']} --local-dir models/riffusion/riffusion-v1",
        (
            f"hf download riffusion/riffusion-model-v1 "
            f"--local-dir models/riffusion/riffusion-v1/{_CONFIG_DIRNAME} "
            f"--include '*.json' --include '*.txt'"
        ),
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


def _load_pipeline(ckpt_path: str, config_path: str | None = None) -> "StableDiffusionPipeline":
    """Load the Riffusion SD pipeline from a single .ckpt file (local or URL)."""
    device = _get_device()
    # The stripped GitMylo checkpoint produces NaN in float16 on MPS.
    # Use float32 everywhere except CUDA.
    dtype = torch.float16 if device == "cuda" else torch.float32

    logger.info("Loading riffusion pipeline from %s on %s", ckpt_path, device)
    pipe = StableDiffusionPipeline.from_single_file(
        ckpt_path,
        config=config_path,
        torch_dtype=dtype,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe = pipe.to(device)
    pipe.enable_attention_slicing()  # reduces peak memory on MPS / low VRAM
    return pipe


def _spectrogram_image_to_audio(image) -> np.ndarray:
    """Convert a Riffusion spectrogram PIL image to a float32 mono waveform.

    Exact inverse of Riffusion's image_from_spectrogram() encoding:
      1. Grayscale -> float32 [0, 255]
      2. Undo inversion: 255 - pixel  (Riffusion stores bright=quiet)
      3. Normalize to [0, 1]
      4. Undo power curve: val ^ (1 / power_for_image)  (power=0.25 → ^4)
      5. Vertically flip (image row-0 = high freq; mel index-0 = low freq)
      6. Invert mel filterbank via pseudo-inverse to get linear spectrogram
      7. Griffin-Lim phase reconstruction
    """
    try:
        import librosa
    except ImportError as exc:
        raise ImportError(
            "librosa is required for Riffusion audio conversion. Run: pip install librosa"
        ) from exc

    # Step 1-4: undo image_from_spectrogram encoding
    img = np.array(image.convert("L")).astype(np.float32)  # [0, 255]
    img = 255.0 - img  # undo inversion
    img = img / 255.0  # normalize [0, 1]
    mel_amp = np.power(img, 1.0 / _RIFFUSION_POWER_FOR_IMAGE)  # undo ^0.25 → ^4

    # Step 5: flip so row-0 = lowest frequency (librosa/mel convention)
    mel_amp = mel_amp[::-1].copy()

    # Step 6: invert mel filterbank using non-negative least squares (NNLS)
    # This is mathematically superior to pseudo-inverse and avoids distortion.
    linear_spec = librosa.feature.inverse.mel_to_stft(
        mel_amp,
        sr=_RIFFUSION_SAMPLE_RATE,
        n_fft=_RIFFUSION_N_FFT,
        power=1.0,  # We passed amplitude, not power
        fmin=_RIFFUSION_FMIN,
        fmax=_RIFFUSION_FMAX,
        htk=True,
        norm=None,
    )

    # Step 7: Griffin-Lim with Riffusion's exact STFT parameters
    audio = librosa.griffinlim(
        linear_spec,
        n_iter=32,
        hop_length=_RIFFUSION_HOP_LENGTH,
        win_length=_RIFFUSION_WIN_LENGTH,
        n_fft=_RIFFUSION_N_FFT,
    )

    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak

    return audio.astype(np.float32)


_CROSSFADE_MS = 50  # milliseconds of overlap between tiles to avoid click artifacts


def _crossfade(a: np.ndarray, b: np.ndarray, sr: int, fade_ms: int) -> np.ndarray:
    """Overlap-add two mono clips with a linear crossfade of `fade_ms` milliseconds."""
    fade_samples = int(sr * fade_ms / 1000)
    fade_samples = min(fade_samples, len(a), len(b))
    if fade_samples == 0:
        return np.concatenate([a, b])
    ramp = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    a[-fade_samples:] *= ramp
    b[:fade_samples] *= 1.0 - ramp
    return np.concatenate(
        [
            a[:-fade_samples],
            a[-fade_samples:] + b[:fade_samples],
            b[fade_samples:],
        ]
    )


def _generate_tiles(pipe, prompt: str, steps: int, num_tiles: int, seed: int) -> np.ndarray:
    """Run num_tiles diffusion passes, crossfading adjacent tiles to avoid clicks."""
    clips: list[np.ndarray] = []
    for i in range(num_tiles):
        logger.debug("riffusion tile %d/%d", i + 1, num_tiles)
        # Use CPU-based generator for seeding to avoid PyTorch MPS issues and ensure reproducibility
        generator = torch.Generator(device="cpu").manual_seed(seed + i)
        result = pipe(
            prompt,
            num_inference_steps=steps,
            width=_RIFFUSION_IMAGE_WIDTH,
            height=_RIFFUSION_N_MELS,
            guidance_scale=_DEFAULT_GUIDANCE_SCALE,
            generator=generator,
        )
        audio = _spectrogram_image_to_audio(result.images[0])
        clips.append(audio)

    if len(clips) == 1:
        return clips[0]

    result_audio = clips[0]
    for clip in clips[1:]:
        result_audio = _crossfade(result_audio, clip, _RIFFUSION_SAMPLE_RATE, _CROSSFADE_MS)
    return result_audio


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
                    os.path.isfile(os.path.join(MODELS_DIR, model_key, _CKPT_FILENAME))
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

        ckpt_file = os.path.join(MODELS_DIR, model_key, _CKPT_FILENAME)
        resolved = ckpt_file if os.path.isfile(ckpt_file) else None
        if not resolved:
            resolved = _MODELS[model_key]["hf_url"]
            logger.info("model_not_found_locally model=%s fallback=%s", model_key, resolved)

        config_dir = os.path.join(MODELS_DIR, model_key, _CONFIG_DIRNAME)
        local_config = config_dir if os.path.isdir(config_dir) else None

        t0 = time.time()

        try:
            pipe = _model_cache.get_or_load(
                model_key,
                lambda: _load_pipeline(resolved, local_config),
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

        seed = request.get("effective_seed")
        if seed is None:
            seed = int(time.time() * 1000) & 0xFFFFFFFF

        num_tiles = max(1, math.ceil(duration / _RIFFUSION_NATIVE_DURATION))

        try:
            audio = _generate_tiles(pipe, text, steps, num_tiles, seed)
        except Exception as e:
            logger.error("generation_failed req_id=%s model=%s: %s", req_id, model_key, e)
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        # Trim to requested duration
        target_samples = int(duration * _RIFFUSION_SAMPLE_RATE)
        if len(audio) > target_samples:
            audio = audio[:target_samples]

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

        return wav_path
