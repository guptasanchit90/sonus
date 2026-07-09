# MusicGen + AudioGen Engine

Generates music and sound effects from text prompts on Apple Silicon via MLX.

Powered by [`mlx-audiocraft`](https://github.com/theashishmaurya/mlx-audiocraft).

## Models

| Model ID | Parameters | Type | Quality | Download |
|----------|-----------|------|---------|----------|
| `musicgen-small` | 300M | music | Good | ~1.2 GB |
| `musicgen-medium` | 1.5B | music | Better | ~3.2 GB |
| `musicgen-large` | 3.3B | music | Best | ~6.5 GB |
| `audiogen-medium` | 1.5B | sound effects | Good | ~3.6 GB |

## Requirements

- macOS 13+ with Apple Silicon (M1/M2/M3/M4)
- `pip install mlx-audiocraft`

## Download a model

```bash
hf download mlx-community/musicgen-small --local-dir models/musicgen/musicgen-small
```

Replace `musicgen-small` with any model ID from the table above.

## Usage

### Generate music (OpenAI-compatible endpoint)

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "musicgen-small",
    "input": "lo-fi hip hop beat with vinyl crackle",
    "voice": "default"
  }' --output music.wav
```

### Generate sound effects

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "audiogen-medium",
    "input": "thunderstorm with heavy rain",
    "voice": "default"
  }' --output thunder.wav
```

### Extra parameters

Pass `duration` (1-30 seconds, default 10) as a top-level JSON field:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "musicgen-small",
    "input": "jazz trio, piano and double bass",
    "voice": "default",
    "duration": 15
  }' --output jazz.wav
```

## Capabilities

- `musicgen-small/medium/large`: `text_to_music`
- `audiogen-medium`: `text_to_sfx`
- No voice concept — `voice` field is accepted but ignored
- English prompts only
- Duration: 1–30 seconds

## Notes

- Models download on first use (lazy loading).
- The T5 text encoder runs in PyTorch (CPU). The transformer LM and EnCodec decoder run on Apple GPU via MLX.
- Output is converted to 24kHz mono WAV (the Sonus standard) regardless of the native model sample rate.