# Sonus Docs

[← Back to README](../README.md)

---

## API Reference

- [Full API Reference](api.md) — every endpoint, every field, every curl example

## Engines

| Engine | Type | What it's good at |
|---|---|---|
| **Qwen3** | MLX (Apple Silicon) | [Premium quality, voice design, voice cloning](engines/qwen.md) |
| **Kokoro** | ONNX | [54 voices, 9 languages, fast](engines/kokoro.md) |
| **Piper** | ONNX | [100+ languages, blazing fast, tiny models](engines/piper.md) |
| **Chatterbox Turbo** | MLX (Apple Silicon) | [Best-in-class voice cloning](engines/chatterbox.md) |
| **Whisper MLX** | MLX (Apple Silicon) | [Speech-to-text, 5 model sizes](engines/whisper.md) |

## Speech to Text

- [Whisper MLX](engines/whisper.md) — transcribe audio locally via MLX
- `POST /v1/audio/transcriptions` — OpenAI-compatible STT endpoint
- `GET /v1/stt/models` — available STT models and download status

## Development

- [Contributing Guide](../CONTRIBUTING.md) — add a new engine (TTS or STT), fix a bug, write better docs
- [Development Setup](development.md) — get your environment ready

---

## Quick Links

| Endpoint | What it does |
|---|---|
| `http://localhost:8000/api-docs` | Interactive Swagger UI — try every endpoint |
| `http://localhost:8000/` | Web UI — the friendly form |
| `GET /health` | Is it alive? Yes/no |
| `GET /v1/voices` | Who can speak? |
| `GET /v1/models` | What's installed? |
| `GET /v1/models/{id}` | Model details |
| `POST /v1/audio/speech` | OpenAI-compatible TTS — drop-in replacement |
| `POST /v1/audio/transcriptions` | OpenAI-compatible STT |
| `GET /v1/stt/models` | Available STT models |
| `../mcp-docs/mcp.md` | MCP (Model Context Protocol) — [docs](mcp.md) |
| `POST /mcp` | MCP streamable HTTP endpoint |
