# CosyVoice2 Engine

Zero-shot multilingual text-to-speech by Alibaba's FunAudioLLM. Supports voice cloning, emotion/prosody control, and cross-lingual synthesis.

## Model

| Model Key | HF Repo | Size | Languages |
|---|---|---|---|
| `cosyvoice2-0.5b` | `FunAudioLLM/CosyVoice2-0.5B` | ~5.6 GB | zh, en, ja, ko, yue |

## Download

```bash
hf download FunAudioLLM/CosyVoice2-0.5B --local-dir models/cosyvoice/CosyVoice2-0.5B
```

## Install Dependencies

```bash
pip install cosyvoice torch
```

If Matcha-TTS is not bundled, clone it manually:

```bash
git clone https://github.com/shivammehta25/Matcha-TTS third_party/Matcha-TTS
```

## Usage

Place a reference `.wav` file (3–10 s) in `voices/` with an optional `.txt` transcript:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"cosyvoice2-0.5b","input":"你好，欢迎使用 CosyVoice。","voice":"my_voice.wav"}' \
  --output speech.wav
```

## Voice Preparation

| File | Required | Description |
|---|---|---|
| `voices/my_voice.wav` | Yes | 3–10 s reference audio at any sample rate |
| `voices/my_voice.txt` | Recommended | Exact transcript of the reference |

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `temperature` | float | 0.7 | Sampling temperature |

## Instruct Mode

CosyVoice2 supports fine-grained control via special tags:
- `<laughter></laughter>` — insert laughter
- `<strong></strong>` — emphasize words
- `[laughter]` — alternative laugh tag
- `[breath]` — breathing sound

## Notes

- Native output is 22.05 kHz mono; converted to 24 kHz by Sonus.
- Modelscope mirror: `iic/CosyVoice2-0.5B`
- No separate MLX version available; runs via PyTorch with MPS acceleration on Apple Silicon.
- `third_party/Matcha-TTS` is auto-detected from the repo root if installed.
