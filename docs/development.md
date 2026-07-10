# Development Setup

## What you'll need

- A Mac with Apple Silicon (M1–M4)
- Python 3.13+ (`brew install python@3.13`)
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)

## First time

```bash
git clone https://github.com/YOUR_USERNAME/sonus.git
cd sonus

python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **Keep it in the venv.** Don't use system `pip3` or `python3` directly — you'll have a bad time.

## Run it

```bash
source venv/bin/activate
python server.py          # fires up on http://0.0.0.0:8000
```

Where to find things:
- Interactive API docs: `http://localhost:8000/api-docs`
- Web UI: `http://localhost:8000/`
- OpenAI-compatible Speech/Music/SFX: `http://localhost:8000/v1/audio/speech`
- OpenAI-compatible STT: `http://localhost:8000/v1/audio/transcriptions`
- SFX library management: `http://localhost:8000/v1/sfx`

## Lint & typecheck

Tool config lives in `pyproject.toml`:

```bash
ruff check server.py src/
ruff format server.py src/
pyright server.py src/
```

## Tests

```bash
venv/bin/pytest tests/ -v
```

New tests go in `tests/` using `pytest`.

## Model download

Each engine needs its own model files. See `docs/engines/` for the download ritual.

Use `GET /v1/models?extras=true` to see all models with download commands in the `install` field — or open the web UI and click the install button on any unavailable model.

### Docker

Kokoro and Piper can run in Docker (Qwen and Chatterbox need the Metal GPU, so no Docker for them):

```bash
docker build -t tts-server .
docker run -p 8000:8000 \
  -v "$(pwd)/models:/app/models" \
  -v "$(pwd)/voices:/app/voices" \
  -v "$(pwd)/outputs:/app/outputs" \
  tts-server
```
