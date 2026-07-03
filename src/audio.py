import logging
import subprocess

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

NORM_TARGET = 0.9


def normalize_loudness(wav_path: str) -> None:
    try:
        audio, sr = sf.read(wav_path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        peak = np.max(np.abs(audio))
        if peak < 1e-10:
            return
        scale = NORM_TARGET / peak
        if abs(scale - 1.0) < 0.01:
            return
        sf.write(wav_path, audio * scale, sr)
    except Exception:
        logger.exception("normalize_loudness failed")


def trim_silence(wav_path: str, silence_thresh: float = 0.005, min_silence_len: int = 500) -> None:
    try:
        audio, sr = sf.read(wav_path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        rms = np.sqrt(np.mean(audio**2))
        adaptive_thresh = max(silence_thresh, rms * 0.01)
        mask = np.abs(audio) > adaptive_thresh
        if not mask.any():
            return
        nonzero = np.where(mask)[0]
        start = nonzero[0]
        end = nonzero[-1] + 1 + min_silence_len
        trimmed = audio[max(0, start) : min(end, len(audio))]
        sf.write(wav_path, trimmed, sr)
    except Exception:
        logger.exception("trim_silence failed")


def wav_to_mp3(wav_path: str, mp3_path: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        wav_path,
        "-codec:a",
        "libmp3lame",
        "-qscale:a",
        "2",
        mp3_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def wav_to_pcm(wav_path: str, pcm_path: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        wav_path,
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        pcm_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def merge_wav_files(wav_paths: list[str], output_path: str) -> None:
    try:
        parts = []
        sr = None
        for path in wav_paths:
            data, current_sr = sf.read(path)
            if sr is None:
                sr = current_sr
            parts.append(data)
        if parts:
            merged = np.concatenate(parts)
            sf.write(output_path, merged, sr)
    except Exception:
        logger.exception("merge_wav_files failed")
        raise


def generate_silence(duration: float, sample_rate: int, output_path: str) -> None:
    try:
        num_samples = int(duration * sample_rate)
        silence_data = np.zeros(num_samples, dtype=np.float32)
        sf.write(output_path, silence_data, sample_rate)
    except Exception:
        logger.exception("generate_silence failed")
        raise


def convert_to_wav_matching(input_path: str, output_path: str, sample_rate: int) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.exception("convert_to_wav_matching failed")
        return False
