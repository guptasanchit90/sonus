# Riffusion Engine

Text-to-music generation via spectrogram diffusion. Riffusion fine-tunes Stable Diffusion v1.5 to generate mel-spectrogram images, which are then converted to audio via Griffin-Lim phase reconstruction.

## Models

| Model Key | HF Repo | Size | Capabilities |
|---|---|---|---|
| `riffusion-v1` | `GitMylo/riffusion-model-v1-small` | ~2.13 GB | text-to-music |

## Download

```bash
# Downloads the raw .ckpt checkpoint (not Diffusers-format)
hf download GitMylo/riffusion-model-v1-small --local-dir models/riffusion/riffusion-v1

# Downloads pipeline config files (JSON schemas, tokenizer) — avoids network on every load
hf download riffusion/riffusion-model-v1 --local-dir models/riffusion/riffusion-v1/riffusion-v1-config --include '*.json' --include '*.txt'
```

## Install Dependencies

```bash
pip install diffusers accelerate librosa
```

## Usage

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"riffusion-v1","input":"lo-fi hip hop beats, warm, chill","voice":"default"}' \
  --output music.mp3
```

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `duration` | float | 5.0 | 1–30 s | Output duration. Auto-tiles for >5.12 s. |
| `num_inference_steps` | int | 50 | 10–150 | Diffusion steps. Fewer = faster, lower quality. |

## Architecture

1. Text prompt → Stable Diffusion UNet → 512×512 mel-spectrogram image
2. Spectrogram image → Griffin-Lim reconstruction → 44.1 kHz mono WAV
3. WAV → ffmpeg → 24 kHz MP3 (standard Sonus pipeline)

Each inference pass produces ~5.12 s. For longer durations the engine runs N passes and concatenates the clips.

## Performance (Apple Silicon M-series)

| Duration | Tiles | ~Time (MPS) |
|---|---|---|
| 5 s | 1 | 20–40 s |
| 10 s | 2 | 40–80 s |
| 30 s | 6 | 2–4 min |

## Notes

- Riffusion is not gated — no HF token or TOS acceptance required.
- `PYTORCH_ENABLE_MPS_FALLBACK=1` is set automatically by the engine for Apple Silicon compatibility.
- Output is mono 44.1 kHz; stereo extension is not supported.
