# Stable Audio Open Engine

Text-to-music generation via latent diffusion. Stable Audio Open generates variable-length (up to 47 s) stereo audio at 44.1 kHz from text prompts. Uses a three-component architecture: autoencoder waveform compression, T5 text encoder, and transformer-based diffusion (DiT).

## Model

| Model Key | HF Repo | Size | Capabilities |
|---|---|---|---|
| `stable-audio-open-1.0` | `stabilityai/stable-audio-open-1.0` | ~3.2 GB | text-to-music |

## Download

```bash
hf download stabilityai/stable-audio-open-1.0 --local-dir models/stable_audio/stable-audio-open-1.0
```

## Install Dependencies

```bash
pip install diffusers torch
```

`diffusers>=0.30.0` is already listed in requirements.txt.

## Usage

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"stable-audio-open-1.0","input":"lo-fi hip hop beat with warm vinyl crackle","voice":"default","duration":10}' \
  --output music.wav
```

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `duration` | float | 10.0 | 1–47 s | Output duration in seconds |
| `num_inference_steps` | int | 100 | 1–250 | Diffusion steps. Higher = better quality. |
| `guidance_scale` | float | 7.0 | 1.0–25.0 | Prompt adherence vs. fidelity. Higher = closer to prompt. |
| `negative_prompt` | str | `"low quality, average quality"` | — | Describe what to avoid in the output |

## Architecture

1. Text prompt → T5 text encoder → embeddings
2. Embeddings + duration conditioning → DiT (transformer denoiser) → latents
3. Latents → Oobleck VAE decoder → 44.1 kHz stereo waveform
4. WAV → ffmpeg → 24 kHz stereo WAV (Sonus pipeline)

## Performance (Apple Silicon M-series)

Duration | ~Time (MPS, float32)
---|---
5 s | 60–90 s
10 s | 90–150 s
30 s | 3–5 min

## Notes

- Output is **stereo** 24 kHz WAV (unlike most Sonus engines which output mono).
- `PYTORCH_ENABLE_MPS_FALLBACK=1` is set automatically for Apple Silicon compatibility.
- The model is **not gated** — no HF token or TOS acceptance required.
- Uses `diffusers.StableAudioPipeline` — no `stable-audio-tools` package needed.
