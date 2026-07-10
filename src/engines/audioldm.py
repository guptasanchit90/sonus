import logging
import os
import time
import warnings

import soundfile as sf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

logger = logging.getLogger("audioldm")

_DIFFUSERS_AVAILABLE = False
try:
    import torch
    from diffusers import AudioLDMPipeline  # type: ignore[reportPrivateImportUsage]

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

MODELS_DIR = os.path.join(os.getcwd(), "models", "audioldm")

_MODELS: dict[str, dict] = {
    "audioldm-s-full-v2": {
        "hf": "cvssp/audioldm-s-full-v2",
        "name": "AudioLDM Small v2",
        "description": "Lightweight latent diffusion audio generator (~800 MB)",
        "size": "800 MB",
        "capabilities": ["text_to_sfx", "text_to_music"],
    },
    "audioldm-m-full": {
        "hf": "cvssp/audioldm-m-full",
        "name": "AudioLDM Medium",
        "description": "Medium scale latent diffusion audio generator (~1.5 GB)",
        "size": "1.5 GB",
        "capabilities": ["text_to_sfx", "text_to_music"],
    },
    "audioldm-l-full": {
        "hf": "cvssp/audioldm-l-full",
        "name": "AudioLDM Large",
        "description": "Large scale latent diffusion audio generator (~3.0 GB)",
        "size": "3.0 GB",
        "capabilities": ["text_to_sfx", "text_to_music"],
    },
}

_AUDIOLDM_SAMPLE_RATE = 16000

_DEFAULT_DURATION = 5.0
_MAX_DURATION = 30.0
_MIN_DURATION = 1.0
_DEFAULT_STEPS = 100
_DEFAULT_GUIDANCE = 10.0

_install_commands: dict[str, list[str]] = {
    "audioldm-s-full-v2": [
        "hf download cvssp/audioldm-s-full-v2 --local-dir models/audioldm/audioldm-s-full-v2",
    ],
    "audioldm-m-full": [
        "hf download cvssp/audioldm-m-full --local-dir models/audioldm/audioldm-m-full",
    ],
    "audioldm-l-full": [
        "hf download cvssp/audioldm-l-full --local-dir models/audioldm/audioldm-l-full",
    ],
}

_model_cache: ModelCache = ModelCache(ttl=120, tag="audioldm")


def _get_device() -> str:
    if not _DIFFUSERS_AVAILABLE:
        return "cpu"
    # AudioLDMPipeline has numerical instability / static noise generation bugs on MPS.
    # We force CPU execution on macOS to guarantee audio quality.
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_pipeline(local_path: str) -> "AudioLDMPipeline":
    device = _get_device()
    use_fp16 = device in ("cuda",)
    dtype = torch.float16 if use_fp16 else torch.float32
    is_local = os.path.isdir(local_path)

    logger.info("Loading AudioLDM pipeline from %s on %s", local_path, device)
    pipe = AudioLDMPipeline.from_pretrained(
        local_path,
        torch_dtype=dtype,
        local_files_only=is_local,
    )
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()
    return pipe


@register
class AudioLDMEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "audioldm"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        return [
            {
                "id": model_key,
                "name": _MODELS[model_key].get("name", model_key),
                "engine": "audioldm",
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
                detail="'input' (text prompt) is required for audio generation",
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
        if not (1 <= steps <= 200):
            raise HTTPException(
                status_code=422,
                detail="num_inference_steps must be between 1 and 200",
            )

        guidance = request.get("guidance_scale", _DEFAULT_GUIDANCE)
        if not (1.0 <= guidance <= 20.0):
            raise HTTPException(
                status_code=422,
                detail="guidance_scale must be between 1.0 and 20.0",
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        if not _DIFFUSERS_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "AudioLDM engine requires diffusers + torch + transformers. "
                    "Run: pip install diffusers torch transformers"
                ),
            )

        model_key = request["model"]
        text = request["text"]
        # Enhance the prompt with quality keywords if not present to boost fidelity
        if not any(k in text.lower() for k in ["clear", "quality", "studio", "hifi", "noise-free"]):
            text = f"{text}, clear, high quality, studio quality"

        duration = request.get("duration", _DEFAULT_DURATION)
        steps = request.get("num_inference_steps", _DEFAULT_STEPS)
        guidance = request.get("guidance_scale")
        if guidance is None:
            guidance = request.get("cfg_weight", _DEFAULT_GUIDANCE)
        negative_prompt = request.get(
            "negative_prompt",
            "low quality, average quality, hiss, noise, static, muffled, distorted"
        )
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

        seed = request.get("effective_seed")
        if seed is None:
            seed = int(time.time() * 1000) & 0xFFFFFFFF

        generator = torch.Generator(device="cpu").manual_seed(seed)

        try:
            result = pipe(
                prompt=text,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                audio_length_in_s=duration,
                guidance_scale=guidance,
                generator=generator,
            )
        except Exception as e:
            logger.error("generation_failed req_id=%s model=%s: %s", req_id, model_key, e)
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        _model_cache.touch()

        audio_np = result.audios[0]
        if audio_np.ndim > 1:
            audio_np = audio_np.squeeze()

        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        sf.write(wav_path, audio_np, _AUDIOLDM_SAMPLE_RATE)

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        os.rename(wav_path, raw_path)

        if not convert_to_wav_24k(raw_path, wav_path):
            raise HTTPException(
                status_code=500,
                detail="Failed to convert AudioLDM output to 24kHz WAV",
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

        return wav_path
