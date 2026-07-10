# AudioLDM Engine

Text-to-audio and sound effects (SFX) generation via latent diffusion. AudioLDM maps text prompts to continuous audio embeddings, translating them into waveforms at a native 16 kHz sample rate.

## Models

| Model Key | HF Repo | Size | Capabilities |
|---|---|---|---|
| `audioldm-s-full-v2` | `cvssp/audioldm-s-full-v2` | ~800 MB | text-to-sfx, text-to-music |
| `audioldm-m-full` | `cvssp/audioldm-m-full` | ~1.5 GB | text-to-sfx, text-to-music |
| `audioldm-l-full` | `cvssp/audioldm-l-full` | ~3.0 GB | text-to-sfx, text-to-music |

## Download

```bash
# Downloads the standard small model
hf download cvssp/audioldm-s-full-v2 --local-dir models/audioldm/audioldm-s-full-v2
```

## Install Dependencies

```bash
pip install diffusers transformers torch
```

## Usage

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"audioldm-s-full-v2","input":"a hammer hitting a wooden table, loud impact","voice":"default"}' \
  --output hammer.mp3
```

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `duration` | float | 5.0 | 1–30 s | Output duration in seconds. |
| `num_inference_steps` | int | 50 | 1–200 | Denoising steps. Fewer = faster, lower quality. |
| `guidance_scale` | float | 2.5 | 1.0–20.0 | Classifier-free guidance. Higher = closer prompt adherence. |

## Notes

- AudioLDM outputs native 16 kHz mono audio, which is resampled by Sonus to 24 kHz WAV for API delivery.
- Uses CPU-based seeding to support reproducible generation outputs on macOS (MPS).
