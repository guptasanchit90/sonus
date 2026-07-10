import logging
import os
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("cosyvoice")

_COSYVOICE_AVAILABLE = False
try:
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav

    _COSYVOICE_AVAILABLE = True
except ImportError:
    try:
        matcha_dir = os.path.join(os.getcwd(), "third_party", "Matcha-TTS")
        if os.path.isdir(matcha_dir):
            sys.path.insert(0, matcha_dir)
        from cosyvoice.cli.cosyvoice import CosyVoice2
        from cosyvoice.utils.file_utils import load_wav

        _COSYVOICE_AVAILABLE = True
    except ImportError:
        pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import clean_memory, convert_to_wav_24k, model_path, resolve_voice

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "cosyvoice")

_MODELS: dict[str, dict] = {
    "cosyvoice2-0.5b": {
        "hf": "FunAudioLLM/CosyVoice2-0.5B",
        "name": "CosyVoice2 0.5B",
        "description": "Multilingual zero-shot TTS — emotion/prosody control, voice cloning",
        "size": "5.6 GB",
        "capabilities": ["voice_clone"],
    },
}

_COSYVOICE_SAMPLE_RATE = 22050

_DEFAULT_TEMPERATURE = 0.7

_install_commands: dict[str, list[str]] = {
    "cosyvoice2-0.5b": [
        "hf download FunAudioLLM/CosyVoice2-0.5B --local-dir models/cosyvoice/CosyVoice2-0.5B",
    ],
}

_model_cache: ModelCache = ModelCache(ttl=300, tag="cosyvoice")


def _get_ref_text(voice_file: str) -> str:
    ref_path = resolve_voice(voice_file)
    if not ref_path:
        return ""
    txt_path = os.path.splitext(ref_path)[0] + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _load_cosyvoice(local_path: str):
    logger.info("Loading CosyVoice2 from %s", local_path)
    return CosyVoice2(local_path, load_jit=False, load_trt=False, fp16=False)


@register
class CosyvoiceEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "cosyvoice"

    def claims(self, model: str) -> bool:
        return model in _MODELS

    def list_models(self) -> list[dict]:
        voices_dir = os.path.join(os.getcwd(), "voices")
        if not os.path.exists(voices_dir):
            cloneable = []
        else:
            cloneable = sorted(
                f
                for f in os.listdir(voices_dir)
                if f.lower().endswith(".wav") and not f.startswith(".")
            )
        voices = {"cloneable": cloneable} if cloneable else {}

        return [
            {
                "id": model_key,
                "name": _MODELS[model_key]["name"],
                "engine": "cosyvoice",
                "model": model_key,
                "mode": "clone",
                "capabilities": _MODELS[model_key]["capabilities"],
                "description": _MODELS[model_key]["description"],
                "size": _MODELS[model_key]["size"],
                "available": (
                    model_path(MODELS_DIR, model_key) is not None and _COSYVOICE_AVAILABLE
                ),
                "mlx_required": False,
                "voices": voices,
                "languages": ["zh", "en", "ja", "ko", "yue"],
                "install": {
                    "source": "HuggingFace",
                    "url": f"https://huggingface.co/{_MODELS[model_key]['hf']}",
                    "commands": _install_commands[model_key],
                },
            }
            for model_key in _MODELS
        ]

    def list_voices(self) -> dict:
        voices_dir = os.path.join(os.getcwd(), "voices")
        if not os.path.exists(voices_dir):
            return {}
        cloneable = sorted(
            f
            for f in os.listdir(voices_dir)
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
        if not _COSYVOICE_AVAILABLE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "CosyVoice engine requires the cosyvoice package. Run: pip install cosyvoice"
                ),
            )

        model_key = request["model"]
        text = request["text"]
        voice_file = request.get("sample_voice_file") or ""
        req_id = request.get("req_id", "")
        segment = request.get("segment", "")

        resolved = model_path(MODELS_DIR, model_key)
        if not resolved:
            hf_repo = _MODELS[model_key]["hf"]
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Model '{model_key}' not found in {MODELS_DIR}. "
                    f"Run: hf download {hf_repo} --local-dir models/cosyvoice/{model_key}"
                ),
            )

        t0 = time.time()

        try:
            cosyvoice = _model_cache.get_or_load(model_key, lambda: _load_cosyvoice(resolved))
            _model_cache.touch()

            clean_memory()

            if voice_file:
                ref_path = resolve_voice(voice_file)
                ref_text = _get_ref_text(voice_file)
                prompt_speech_16k = load_wav(ref_path, 16000)

                results = list(
                    cosyvoice.inference_zero_shot(
                        text,
                        ref_text,
                        prompt_speech_16k,
                        stream=False,
                    )
                )
            else:
                results = list(
                    cosyvoice.inference_sft(
                        text,
                        "default",
                        stream=False,
                    )
                )

            audio_chunks = [r["tts_speech"] for r in results]
            if not audio_chunks:
                raise HTTPException(status_code=500, detail="CosyVoice produced no audio output")

            audio = np.concatenate([c.cpu().numpy().ravel() for c in audio_chunks])

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

        raw_path = os.path.join(tmp_dir, "audio_raw.wav")
        sf.write(raw_path, audio, _COSYVOICE_SAMPLE_RATE)

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
