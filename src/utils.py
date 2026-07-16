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
    clean_name = filename
    if clean_name.lower().endswith(".wav"):
        clean_name = clean_name[:-4]

    # Check folder-based voice
    folder_path = os.path.join(VOICES_DIR, clean_name)
    if os.path.isdir(folder_path):
        wav_path = os.path.join(folder_path, f"{clean_name}.wav")
        if os.path.exists(wav_path):
            return wav_path

    # Legacy fallback
    for candidate in [filename, f"{filename}.wav"]:
        full = os.path.join(VOICES_DIR, candidate)
        if os.path.exists(full) and not os.path.isdir(full):
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


def convert_to_wav_24k(input_path: str, output_path: str, channels: int = 1) -> bool:
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
        str(channels),
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
    names: list[str] = []
    for entry in os.listdir(directory):
        if entry.startswith("."):
            continue
        entry_path = os.path.join(directory, entry)
        if os.path.isdir(entry_path):
            # Folder-based voice: folder named <stem>, wav inside named <stem>.wav
            wav = os.path.join(entry_path, f"{entry}.wav")
            if os.path.exists(wav):
                names.append(f"{entry}.wav")
        elif entry.lower().endswith(".wav"):
            names.append(entry)
    return sorted(names)


# ---------------------------------------------------------------------------
# Voice embedding helpers — shared by any engine that caches speaker embeddings
# ---------------------------------------------------------------------------


def voice_embedding_path(voice_file: str) -> str:
    """Return the .npy sidecar path for a given voice WAV path."""
    return os.path.splitext(voice_file)[0] + ".npy"


def load_voice_embedding(voice_file: str):
    """Load a cached MLX speaker embedding from disk, or return None."""
    try:
        import mlx.core as mx
    except ImportError:
        return None

    emb_path = voice_embedding_path(voice_file)
    if os.path.exists(emb_path):
        try:
            res = mx.load(emb_path)
            if isinstance(res, mx.array):
                return res
        except Exception:
            os.remove(emb_path)
    return None


def save_voice_embedding(voice_file: str, embedding) -> None:
    """Persist an MLX speaker embedding to a .npy sidecar next to the WAV."""
    try:
        import mlx.core as mx

        emb_path = voice_embedding_path(voice_file)
        mx.save(emb_path, embedding)
    except Exception:
        pass
