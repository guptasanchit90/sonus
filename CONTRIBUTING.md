# Contributing

Pull requests, bug reports, and new engines — all welcome. Let's build the best local TTS server together.

---

## What's in here

- [Getting Started](#getting-started)
- [How it's built](#how-its-built)
- [Adding a New Engine](#adding-a-new-engine)
- [Code Style](#code-style)
- [OpenAI-Compatible Endpoint](#openai-compatible-endpoint)
- [Output File Conventions](#output-file-conventions)
- [Key Dependencies](#key-dependencies)
- [Reporting Bugs](#reporting-bugs)
- [Pull Requests](#pull-requests)

---

## Getting Started

```bash
git clone https://github.com/YOUR_USERNAME/sonus.git
cd sonus

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
```

Download models for at least one engine (see `docs/engines/`) and you're off.

---

## How it's built

A FastAPI server that wraps multiple audio generation (TTS, music, SFX) and transcription (STT) engines behind a single HTTP API. Audio generation engines live in `src/engines/` and implement the `TTSEngine` protocol (`src/engines/base.py`). STT engines live in `src/stt/` and implement the `STTEngine` protocol (`src/stt/base.py`).

```
server.py              # FastAPI app — routing, entry point
src/
  utils.py             # Helpers everyone shares (voice resolution, ffmpeg, memory)
  cache.py             # ModelCache[T] — TTL eviction for MLX engines
  audio.py             # Loudness normalization, silence trim, format conversion
  engines/
    base.py            # TTSEngine protocol + @register decorator + BaseEngine mixin
    qwen.py            # Qwen3 via mlx-audio (Apple Silicon)
    chatterbox.py      # Chatterbox Turbo via mlx-audio (Apple Silicon)
    kokoro.py          # Kokoro-82M via kokoro-onnx (ONNX)
    piper.py           # Piper via piper-tts (ONNX)
    cosyvoice.py       # CosyVoice2 (PyTorch)
    fish_speech.py     # Fish Speech (PyTorch/MLX)
    musicgen.py        # MusicGen & AudioGen (MLX)
    riffusion.py       # Riffusion (PyTorch/Diffusers)
    stable_audio.py    # Stable Audio Open (PyTorch/Diffusers)
    __init__.py        # Imports everything so @register fires
  stt/
    base.py            # STTEngine protocol + @register decorator + BaseSTTEngine mixin
    whisper_mlx.py     # Whisper via mlx-whisper (Apple Silicon)
    __init__.py        # Imports everything so @register fires
static/
  index.html           # Web UI — Vue 3 (CDN), no build step
  app.js               # Web UI logic — components, store, app
models/                # Downloaded models (gitignored)
voices/                # Your WAV samples for cloning (gitignored)
sfx/                   # Sound effects database (gitignored except .gitkeep)
outputs/               # Generated audio lands here (gitignored)
docs/                  # API, engine, development, and MCP docs
```

---

## Adding a New Engine

Engines auto-register via the `@register` decorator. **You don't touch `server.py`.** Drop in a file, decorate it, done.

### Steps

| # | Do this |
|---|---|
| 1 | Create `src/engines/<name>.py` implementing `TTSEngine` |
| 2 | Slap `@register` on it from `src.engines.base` |
| 3 | Set `engine_name` property (used by `/voices`) |
| 4 | Import shared goodies from `src.utils` instead of rolling your own |
| 5 | MLX engine? Use `ModelCache` from `src.cache` |
| 6 | Register your module in `src/engines/__init__.py` |
| 7 | Write `docs/engines/<name>.md` |

### Template

```python
# src/engines/myengine.py
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install fastapi") from exc

from src.utils import VOICES_DIR, SAMPLE_RATE, resolve_voice, clean_memory
from .base import BaseEngine, register

MODELS_DIR = os.path.join(os.getcwd(), "models", "myengine")
MODEL_ID = "my-voice-model"


@register
class MyEngine(BaseEngine):
    @property
    def engine_name(self) -> str:
        return "myengine"

    def claims(self, model: str) -> bool:
        return model == MODEL_ID

    def list_models(self) -> list[dict]:
        return [{
            "engine": "myengine",
            "model": MODEL_ID,
            "mode": "speaker",
            "available": os.path.exists(MODELS_DIR),
        }]

    def list_voices(self) -> dict:
        return super().list_voices()

    def validate(self, request: dict) -> None:
        _model = request["model"]
        if _model != MODEL_ID:
            raise HTTPException(status_code=422, detail=f"Unknown model '{_model}'")

    def generate(self, request: dict, tmp_dir: str) -> str:
        text = request["text"]
        wav_path = os.path.join(tmp_dir, "audio_000.wav")
        # ... make some noise ...
        if not os.path.exists(wav_path):
            raise HTTPException(status_code=500, detail="TTS produced no output file")
        return wav_path
```

### STT Engine

Speech-to-text engines work the same way but live in `src/stt/` and use the `STTEngine` protocol from `src/stt/base.py`.

```python
# src/stt/myengine.py
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

_AVAILABLE = False
try:
    import my_stt_lib
    _AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install fastapi") from exc

from src.cache import ModelCache
from .base import BaseSTTEngine, register


@register
class MySTTEngine(BaseSTTEngine):
    @property
    def engine_name(self) -> str:
        return "my_stt"

    def claims(self, model: str) -> bool:
        return model == "my-stt-model"

    def list_models(self) -> list[dict]:
        return [{
            "id": "my-stt-model",
            "name": "My STT Model",
            "engine": self.engine_name,
            "model": "my-stt-model",
            "mode": "stt",
            "capabilities": ["transcribe"],
            "description": "...",
            "available": _AVAILABLE,
            "languages": ["en", "multi"],
            "size": "~500 MB",
            "install": {"commands": ["hf download ..."]},
        }]

    def list_voices(self) -> dict:
        return {}

    def validate(self, request: dict) -> None:
        if request["model"] != "my-stt-model":
            raise HTTPException(status_code=422, detail="Unknown model")

    def transcribe(
        self, audio_path: str, model: str, language: str | None, temperature: float
    ) -> dict:
        # ... transcribe audio ...
        return {"text": "transcription result", "segments": [], "detected_language": "en"}
```

### The five methods you must implement (TTS Engine)

| Method | Job |
|---|---|
| `claims(model)` | Return `True` if this engine handles this model string |
| `list_models()` | Return model metadata dicts |
| `list_voices()` | Return `{category: [voice_id, ...]}` |
| `validate(request)` | Raise `HTTPException(422)` on bad input (runs before model loading) |
| `generate(request, tmp_dir)` | Run the model, write `audio_000.wav`, return its path |

### Shared utilities (`src/utils.py`)

| Function | What it does |
|---|---|
| `resolve_voice(filename)` | Find a `.wav` in `voices/` |
| `model_path(base_dir, folder)` | Resolve model folder (handles HF snapshots) |
| `get_audio_duration(filepath)` | Ask ffprobe how long an audio file is |
| `convert_to_wav_24k(in, out)` | Re-encode to 24kHz mono WAV via ffmpeg |
| `clean_memory()` | `gc.collect()` + `mx.clear_cache()` if MLX is around |
| `scan_wav_voices(dir)` | List `.wav` files in a directory (sorted, no dotfiles) |

Shared constants: `MODELS_DIR`, `VOICES_DIR`, `SAMPLE_RATE`.

### Model cache for MLX engines

MLX engines should cache loaded models with `ModelCache`:

```python
from src.cache import ModelCache

_model_cache = ModelCache(ttl=10, tag="myengine")

def generate(self, request, tmp_dir):
    model = _model_cache.get_or_load(
        request["model"],
        lambda: load_model(Path(model_path)),
    )
    # ... use model ...
```

### Engine file structure (convention)

1. Stdlib imports (alphabetical)
2. Warning suppression
3. `try/except ImportError` for optional platform deps (MLX) — set `_MLX_AVAILABLE`
4. `try/except ImportError` for hard deps (fastapi)
5. Shared imports from `src.utils`, `src.cache`
6. Engine-specific imports from `.base`
7. Constants (`MODELS_DIR`, `MODEL_ID`, engine-specific maps)
8. Helpers (prefixed with `_`)
9. `@register` class

---

## Code Style

### General

- **Engines go in `src/engines/`.** Shared stuff in `src/utils.py`, `src/cache.py`, `src/audio.py`.
- **No classes outside engine files.** Everywhere else, keep it procedural.
- **Keep lines under ~100 chars.** Match the vibe around you.
- **No trailing whitespace.**

### Imports

Group in this order, separated by blank lines:

1. Stdlib (alphabetical)
2. Warning suppression
3. Third-party `try/except ImportError` (optional — `mlx`)
4. Third-party `try/except ImportError` (hard — `fastapi`)
5. Project modules (`src.utils`, `src.cache`)
6. Relative engine imports (`.base`)

```python
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

_MLX_AVAILABLE = False
try:
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model
    _MLX_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import HTTPException
except ImportError as exc:
    raise ImportError("fastapi is not installed. Run: pip install -r requirements.txt") from exc

from src.cache import ModelCache
from src.utils import VOICES_DIR, SAMPLE_RATE, resolve_voice, clean_memory
from .base import BaseEngine, register
```

- No `from foo import *`.
- Lazy imports inside a function are OK for platform-specific modules.

### Naming

| Kind | Style | Example |
|---|---|---|
| Functions | `snake_case` verb_noun | `load_model`, `scan_voices`, `clean_memory` |
| Constants | `UPPER_SNAKE_CASE` | `MODELS_DIR`, `SAMPLE_RATE` |
| Private helpers | `_leading_underscore` | `_model_path`, `_resolve_voice` |
| Local variables | `snake_case` | `tmp_dir`, `wav_path` |
| Booleans | Positive prefix | `_MLX_AVAILABLE`, `is_valid` |
| Engine property | `engine_name` (property) | `return "qwen"` |

### Type annotations

Engine files use type annotations. Keep 'em:

```python
def claims(self, model: str) -> bool: ...
def list_models(self) -> list[dict]: ...
```

- Use `str | None` over `Optional[str]`.
- `server.py` has none — adding them is welcome but not required.
- If you annotate, annotate everything consistently.

### Constants

Per-engine constants in the engine file. Shared constants in `src/utils.py`:

```python
# src/utils.py (shared)
MODELS_DIR  = os.path.join(os.getcwd(), "models")
VOICES_DIR  = os.path.join(os.getcwd(), "voices")
SAMPLE_RATE = 24000

# Engine file (your engine's stuff)
MODELS_DIR = os.path.join(os.getcwd(), "models", "myengine")
```

Use `os.getcwd()`. Never hardcode paths.

### Error handling

**In engines** — raise `HTTPException` so FastAPI gives a clean JSON error:

```python
raise HTTPException(status_code=422, detail="'voice_description' is required")
raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
```

**Guard clauses** — return `None` early instead of nesting:

```python
def _model_path(folder_name: str) -> str | None:
    full = os.path.join(MODELS_DIR, folder_name)
    if not os.path.exists(full):
        return None
    return full
```

**Silent suppression** — for optional features only:

```python
try:
    import termios
    termios.tcflush(sys.stdin, termios.TCIOFLUSH)
except (ImportError, OSError):
    pass
```

- Never use bare `except:` — catch at minimum `Exception`.
- Don't re-raise without a reason.
- Always clean up resources in `finally`.

### Path handling

- `os.path.join` for everything. No string concatenation.
- Temp dirs: `tempfile.gettempdir()` + unique suffix. Clean up with `shutil.rmtree`.

### Subprocess

```python
subprocess.run(
    ["ffmpeg", "-y", "-v", "error", "-i", src, dst],
    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
)
```

Use `check=True` when failure matters (ffmpeg). Use `check=False` for optional stuff (`afplay`).

### Memory management

Call `clean_memory()` after releasing MLX models:

```python
finally:
    del model
    clean_memory()
```

`ModelCache` calls `clean_memory()` automatically on eviction.

### Warning suppression

Top of every engine file:

```python
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
```

`os.environ["TOKENIZERS_PARALLELISM"] = "false"` is set once in `server.py`.

---

## OpenAI-Compatible Endpoint

The server exposes `POST /v1/audio/speech` that speaks OpenAI's TTS API dialect.

### Model aliases

The manifest is built **dynamically** from each engine's `list_models()` at request time:

```python
def list_models(self) -> list[dict]:
    return [{
        "id": "kokoro",
        "name": "Kokoro 82M",
        "engine": "kokoro",
        "model": "kokoro-v1.0",
        "mode": "speaker",
        "capabilities": ["speaker", "voice_blend"],
        "description": "...",
        "available": True,
    }]
```

For catch-all engines (Piper — voice files ARE the models), use `"model": ""`.

New in 0.2.0: Models can include an `"install"` field with download commands, shown in the web UI install modal:

```python
"install": {
    "commands": [
        "hf download org/repo --local-dir models/myengine/model",
    ],
}
```

### Voice field mapping

| Capability | `voice` param becomes |
|---|---|
| `speaker` / `voice_blend` | `speaker_name` |
| `voice_prompt` | `voice_description` |
| `voice_clone` | `sample_voice_file` |

### Adding a new alias

Add an entry to `list_models()`:
1. Pick a short `id` (unique across all engines)
2. Set `engine` to `engine_name`
3. Set `model` to the internal model identifier
4. Declare `capabilities`
5. Set `available` based on model file presence

### OpenAI name mapping

`OPENAI_MODEL_ALIASES` in `server.py` maps `tts-1`, `tts-1-hd` to aliases from the dynamic manifest.

---

## Output File Conventions

- Generated audio → `outputs/server/<uuid>.mp3` (or `.wav`, `.pcm`)
- JSON metadata → `outputs/server/<uuid>.mp3.json` (params, E2E results)
- STT results → `outputs/server/<uuid>.json` (with `x-save-output: true`)
- Temp work dirs → `<tempdir>/tts_<uuid>/` (deleted after each request)
- Clone voices → `voices/*.wav` (gitignored except `.gitkeep`)
- Speaker embeddings → `voices/*.npy` (cached, gitignored)
- Staged voices → `voices/.staging/*.wav` (pre-save preview)
- Sound effects → `sfx/*.wav` (gitignored except `.gitkeep`)
- Piper models → `models/piper/<name>.onnx` + `<name>.onnx.json`
- Kokoro models → `models/kokoro/kokoro-v1.0.onnx` + `voices-v1.0.bin`
- Qwen models → `models/qwen/<folder>/` (HF snapshot layout)
- Chatterbox → `models/chatterbox/<folder>/`
- Whisper STT models → `models/whisper/<model_id>/` (HF snapshot layout)

## Chatterbox Turbo Model Setup

```bash
source venv/bin/activate
hf download mlx-community/Chatterbox-Turbo-TTS-fp16
```

The fp16 variant (~1.2 GB) lives in the HuggingFace cache. S3TokenizerV2 auto-downloads on first load.

---

## Tool Configuration

Lint and typecheck settings live in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
```

Run with:

```bash
ruff check server.py src/
ruff format server.py src/
pyright server.py src/
```

---

## Key Dependencies

| Package | Who uses it | What for |
|---|---|---|
| `fastapi`, `uvicorn` | `server.py` | Serving HTTP |
| `mlx`, `mlx-audio`, `mlx-metal` | `qwen.py`, `chatterbox.py` | Apple Silicon GPU inference |
| `mlx-whisper` | `whisper_mlx.py` | Apple Silicon Whisper inference |
| `kokoro-onnx` | `kokoro.py` | Kokoro ONNX |
| `piper-tts` | `piper.py` | Piper ONNX |
| `numpy`, `soundfile` | `kokoro.py` | Audio arrays |
| `mlx-audiocraft` | `musicgen.py` | MusicGen and AudioGen model inference |
| `diffusers` | `riffusion.py`, `stable_audio.py` | Spec/latent diffusion pipeline |
| `torch` | `cosyvoice.py`, `fish_speech.py`, diffusion engines | PyTorch inference backend |
| `librosa` | `riffusion.py` | Audio loading and mel spectrogram math |
| `accelerate` | diffusion engines | Fast PyTorch GPU scaling |
| `transformers`, `tokenizers` | `mlx-audio`, `mlx-whisper` (transitive) | Tokenisation |
| `huggingface_hub` | `mlx-audio`, `mlx-whisper` (transitive) | Model downloads |

Pin direct dependencies with `==` in `requirements.txt`. Transitive deps install automatically — don't pin them unless you need to.

---

## Reporting Bugs

Open an issue with:
- macOS version and chip (e.g. M2 Pro)
- Python version (`python3 --version`)
- The exact command that broke
- Full error output

---

## Pull Requests

- One logical change per PR.
- Update docs if you change behaviour.
- Test with at least one engine before submitting.
