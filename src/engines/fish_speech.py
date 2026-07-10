import logging
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("fish_speech")

_MLX_SPEECH_AVAILABLE = False
try:
    from mlx_speech import tts as mlx_tts

    _MLX_SPEECH_AVAILABLE = True
except ImportError:
    pass

_FISH_SPEECH_AVAILABLE = False
try:
    import torch

    _FISH_SPEECH_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import clean_memory, convert_to_wav_24k, model_path, resolve_voice

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "fish_speech")
VOICES_DIR = os.path.join(os.getcwd(), "voices")

_MODELS: dict[str, dict] = {
    "fish-speech-1.5": {
        "hf": "fishaudio/fish-speech-1.5",
        "name": "Fish Speech V1.5",
        "description": "Multilingual TTS — 1M+ hours training, 13 languages, voice cloning",
        "size": "1.2 GB",
        "capabilities": ["voice_clone"],
    },
    "s2-pro": {
        "hf": "fishaudio/s2-pro",
        "name": "Fish Audio S2 Pro",
        "description": "Dual-AR 4B TTS — emotion control, multi-speaker, best-in-class quality",
        "size": "8.5 GB",
        "capabilities": ["voice_clone"],
    },
}

_V1_5_LANGUAGES = [
    "en",
    "zh",
    "ja",
    "de",
    "fr",
    "es",
    "ko",
    "ar",
    "ru",
    "nl",
    "it",
    "pl",
    "pt",
]
_S2_LANGUAGES = [
    "en",
    "zh",
    "ja",
    "ko",
    "de",
    "fr",
    "es",
    "ru",
    "pt",
    "it",
    "pl",
    "nl",
    "ar",
]

_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_TOP_P = 0.7
_DEFAULT_REPETITION_PENALTY = 1.2
_DEFAULT_MAX_NEW_TOKENS = 2048

_install_commands: dict[str, list[str]] = {
    "fish-speech-1.5": [
        "hf download fishaudio/fish-speech-1.5 --local-dir models/fish_speech/fish-speech-1.5",
    ],
    "s2-pro": [
        "hf download fishaudio/s2-pro --local-dir models/fish_speech/s2-pro",
    ],
}

_model_cache: ModelCache = ModelCache(ttl=300, tag="fish_speech")


def _get_device() -> str:
    if not _FISH_SPEECH_AVAILABLE:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_ref_text(voice_file: str) -> str:
    ref_path = resolve_voice(voice_file)
    if not ref_path:
        return ""
    txt_path = os.path.splitext(ref_path)[0] + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ── V1.5 backend ─────────────────────────────────────────────────────────────


def _load_v1_5_models(local_path: str) -> dict:
    from fish_speech.models.dac.inference import load_model as load_dac
    from fish_speech.models.text2semantic.inference import (
        load_model as load_text2sem,
    )
    from fish_speech.models.vqgan.inference import load_model as load_vqgan

    device = _get_device()
    logger.info("Loading Fish Speech V1.5 from %s on %s", local_path, device)
    precision = "bf16" if device == "cuda" else "fp32"

    return {
        "text2sem": load_text2sem(local_path, device=device, precision=precision),
        "vqgan": load_vqgan(local_path, device=device),
        "dac": load_dac(local_path, device=device),
    }


def _encode_ref_audio(dac_model, ref_path: str) -> np.ndarray:
    from fish_speech.models.dac.inference import encode_audio

    return encode_audio(dac_model, ref_path)


def _generate_v1_5_audio(
    models: dict,
    text: str,
    ref_tokens: np.ndarray | None,
    ref_text: str,
    temperature: float,
    top_p: float,
    repetition_penalty: float,
    max_new_tokens: int,
) -> np.ndarray:
    from fish_speech.models.text2semantic.inference import generate as gen_semantic
    from fish_speech.models.vqgan.inference import generate as gen_audio

    kwargs: dict = {
        "model": models["text2sem"],
        "text": text,
        "temperature": temperature,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "max_new_tokens": max_new_tokens,
    }

    if ref_tokens is not None and ref_text:
        kwargs["prompt_tokens"] = ref_tokens
        kwargs["prompt_text"] = ref_text

    semantic = gen_semantic(**kwargs)
    return gen_audio(models["vqgan"], codes=semantic)


# ── S2 Pro (HF / fish-speech) backend ────────────────────────────────────────


def _load_s2_hf(local_path: str):
    from fish_speech.models.s2.inference import S2Model

    device = _get_device()
    logger.info("Loading S2 Pro from %s on %s", local_path, device)
    return S2Model.from_pretrained(local_path, device=device)


def _generate_s2_hf_audio(model, text: str, ref_path: str | None, temperature: float) -> np.ndarray:
    kwargs: dict = {"text": text, "temperature": temperature}
    if ref_path:
        kwargs["reference_audio"] = ref_path
    return model.generate(**kwargs)


# ── S2 Pro (MLX) backend ─────────────────────────────────────────────────────


def _generate_s2_mlx_audio(
    text: str,
    ref_path: str | None,
    ref_text: str,
    temperature: float,
) -> np.ndarray:
    model = _model_cache.get_or_load(
        "s2-pro-mlx",
        lambda: mlx_tts.load("fish-s2-pro"),
    )
    _model_cache.touch()

    if ref_path and ref_text:
        return model.generate_with_reference(text, ref_path, ref_text)
    return model.generate(text)


# ── Engine ────────────────────────────────────────────────────────────────────


@register
class FishSpeechEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "fish_speech"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        if not os.path.exists(VOICES_DIR):
            cloneable = []
        else:
            cloneable = sorted(
                f
                for f in os.listdir(VOICES_DIR)
                if f.lower().endswith(".wav") and not f.startswith(".")
            )
        voices = {"cloneable": cloneable} if cloneable else {}

        return [
            {
                "id": model_key,
                "name": _MODELS[model_key]["name"],
                "engine": "fish_speech",
                "model": model_key,
                "mode": "clone",
                "capabilities": _MODELS[model_key]["capabilities"],
                "description": _MODELS[model_key]["description"],
                "size": _MODELS[model_key]["size"],
                "available": model_path(MODELS_DIR, model_key) is not None,
                "mlx_required": model_key == "s2-pro",
                "voices": voices,
                "languages": _V1_5_LANGUAGES if model_key == "fish-speech-1.5" else _S2_LANGUAGES,
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/{_MODELS[model_key]['hf']}",
                    "commands": _install_commands[model_key],
                },
            }
            for model_key in _MODELS
        ]

    def list_voices(self) -> dict:
        if not os.path.exists(VOICES_DIR):
            return {}
        cloneable = sorted(
            f
            for f in os.listdir(VOICES_DIR)
            if f.lower().endswith(".wav") and not f.startswith(".")
        )
        return {"cloneable": cloneable} if cloneable else {}

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
                detail="'input' (text) is required for speech generation",
            )

        voice_file = request.get("sample_voice_file") or ""
        if voice_file:
            if not resolve_voice(voice_file):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Voice file '{voice_file}' not found in voices/. "
                        "Place a .wav file there and retry."
                    ),
                )

    def generate(self, request: dict, tmp_dir: str) -> str:
        model_key = request["model"]
        text = request["text"]
        voice_file = request.get("sample_voice_file") or ""
        temperature = request.get("temperature", _DEFAULT_TEMPERATURE)
        req_id = request.get("req_id", "")
        segment = request.get("segment", "")

        resolved = model_path(MODELS_DIR, model_key)
        if not resolved:
            hf_repo = _MODELS[model_key]["hf"]
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Model '{model_key}' not found in {MODELS_DIR}. "
                    f"Run: hf download {hf_repo} --local-dir models/fish_speech/{model_key}"
                ),
            )

        t0 = time.time()

        try:
            if model_key == "s2-pro" and _MLX_SPEECH_AVAILABLE:
                ref_path = resolve_voice(voice_file) if voice_file else None
                ref_text = _get_ref_text(voice_file) if voice_file else ""
                audio = _generate_s2_mlx_audio(text, ref_path, ref_text, temperature)

            elif model_key == "s2-pro" and _FISH_SPEECH_AVAILABLE:
                s2_model = _model_cache.get_or_load("s2-pro", lambda: _load_s2_hf(resolved))
                _model_cache.touch()
                clean_memory()
                ref_path = resolve_voice(voice_file) if voice_file else None
                audio = _generate_s2_hf_audio(s2_model, text, ref_path, temperature)

            elif model_key == "fish-speech-1.5" and _FISH_SPEECH_AVAILABLE:
                models = _model_cache.get_or_load(
                    "fish-speech-1.5", lambda: _load_v1_5_models(resolved)
                )
                _model_cache.touch()
                clean_memory()

                ref_tokens = None
                ref_text = ""
                if voice_file:
                    ref_path = resolve_voice(voice_file)
                    if ref_path:
                        ref_text = _get_ref_text(voice_file)
                        ref_tokens = _encode_ref_audio(models["dac"], ref_path)

                audio = _generate_v1_5_audio(
                    models,
                    text,
                    ref_tokens,
                    ref_text,
                    temperature,
                    _DEFAULT_TOP_P,
                    _DEFAULT_REPETITION_PENALTY,
                    _DEFAULT_MAX_NEW_TOKENS,
                )

            else:
                missing = []
                if model_key == "s2-pro":
                    if not _MLX_SPEECH_AVAILABLE:
                        missing.append("mlx-speech")
                    if not _FISH_SPEECH_AVAILABLE:
                        missing.append("fish-speech")
                if model_key == "fish-speech-1.5" and not _FISH_SPEECH_AVAILABLE:
                    missing.append("fish-speech torch")
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Missing dependencies for {model_key}: "
                        f"{' + '.join(missing)}. "
                        f"Run: pip install {' '.join(missing)}"
                    ),
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "generation_failed req_id=%s segment=%s model=%s voice=%s: %s",
                req_id,
                segment,
                model_key,
                voice_file,
                e,
            )
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        import soundfile as sf

        if isinstance(audio, np.ndarray):
            arr = audio
        elif hasattr(audio, "cpu"):
            arr = audio.cpu().numpy()
        else:
            arr = np.array(audio)

        if arr.ndim == 2 and arr.shape[0] <= 2:
            arr = arr.T

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        sf.write(raw_path, arr, 44100)

        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        if not convert_to_wav_24k(raw_path, wav_path):
            raise HTTPException(status_code=500, detail="Failed to convert to 24kHz WAV")

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s segment=%s model=%s voice=%s elapsed=%.2fs text_len=%d",
            req_id,
            segment,
            model_key,
            voice_file,
            elapsed,
            len(text),
        )

        if not os.path.exists(wav_path):
            raise HTTPException(status_code=500, detail="TTS produced no output file")

        return wav_path
