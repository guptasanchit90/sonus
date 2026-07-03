# Changelog

## 0.2.0 (2025-06-30)

- **Speech-to-text subsystem** — Whisper MLX engine (5 model sizes from tiny to large-v3)
- **STT endpoints** — `GET /v1/stt/models`, `POST /v1/audio/transcriptions` (OpenAI-compatible)
- **E2E validation** — web UI can transcribe TTS output and display WER/similarity
- **Voice management API** — `POST /voice`, `PUT /voice/{name}`, `DELETE /voice/{name}`, staging endpoints
- **Output management API** — `GET /outputs/detail`, `PUT /output/{filename}/meta`, per-file delete
- **Access control** — path traversal protection (`os.path.realpath` checks on all file endpoints)
- **Model manifests** — `install` field in manifests (download commands per engine)
- **Install modal** — web UI shows model download instructions from engine manifests
- **Model listing** — `?extras=true` for full details, `?available_only` filtering
- **Web UI** — E2E validation workflow, batch generation across engines, install modal
- **Kokoro voice blending** — comma-separated voices with optional weights
- **Kokoro `add_pauses` removed** — replaced by auto-SSML chunking
- **Qwen 4bit Base model** — `qwen-clone` alias for 1.7B-Base-4bit (~1.6 GB)
- **Qwen Lite Voice Design** — `qwen-lite-voice` (0.6B-VoiceDesign-8bit)
- **Speaker embedding caching** — Qwen voice cloning performance optimization
- **pyproject.toml** — ruff and pyright configuration

## 0.1.0 (2025-06-27)

- Initial release
- Qwen3 engine: custom voice, voice design, voice cloning (MLX)
- Kokoro engine: 54 voices, 9 languages (ONNX)
- Piper engine: 40+ languages, per-voice models (ONNX)
- Chatterbox Turbo engine: high-quality voice cloning (MLX)
- OpenAI-compatible `/v1/audio/speech` endpoint
- Dark-themed web UI
- Docker support (Kokoro + Piper)
