# Fish Speech Engine

Text-to-speech with voice cloning. Two model variants:

- **Fish Speech V1.5** — 1M+ hours training, 13 languages, zero-shot voice cloning
- **Fish Audio S2 Pro** — Dual-AR 4B model, emotion control via tags (`[laugh]`, `[whisper]`), multi-speaker

## Models

| Model Key | HF Repo | Size | Languages |
|---|---|---|---|
| `fish-speech-1.5` | `fishaudio/fish-speech-1.5` | ~1.2 GB | 13 languages |
| `s2-pro` | `fishaudio/s2-pro` | ~8.5 GB | 13 languages |

## Download

```bash
# Fish Speech V1.5
hf download fishaudio/fish-speech-1.5 --local-dir models/fish_speech/fish-speech-1.5

# S2 Pro
hf download fishaudio/s2-pro --local-dir models/fish_speech/s2-pro
```

## Install Dependencies

```bash
# For V1.5 (PyTorch)
pip install fish-speech torch

# For S2 Pro — prefer MLX on Apple Silicon:
pip install mlx-speech

# Fallback for S2 Pro (PyTorch):
pip install fish-speech torch
```

## Usage

Place a reference `.wav` file (3–10 s) in `voices/` with an optional `.txt` transcript:

```bash
# V1.5 with voice cloning
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"fish-speech-1.5","input":"Hello, this is a voice clone.","voice":"my_voice.wav"}' \
  --output speech.wav

# S2 Pro with voice cloning
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"s2-pro","input":"(happy) This sounds amazing!","voice":"my_voice.wav"}' \
  --output speech.wav
```

## Voice Preparation

| File | Required | Description |
|---|---|---|
| `voices/my_voice.wav` | Yes | 3–10 s reference audio |
| `voices/my_voice.txt` | Recommended | Exact transcript of the reference |

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `temperature` | float | 0.7 | Sampling temperature (0.1–1.0) |

## Notes

- S2 Pro supports emotion tags: `[laugh]`, `[whisper]`, `[sigh]`, `[emphasis]`, etc.
- S2 Pro prefers `mlx-speech` (MLX-native) on Apple Silicon; falls back to PyTorch.
- V1.5 always uses the `fish-speech` PyTorch package.
