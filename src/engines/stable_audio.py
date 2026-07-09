import logging
import os
import time
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

logger = logging.getLogger("stable_audio")

_DIFFUSERS_AVAILABLE = False
try:
    import torch
    from diffusers import StableAudioPipeline

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

MODELS_DIR = os.path.join(os.getcwd(), "models", "stable_audio")

_MODELS: dict[str, dict] = {
    "stable-audio-open-1.0": {
        "hf": "stabilityai/stable-audio-open-1.0",
        "name": "Stable Audio Open 1.0",
        "description": "Latent diffusion — high-quality stereo audio, up to 47 s, 44.1 kHz",
        "size": "3.2 GB",
        "capabilities": ["text_to_music"],
    },
}

_STABLE_AUDIO_SAMPLE_RATE = 44100

_DEFAULT_DURATION = 10.0
_MAX_DURATION = 47.0
_MIN_DURATION = 1.0
_DEFAULT_STEPS = 100
_DEFAULT_GUIDANCE = 7.0

_install_commands: dict[str, list[str]] = {
    "stable-audio-open-1.0": [
        "hf download stabilityai/stable-audio-open-1.0 --local-dir"
        " models/stable_audio/stable-audio-open-1.0",
    ],
}

_model_cache: ModelCache = ModelCache(ttl=120, tag="stable_audio")


def _get_device() -> str:
    if not _DIFFUSERS_AVAILABLE:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_pipeline(local_path: str) -> "StableAudioPipeline":
    device = _get_device()
    use_fp16 = device in ("cuda",)
    dtype = torch.float16 if use_fp16 else torch.float32
    is_local = os.path.isdir(local_path)

    logger.info("Loading Stable Audio pipeline from %s on %s", local_path, device)
    pipe = StableAudioPipeline.from_pretrained(
        local_path,
        torch_dtype=dtype,
        local_files_only=is_local,
    )
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()
    return pipe


@register
class StableAudioEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "stable_audio"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        return [
            {
                "id": model_key,
                "name": _MODELS[model_key].get("name", model_key),
                "engine": "stable_audio",
                "model": model_key,
                "mode": "generation",
                "capabilities": _MODELS[model_key]["capabilities"],
                "description": _MODELS[model_key]["description"],
                "size": _MODELS[model_key]["size"],
                "available": (
                    model_path(MODELS_DIR, model_key) is not None and _DIFFUSERS_AVAILABLE
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
        if not (1 <= steps <= 250):
            raise HTTPException(
                status_code=422,
                detail="num_inference_steps must be between 1 and 250",
            )

        guidance = request.get("guidance_scale", _DEFAULT_GUIDANCE)
        if not (1.0 <= guidance <= 25.0):
            raise HTTPException(
                status_code=422,
                detail="guidance_scale must be between 1.0 and 25.0",
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _DIFFUSERS_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Stable Audio engine requires diffusers + torch. "
                    "Run: pip install diffusers torch"
                ),
            )

        model_key = request["model"]
        text = request["text"]
        duration = request.get("duration", _DEFAULT_DURATION)
        steps = request.get("num_inference_steps", _DEFAULT_STEPS)
        guidance = request.get("guidance_scale", _DEFAULT_GUIDANCE)
        negative_prompt = request.get("negative_prompt", "low quality, average quality")
        req_id = request.get("req_id", "")

        resolved = model_path(MODELS_DIR, model_key)
        if not resolved:
            resolved = _MODELS[model_key]["hf"]
            logger.info("model_not_found_locally model=%s fallback=%s", model_key, resolved)

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

        try:
            result = pipe(
                prompt=text,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                audio_end_in_s=duration,
                guidance_scale=guidance,
            )
        except Exception as e:
            logger.error("generation_failed req_id=%s model=%s: %s", req_id, model_key, e)
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        audio_tensor = result.audios[0]
        audio_np = audio_tensor.T.float().cpu().numpy()

        import soundfile as sf

        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        sf.write(wav_path, audio_np, _STABLE_AUDIO_SAMPLE_RATE)

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        os.rename(wav_path, raw_path)

        if not convert_to_wav_24k(raw_path, wav_path, channels=2):
            raise HTTPException(
                status_code=500,
                detail="Failed to convert stable audio output to 24kHz WAV",
            )

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s model=%s duration=%.1fs steps=%d elapsed=%.2fs",
            req_id,
            model_key,
            duration,
            steps,
            elapsed,
        )

        if not os.path.exists(wav_path):
            raise HTTPException(status_code=500, detail="Generation produced no output file")

        return wav_path
