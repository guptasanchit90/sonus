<p align="center">
  <img src="static/logo.jpg" width="160" alt="Sonus Logo" style="border-radius: 16px;" />
</p>

# Sonus — Speak freely

Multi-engine, offline audio hub (Speech, Music, SFX, STT) on your Mac. No cloud. No API keys. No one listening.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13+-blue.svg)](.python-version)
[![Platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)](https://www.apple.com/mac/)
Runs on [MLX](https://github.com/ml-explore/mlx) and [ONNX Runtime](https://onnxruntime.ai/) — Apple Silicon for MLX engines, **any platform** for ONNX engines (Kokoro, Piper).

> **About the name:** *Sonus* is Latin for "sound" (/ˈsoː.nus/). Felt right for a project about making machines talk.
>
> **ℹ️** Not affiliated with any company, service, or organization named Sonus. Just a coincidence. We're an independent open-source thing.
>
> *[Opencode](https://opencode.ai) — vibecoded by AI, tested by humans.*

---

## What is this?

Sonus turns text into speech/music/SFX (and speech into text) using whatever engine you throw at it. Multiple engines, one unified API. Run it locally, hit the endpoint, get audio back. Zero data leaves your machine.

Think of it as a **local audio hub** — TTS via Qwen3, Kokoro, Piper, Chatterbox, CosyVoice, and Fish Speech; Speech-to-Music/SFX via MusicGen, Riffusion, and Stable Audio Open; and STT via Whisper. All offline, all local.

---

## Run in the cloud

No Mac? No problem. Kokoro and Piper (ONNX engines) work on any platform. Click a badge to open a pre-configured notebook — it installs everything, downloads models, starts the server, and gives you a public URL.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/guptasanchit90/sonus/blob/main/notebooks/colab_quickstart.ipynb)
[![Open In Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)](https://www.kaggle.com/kernels/welcome?src=https://raw.githubusercontent.com/guptasanchit90/sonus/main/notebooks/kaggle_quickstart.ipynb)
[![Open In SageMaker Studio Lab](https://img.shields.io/badge/Open%20in-SageMaker%20Studio%20Lab-important?logo=amazon-aws)](https://studiolab.sagemaker.aws/import/github/guptasanchit90/sonus/blob/main/notebooks/sagemaker_quickstart.ipynb)

---

## Engines at a glance

| Engine | Framework | Type / Modality | Vibe / Capabilities |
|---|---|---|---|
| **Qwen3** | MLX | TTS | Premium quality. Sounds almost human. 🍎 Apple Silicon only. |
| **Kokoro** | ONNX | TTS | The multilingual workhorse. Fast, reliable. ✅ Cross-platform. |
| **Piper** | ONNX | TTS | The speed demon. 100+ languages, tiny footprint. ✅ Cross-platform. |
| **Chatterbox Turbo** | MLX | TTS | Best-in-class cloning. Feed it a WAV, get a twin. 🍎 Apple Silicon only. |
| **CosyVoice2** | PyTorch | TTS | Zero-shot TTS, emotion/prosody control. ✅ Cross-platform. |
| **Fish Speech** | PyTorch / MLX | TTS | Multilingual TTS with voice cloning. ✅ Cross-platform / 🍎. |
| **MusicGen / AudioGen** | MLX | Music / SFX | Text-to-music & text-to-sfx on GPU. 🍎 Apple Silicon only. |
| **Riffusion** | Diffusers (PyTorch) | Music | Fast text-to-music via spectrogram diffusion. ✅ Cross-platform. |
| **Stable Audio Open** | Diffusers (PyTorch) | Music / SFX | High-quality stereo audio, up to 47 seconds. ✅ Cross-platform. |
| **Whisper MLX** | MLX | STT | Speech-to-text. Transcribe anything. 🍎 Apple Silicon only. |

More on each engine:
- [Qwen3](docs/engines/qwen.md) — custom voice, voice design, voice cloning
- [Kokoro](docs/engines/kokoro.md) — 54 built-in voices, 9 languages
- [Piper](docs/engines/piper.md) — fastest inference, widest language support
- [Chatterbox Turbo](docs/engines/chatterbox.md) — voice cloning via MLX
- [CosyVoice2](docs/engines/cosyvoice.md) — zero-shot TTS and prosody control
- [Fish Speech](docs/engines/fish_speech.md) — multilingual TTS with voice cloning
- [MusicGen / AudioGen](docs/engines/musicgen.md) — text-to-music and text-to-sfx
- [Riffusion](docs/engines/riffusion.md) — text-to-music via diffusion
- [Stable Audio Open](docs/engines/stable_audio.md) — stereo music and SFX generation
- [Whisper MLX](docs/engines/whisper.md) — speech-to-text via MLX
- [API Reference](docs/api.md) — full endpoint docs

---

## What you'll need

**Local (macOS Apple Silicon):**
- A Mac with Apple Silicon (M1, M2, M3, M4 — anything with Metal)
- Python 3.13+ (`brew install python@3.13`)
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg`

> **Running in Docker?** Only Kokoro and Piper work there. Qwen3 and Chatterbox need the Metal GPU backend. See each engine's doc for details.

---

## Get started in 30 seconds

```bash
git clone https://github.com/YOUR_USERNAME/sonus.git
cd sonus

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
```

Download models for at least one engine (check the engine docs above), then:

```bash
source venv/bin/activate
python server.py
# Listening on http://0.0.0.0:8000
```

Interactive API docs: **http://localhost:8000/api-docs**

---

## Try it

```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "model": "kokoro-v1.0", "speaker_name": "af_heart"}' \
  --output hello.mp3
```

### Speaking OpenAI's language

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "kokoro", "input": "Hello world", "voice": "af_bella"}' \
  --output hello.mp3
```

Drop-in replacement for `POST /v1/audio/speech`. Your existing OpenAI TTS code works without changes — just point it at `http://localhost:8000`.

### Speech to text (OpenAI-compatible)

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@speech.mp3" \
  -F "model=whisper-base" \
  -F "language=en" \
  -F "temperature=0.0"
```

```json
{"text": "Hello world, this was transcribed locally."}
```

---

## Documentation

| Resource | What's inside |
|---|---|
| [API Reference](docs/api.md) | Every endpoint, schema, curl example |
| [Docs Home](docs/index.md) | Full docs index |
| [Development Guide](docs/development.md) | Setup, linting, testing, Docker |
| [Contributing](CONTRIBUTING.md) | Adding engines, code style, PRs |

---

## How it's built

```
server.py               # FastAPI — the brain
src/
  engines/
    base.py             # The contract every TTS/generation engine signs
    qwen.py             # Qwen3 (MLX)
    chatterbox.py       # Chatterbox Turbo (MLX)
    kokoro.py           # Kokoro (ONNX)
    piper.py            # Piper (ONNX)
    cosyvoice.py        # CosyVoice2 (PyTorch)
    fish_speech.py      # Fish Speech (PyTorch/MLX)
    musicgen.py         # MusicGen & AudioGen (MLX)
    riffusion.py        # Riffusion (PyTorch/Diffusers)
    stable_audio.py     # Stable Audio Open (PyTorch/Diffusers)
  stt/
    base.py             # The contract every STT engine signs
    whisper_mlx.py      # Whisper via MLX (Apple Silicon)
static/                 # Web UI — Vue 3 (CDN), no build step
docs/                   # API, engine, development, and MCP docs
models/                 # Downloaded models (gitignored)
voices/                 # WAVs for voice cloning
sfx/                    # Sound effects database
outputs/                # Generated audio files
```

---

## Built with

| Tool | Role | How we use it |
|---|---|---|
| [Opencode](https://opencode.ai) | AI pair programmer | Vibecoded most of this thing |
| [VS Code](https://code.visualstudio.com) | Editor | Where the magic happens |
| [FastAPI](https://fastapi.tiangolo.com) | Web framework | Routes, validation, docs |
| [Uvicorn](https://www.uvicorn.org) | ASGI server | Serves it all up |
| [MLX](https://github.com/ml-explore/mlx) | ML framework | Apple Silicon superpowers |
| [mlx-audio](https://github.com/Blaizzy/mlx-audio) | Audio model loader | Loads Qwen3, Chatterbox models |
| [pydub](https://github.com/jiaaro/pydub) | Audio conversion | WAV ↔ MP3 magic |
| [soundfile](https://python-soundfile.readthedocs.io) | WAV I/O | Reads and writes WAVs |
| [Piper](https://github.com/rhasspy/piper) | TTS engine | Speed king, ONNX-powered |
| [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) | TTS engine | Multilingual, ONNX-powered |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | TTS engine | Premium quality, MLX-powered |
| [Chatterbox Turbo](https://huggingface.co/mlx-community/Chatterbox-Turbo-TTS-fp16) | TTS engine | Cloning specialist, MLX-powered |
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | TTS engine | Zero-shot multilingual TTS |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | TTS engine | Multilingual TTS and voice cloning |
| [mlx-audiocraft](https://github.com/theashishmaurya/mlx-audiocraft) | Music/SFX engine | Loads MusicGen & AudioGen models |
| [diffusers](https://github.com/huggingface/diffusers) | Audio diffusion | Powers Riffusion and Stable Audio Open |
| [torch](https://pytorch.org) | ML framework | Backend for PyTorch engines (CosyVoice, Fish Speech, Diffusers) |
| [librosa](https://librosa.org) | Audio processing | Mel spectrogram conversion for Riffusion |
| [accelerate](https://github.com/huggingface/accelerate) | PyTorch hardware acceleration | Speeds up diffusion model inference |
| [mlx-whisper](https://github.com/ml-explore/mlx-whisper) | STT engine | Speech-to-text, MLX-powered |
| [Whisper](https://github.com/openai/whisper) | STT model | OpenAI's transcription model |

---

## Disclaimer

Yes, this thing can make audio that sounds like real people. **You're responsible for what you do with it.**

- **Don't** impersonate people without their consent.
- **Don't** create deceptive, fraudulent, or misleading content.
- **Do** respect the laws where you live.
- The authors assume **zero liability** for misuse.

Use it wisely. Or don't — but that's on you.

---

## License

MIT — do what you want with it, just keep the notice.
