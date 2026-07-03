import logging
import os
import time
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
import soundfile as sf

logger = logging.getLogger("kokoro")

try:
    from kokoro_onnx import Kokoro
except ImportError as exc:
    raise ImportError("kokoro_onnx is not installed. Run: pip install kokoro-onnx") from exc

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install fastapi") from exc

from src.cache import ModelCache

from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "kokoro")

ONNX_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"

_LANG_MAP: dict[str, str] = {
    "a": "en-us",
    "b": "en-gb",
    "j": "ja",
    "z": "zh",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "p": "pt-br",
}

_VOICES: dict[str, list[str]] = {
    "en-us": [
        "af_heart",
        "af_alloy",
        "af_aoede",
        "af_bella",
        "af_jessica",
        "af_kore",
        "af_nicole",
        "af_nova",
        "af_river",
        "af_sarah",
        "af_sky",
        "am_adam",
        "am_echo",
        "am_eric",
        "am_fenrir",
        "am_liam",
        "am_michael",
        "am_onyx",
        "am_puck",
        "am_santa",
    ],
    "en-gb": [
        "bf_alice",
        "bf_emma",
        "bf_isabella",
        "bf_lily",
        "bm_daniel",
        "bm_fable",
        "bm_george",
        "bm_lewis",
    ],
    "ja": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
    "zh": [
        "zf_xiaobei",
        "zf_xiaoni",
        "zf_xiaoxiao",
        "zf_xiaoyi",
        "zm_yunjian",
        "zm_yunxi",
        "zm_yunxia",
        "zm_yunyang",
    ],
    "es": ["ef_dora", "em_alex", "em_santa"],
    "fr-fr": ["ff_siwis"],
    "hi": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
    "it": ["if_sara", "im_nicola"],
    "pt-br": ["pf_dora", "pm_alex", "pm_santa"],
}

_ALL_VOICES: set[str] = {v for vs in _VOICES.values() for v in vs}

MODEL_ID = "kokoro-v1.0"
_kokoro_cache = ModelCache(ttl=30, tag="kokoro")


def _onnx_path() -> str:
    return os.path.join(MODELS_DIR, ONNX_FILE)


def _voices_path() -> str:
    return os.path.join(MODELS_DIR, VOICES_FILE)


def _model_available() -> bool:
    return os.path.exists(_onnx_path()) and os.path.exists(_voices_path())


def _parse_voices(voice_input: str) -> tuple[list[str], list[float] | None]:
    parts = [p.strip() for p in voice_input.split(",")]
    voices = []
    weights = []

    for part in parts:
        if ":" in part:
            voice, weight = part.rsplit(":", 1)
            voices.append(voice.strip())
            weight = weight.strip()
            if "." in weight:
                weights.append(float(weight))
            else:
                weights.append(float(weight) / 100)
        else:
            voices.append(part)

    if weights and len(weights) == len(voices):
        return voices, weights
    return voices, None


def _all_same_lang(voices: list[str]) -> bool:
    if not voices:
        return True
    prefixes = {v[0] for v in voices}
    return len(prefixes) == 1


def _lang_for_voice(voice: str) -> str:
    prefix = voice[0] if voice else "a"
    return _LANG_MAP.get(prefix, "en-us")


@register
class KokoroEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "kokoro"

    def claims(self, model: str) -> bool:
        return model == MODEL_ID

    def list_models(self) -> list[dict]:
        return [
            {
                "id": "kokoro",
                "name": "Kokoro 82M",
                "engine": "kokoro",
                "model": MODEL_ID,
                "mode": "speaker",
                "capabilities": ["speaker", "voice_blend"],
                "description": "Fast ONNX-based TTS with 9 languages and voice blending",
                "size": "480 MB",
                "available": _model_available(),
                "voices": {"built_in": sorted(_ALL_VOICES), "cloneable": []},
                "languages": sorted(set(_LANG_MAP.values())),
                "install": {
                    "source": "GitHub Releases",
                    "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0",
                    "commands": [
                        "curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx --output-dir models/kokoro",
                        "curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin --output-dir models/kokoro",
                    ],
                },
            }
        ]

    def list_voices(self) -> dict:
        return {lang: sorted(voices) for lang, voices in _VOICES.items()}

    def validate(self, request: dict) -> None:
        if not _model_available():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Kokoro model files not found in {MODELS_DIR}. "
                    f"Download {ONNX_FILE} and {VOICES_FILE} from "
                    "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"
                ),
            )

        speaker = request.get("speaker_name") or "af_heart"
        voices, weights = _parse_voices(speaker)

        for v in voices:
            if v not in _ALL_VOICES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown Kokoro voice '{v}'. See GET /voices for the full list.",
                )

        if len(voices) > 1 and not _all_same_lang(voices):
            raise HTTPException(
                status_code=422,
                detail="Cannot blend voices from different languages.",
            )

        speed = request.get("speed_value", 1.0)
        if speed < 0.25 or speed > 4.0:
            raise HTTPException(
                status_code=422,
                detail="Speed must be between 0.25 and 4.0 for Kokoro.",
            )

    def generate(self, request: dict, tmp_dir: str) -> str:
        voice = request.get("speaker_name") or "af_heart"
        speed = request["speed_value"]
        text = request["text"]
        voices, weights = _parse_voices(voice)
        lang = _lang_for_voice(voices[0])
        req_id = request.get("req_id", "")
        segment = request.get("segment", "")

        t0 = time.time()
        try:
            kokoro = _kokoro_cache.get_or_load(
                MODEL_ID, lambda: Kokoro(_onnx_path(), _voices_path())
            )

            if len(voices) == 1:
                voice_param = voices[0]
            else:
                n = len(voices)
                if weights:
                    total = sum(weights)
                    norms = [w / total for w in weights]
                else:
                    norms = [1.0 / n] * n
                blended = None
                for i, v in enumerate(voices):
                    style = kokoro.get_voice_style(v)
                    if blended is None:
                        blended = style * norms[i]
                    else:
                        blended = np.add(blended, style * norms[i])
                voice_param = blended
            assert voice_param is not None

            samples, sample_rate = kokoro.create(
                text,
                voice=voice_param,
                speed=speed,
                lang=lang,
            )
        except Exception as e:
            logger.error(
                "generation_failed req_id=%s segment=%s model=%s voice=%s: %s",
                req_id, segment, MODEL_ID, voice, e,
            )
            raise HTTPException(status_code=500, detail=f"Kokoro generation failed: {e}")

        _kokoro_cache.touch()
        samples = np.array(samples)

        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        try:
            sf.write(wav_path, samples, sample_rate)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write WAV: {e}")

        elapsed = time.time() - t0
        logger.info(
            "req_id=%s segment=%s model=%s voice=%s elapsed=%.2fs text_len=%d",
            req_id, segment, MODEL_ID, voice, elapsed, len(text),
        )
        return wav_path
