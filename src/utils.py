import gc
import logging
import os
import subprocess
import threading
import warnings

logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
    force=True,
)

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

_MLX_AVAILABLE = False
try:
    import mlx.core as mx

    _MLX_AVAILABLE = True
except ImportError:
    pass

mlx_lock = threading.Lock()

MODELS_DIR = os.path.join(os.getcwd(), "models")
VOICES_DIR = os.path.join(os.getcwd(), "voices")
SFX_DIR = os.path.join(os.getcwd(), "sfx")
SAMPLE_RATE = 24000


def resolve_voice(filename: str) -> str | None:
    for candidate in [filename, f"{filename}.wav"]:
        full = os.path.join(VOICES_DIR, candidate)
        if os.path.exists(full):
            return full
    return None


def model_path(base_dir: str, folder_name: str) -> str | None:
    full = os.path.join(base_dir, folder_name)
    if not os.path.exists(full):
        return None
    snapshots = os.path.join(full, "snapshots")
    if os.path.exists(snapshots):
        subs = [f for f in os.listdir(snapshots) if not f.startswith(".")]
        if subs:
            return os.path.join(snapshots, subs[0])
    return full


def get_audio_duration(filepath: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 0.0


def convert_to_wav_24k(input_path: str, output_path: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def clean_memory() -> None:
    gc.collect()
    if _MLX_AVAILABLE and mlx_lock.acquire(blocking=False):
        try:
            mx.clear_cache()
        finally:
            mlx_lock.release()


def scan_wav_voices(directory: str = VOICES_DIR) -> list[str]:
    if not os.path.exists(directory):
        return []
    return sorted(
        f for f in os.listdir(directory) if f.lower().endswith(".wav") and not f.startswith(".")
    )
