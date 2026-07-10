# API Reference

The server lives at `http://0.0.0.0:8000`. Hit it with curl, Python, or whatever speaks HTTP.

- Interactive docs (Swagger UI): `http://localhost:8000/api-docs`
- Web UI: `http://localhost:8000/` — a dark-themed form that lets you play with everything

## GET /health — Is it alive?

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

Yep.

---

## GET /v1/voices — Who can speak?

Flat, searchable list of every voice from every engine. Add WAV files to `voices/` and they show up instantly — no restart needed.

```bash
curl http://localhost:8000/v1/voices
```

```json
{
  "object": "list",
  "data": [
    {"id": "Ryan", "engine": "qwen", "category": "built_in"},
    {"id": "Vivian", "engine": "qwen", "category": "built_in"},
    {"id": "af_heart", "engine": "kokoro", "category": "built_in", "language": "en-us"},
    {"id": "my_voice.wav", "engine": "qwen", "category": "cloneable", "size": 123456, "duration": 5.2, "url": "/voice/my_voice.wav"}
  ]
}
```

Cloneable entries include `size`, `duration`, `created_at`, and `url`.

---

## GET /v1/models — OpenAI-style model list

Returns friendly aliases and capabilities for installed models.

```bash
curl http://localhost:8000/v1/models
```

```json
{"object": "list", "data": [
  {"id": "kokoro", "object": "model", "created": 1719000000, "owned_by": "kokoro"},
  {"id": "qwen-voice", "object": "model", "created": 1719000000, "owned_by": "qwen"}
]}
```

| Query param | Effect |
|---|---|
| `?extras=true` | Full detail (capabilities, voices, languages, install info) |
| `?extras=true` also shows unavailable models | Use to see what's downloadable |

---

## GET /v1/models/{model_id} — Model detail

Get a single model by ID. Returns the same shape as the list endpoint.

```bash
curl http://localhost:8000/v1/models/kokoro
```

```json
{"id": "kokoro", "object": "model", "created": 1719000000, "owned_by": "kokoro"}
```

Also supports `?extras=true` for full detail.

---

## GET /v1/models/loaded — List loaded models

Returns details of all models currently loaded in memory caches.

```bash
curl http://localhost:8000/v1/models/loaded
```

```json
{
  "object": "list",
  "data": [
    {
      "model": "kokoro-v1.0",
      "engine": "kokoro",
      "ttl": 30
    }
  ]
}
```

---

## POST /v1/models/unload — Unload models from memory

Unload a specific model or all loaded models from memory.

### Query parameters

| Field | Type | Default | What it does |
|---|---|---|---|
| `model_id` | string | `null` | The ID, tag, or path of the model to unload (e.g. `kokoro-v1.0`, `kokoro`, `en_US-lessac-medium`) |
| `all` | boolean | `false` | Unload all models from memory caches if `true` |

> [!NOTE]
> Either `model_id` or `all=true` must be specified.

### Examples

**Unloading a specific model:**
```bash
curl -X POST "http://localhost:8000/v1/models/unload?model_id=kokoro-v1.0"
```

```json
{
  "status": "success",
  "unloaded": [
    {"model": "kokoro-v1.0", "engine": "kokoro"}
  ]
}
```

**Unloading all models:**
```bash
curl -X POST "http://localhost:8000/v1/models/unload?all=true"
```

---

## POST /v1/audio/speech — OpenAI-compatible TTS

Drop-in replacement for [OpenAI's TTS endpoint](https://platform.openai.com/docs/api-reference/audio/createSpeech). Point your existing code at `http://localhost:8000` and it just works.

### Request body

| Field | Type | Default | What it does |
|---|---|---|---|
| `model` | string | **required** | Alias from `/v1/models` (e.g. `kokoro`, `qwen-voice`, `qwen-clone`) |
| `input` | string | **required** | Text to speak (max 4096 chars) |
| `voice` | string | `null` | Maps to `speaker_name`, `voice_description`, or `sample_voice_file` |
| `response_format` | string | `"mp3"` | `mp3` · `wav` · `pcm` |
| `speed` | number | `1.0` | `0.25` – `4.0` |
| `x-auto-ssml` | header | `true` | Auto-convert plain text to SSML chunks when text ≥ 300 chars |

### How `voice` maps

| Model capability | `voice` becomes |
|---|---|
| `speaker` / `voice_blend` | Speaker name (e.g. `af_heart`, `Vivian`) |
| `voice_prompt` | Voice description (e.g. `"A warm, deep voice"`) |
| `voice_clone` | WAV filename in `voices/` (e.g. `my_voice.wav`) |

### Response

- **Win:** audio file with `Content-Type: audio/mpeg` (or `audio/wav`, `audio/L16`)
- **Header:** `X-Seed: <integer>` and `X-Audio-Duration: <float>`
- **Header (save mode):** Send `x-save-output: true` to persist the file to `outputs/server/`
- **Lose:** JSON `{"detail": "..."}`

### Example

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kokoro",
    "input": "Hello from the OpenAI-compatible endpoint!",
    "voice": "af_bella",
    "speed": 1.0
  }' --output speech.mp3
```

### Text-to-Music & Text-to-SFX Generation

You can use the same `POST /v1/audio/speech` endpoint to generate music and sound effects by specifying a music/SFX model (e.g. `musicgen-small`, `riffusion-v1`, `stable-audio-open-1.0`, or `audiogen-medium`).

#### Mapping parameters for Music/SFX:

| Field | Type | Default | Engine Support / What it does |
|---|---|---|---|
| `model` | string | **required** | Music/SFX model ID (e.g. `musicgen-small`, `riffusion-v1`, `stable-audio-open-1.0`, `audiogen-medium`) |
| `input` | string | **required** | The text prompt describing the music or sound effect to generate (e.g. `"lo-fi hip hop beat with warm vinyl crackle"`) |
| `voice` | string | `null` | Accepted but ignored by music/SFX engines (you can pass `"default"`) |
| `duration` | number | *Varies* | Output duration in seconds. Supported by MusicGen/AudioGen (1-30s), Riffusion (1-30s), and Stable Audio (1-47s). |
| `cfg_weight` | number | *Varies* | Prompt adherence vs. fidelity. Maps to `guidance_scale` for Stable Audio Open. |
| `seed` | integer | `null` | Random seed for reproducibility |

#### Examples:

**Generate Music (MusicGen):**
```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "musicgen-small",
    "input": "lo-fi hip hop beat with vinyl crackle",
    "voice": "default",
    "duration": 15
  }' --output music.wav
```

**Generate Sound Effects (AudioGen):**
```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "audiogen-medium",
    "input": "thunderstorm with heavy rain",
    "voice": "default",
    "duration": 10
  }' --output thunder.wav
```

---

## POST /v1/audio/transcriptions — OpenAI-compatible STT

Transcribe audio using Whisper MLX. Apple Silicon only.

### Request (multipart form)

| Field | Type | Default | What it does |
|---|---|---|---|
| `file` | file | **required** | Audio file (any ffmpeg-readable format) |
| `model` | string | **required** | STT model ID (e.g. `whisper-base`, `whisper-tiny`) |
| `language` | string | `null` | Language hint (`en`, `fr`, etc.) |
| `temperature` | float | `0.0` | Sampling temperature |
| `response_format` | string | `"json"` | `json` · `text` · `verbose_json` |

### Models

| Model ID | Size |
|---|---|
| `whisper-tiny` | ~75 MB |
| `whisper-base` | ~150 MB |
| `whisper-small` | ~500 MB |
| `whisper-medium` | ~1.5 GB |
| `whisper-large-v3` | ~3 GB |

### Example

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@speech.mp3" \
  -F "model=whisper-base" \
  -F "language=en"
```

```json
{"text": "Hello world, this was transcribed locally."}
```

### Header options

| Header | Effect |
|---|---|
| `x-save-output: true` | Saves transcription result as a `.json` file in `outputs/server/` |

---

## GET /v1/stt/models — List STT models

Returns available speech-to-text models and their download status.

```bash
curl http://localhost:8000/v1/stt/models
```

```json
{
  "object": "list",
  "data": [
    {
      "id": "whisper-base",
      "name": "Whisper Base",
      "engine": "whisper_mlx",
      "available": true,
      "size": "~150 MB",
      "install": {"commands": ["hf download mlx-community/whisper-base-mlx --local-dir models/whisper/whisper-base"]}
    }
  ]
}
```

---

## Sound effects (SFX) management

### POST /sfx — Upload a sound effect file

Upload a WAV (or any audio format — ffmpeg auto-converts to 24kHz mono WAV). Sound effect files can be listed, played, or embedded in SSML via the `<audio>` tag.

```bash
curl -X POST http://localhost:8000/sfx \
  -F "file=@explosion.wav" \
  -F "name=explosion"
```

```json
{
  "name": "explosion.wav",
  "duration": 1.5,
  "size": 72000,
  "created_at": 1719000000.0,
  "url": "/sfx/explosion.wav"
}
```

Max upload size: 50 MB. Returns 409 if the file already exists.

### GET /v1/sfx — List all sound effects

Returns a list of all sound effect files in the `sfx/` directory.

```bash
curl http://localhost:8000/v1/sfx
```

```json
{
  "object": "list",
  "data": [
    {
      "name": "explosion.wav",
      "size": 72000,
      "duration": 1.5,
      "created_at": 1719000000.0,
      "url": "/sfx/explosion.wav"
    }
  ]
}
```

### GET /sfx/{name} — Get a sound effect file

Download a sound effect file from the local library.

```bash
curl http://localhost:8000/sfx/explosion.wav --output explosion.wav
```

### PUT /sfx/{name} — Rename an SFX file

Rename a sound effect file in the library.

```bash
curl -X PUT "http://localhost:8000/sfx/explosion.wav?new_name=boom"
```

```json
{
  "name": "boom.wav",
  "url": "/sfx/boom.wav"
}
```

### DELETE /sfx/{name} — Delete a sound effect file

Delete a sound effect from the library.

```bash
curl -X DELETE http://localhost:8000/sfx/explosion.wav
```

```json
{"deleted": "explosion.wav"}
```

---

## Voice management

### POST /voice — Upload a voice file

Upload a WAV (or any audio format — ffmpeg auto-converts). Voice files are used for cloning (Qwen, Chatterbox).

```bash
curl -X POST http://localhost:8000/voice \
  -F "file=@sample.wav" \
  -F "name=my_voice"
```

```json
{
  "name": "my_voice.wav",
  "duration": 5.2,
  "size": 260000,
  "created_at": 1719000000.0,
  "url": "/voice/my_voice.wav"
}
```

Max upload size: 50 MB. Returns 409 if the file already exists.

### POST /voice/stage — Upload to staging (preview before save)

Staged files live in `voices/.staging/` and can be previewed but won't appear in `/v1/voices` until saved.

```bash
curl -X POST http://localhost:8000/voice/stage \
  -F "file=@sample.wav" \
  -F "name=preview_voice"
```

### GET /voice/stage/{name} — Get a staged voice

```bash
curl http://localhost:8000/voice/stage/preview_voice.wav --output preview.wav
```

### DELETE /voice/stage/{name} — Delete a staged voice

```bash
curl -X DELETE http://localhost:8000/voice/stage/preview_voice.wav
```

### POST /voice/stage/{name}/save — Save staged voice permanently

```bash
curl -X POST http://localhost:8000/voice/stage/preview_voice.wav/save
```

### GET /voice/{name} — Download a voice file

```bash
curl http://localhost:8000/voice/my_voice.wav --output my_voice.wav
```

### PUT /voice/{name} — Rename a voice file

```bash
curl -X PUT "http://localhost:8000/voice/my_voice.wav?new_name=renamed_voice"
```

```json
{"name": "renamed_voice.wav", "url": "/voice/renamed_voice.wav"}
```

### DELETE /voice/{name} — Delete a voice file

```bash
curl -X DELETE http://localhost:8000/voice/my_voice.wav
```

```json
{"deleted": "my_voice.wav"}
```

---

## Output management

### GET /outputs/detail — List generated outputs with metadata

```bash
curl http://localhost:8000/outputs/detail
```

```json
[
  {
    "name": "abc123.mp3",
    "size": 48000,
    "duration": 3.2,
    "created_at": 1719000000.0,
    "url": "/output/abc123.mp3",
    "params": {"model": "kokoro", "input": "Hello", "voice": "af_bella", "seed": 12345}
  }
]
```

The `params` field includes generation parameters and E2E validation results (if uploaded via `PUT /output/{filename}/meta`).

### GET /output/{filename} — Download a generated output

```bash
curl http://localhost:8000/output/abc123.mp3 --output speech.mp3
```

### DELETE /output/{filename} — Delete a generated output

```bash
curl -X DELETE http://localhost:8000/output/abc123.mp3
```

```json
{"deleted": "abc123.mp3"}
```

### PUT /output/{filename}/meta — Update output metadata (E2E results)

Used by the web UI to store transcription and WER scores after E2E validation.

```bash
curl -X PUT http://localhost:8000/output/abc123.mp3/meta \
  -H "Content-Type: application/json" \
  -d '{"transcription": "Hello world", "wer": 0.05, "similarity": 0.92}'
```

```json
{"status": "ok"}
```

### DELETE /outputs — Clean up everything

Deletes all generated audio files from `outputs/server/`.

```bash
curl -X DELETE http://localhost:8000/outputs
```

```json
{"deleted": 5, "files": ["abc123.mp3", "def456.mp3", ...]}
```

---

## Errors

All errors come back as JSON:

```json
{"detail": "Something went wrong — here's what"}
```

| HTTP status | What it means |
|---|---|
| `422` | Bad request — unknown model, missing field, bad value |
| `409` | Conflict — file already exists |
| `500` | Server oops — model didn't load, ffmpeg not found, generation bombed |
