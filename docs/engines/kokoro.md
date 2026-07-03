# Kokoro Engine

[Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx) running on ONNX Runtime. 54 built-in voices across 9 languages. Fast, reliable, multilingual.

> Kokoro is fully deterministic — same input, same output, every time. No seed needed.

---

## Model Download

Two files, one folder:

```bash
mkdir -p models/kokoro
cd models/kokoro
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Expected layout:

```
models/
└── kokoro/
    ├── kokoro-v1.0.onnx    (~300 MB)
    └── voices-v1.0.bin
```

Use `"kokoro-v1.0"` as the `model` value in all requests.

---

## Try it

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kokoro",
    "input": "Hello! This is Kokoro running locally.",
    "voice": "af_heart",
    "speed": 1.0
  }' \
  --output speech.mp3
```

---

## Voices

Voice IDs start with a two-letter prefix that tells you the language and gender:

| Prefix | Language | Example voices |
|---|---|---|
| `af_` / `am_` | American English | `af_heart`, `af_bella`, `am_fenrir`, `am_michael` |
| `bf_` / `bm_` | British English | `bf_emma`, `bf_alice`, `bm_george`, `bm_daniel` |
| `jf_` / `jm_` | Japanese | `jf_alpha`, `jm_kumo` |
| `zf_` / `zm_` | Mandarin Chinese | `zf_xiaobei`, `zm_yunxi` |
| `ef_` / `em_` | Spanish | `ef_dora`, `em_alex` |
| `ff_` | French | `ff_siwis` |
| `hf_` / `hm_` | Hindi | `hf_alpha`, `hm_omega` |
| `if_` / `im_` | Italian | `if_sara`, `im_nicola` |
| `pf_` / `pm_` | Brazilian Portuguese | `pf_dora`, `pm_alex` |

See the full list at `GET /v1/voices`.

### All voices

**American English** — `af_heart`, `af_alloy`, `af_aoede`, `af_bella`, `af_jessica`, `af_kore`, `af_nicole`, `af_nova`, `af_river`, `af_sarah`, `af_sky`, `am_adam`, `am_echo`, `am_eric`, `am_fenrir`, `am_liam`, `am_michael`, `am_onyx`, `am_puck`, `am_santa`

**British English** — `bf_alice`, `bf_emma`, `bf_isabella`, `bf_lily`, `bm_daniel`, `bm_fable`, `bm_george`, `bm_lewis`

**Japanese** — `jf_alpha`, `jf_gongitsune`, `jf_nezumi`, `jf_tebukuro`, `jm_kumo`

**Mandarin Chinese** — `zf_xiaobei`, `zf_xiaoni`, `zf_xiaoxiao`, `zf_xiaoyi`, `zm_yunjian`, `zm_yunxi`, `zm_yunxia`, `zm_yunyang`

**Spanish** — `ef_dora`, `em_alex`, `em_santa`

**French** — `ff_siwis`

**Hindi** — `hf_alpha`, `hf_beta`, `hm_omega`, `hm_psi`

**Italian** — `if_sara`, `im_nicola`

**Brazilian Portuguese** — `pf_dora`, `pm_alex`, `pm_santa`

---

## Voice blending

Blend two or more voices by passing comma-separated IDs with optional weights:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kokoro",
    "input": "This voice is a blend of two voices.",
    "voice": "af_heart:0.3,af_bella:0.7",
    "speed": 1.0
  }' \
  --output speech.mp3
```

Default weight is `0.5` if omitted. Use the `voice_blend` capability via the `"voice"` field with comma-separated voice IDs.

---

## Auto-SSML

When `x-auto-ssml: true` (default) and input text is ≥ 300 characters, plain text is automatically converted to SSML `<speak>` with `<p>` (paragraph) and `<s>` (sentence) chunks. This improves quality by keeping each chunk in Kokoro's 100–200 token sweet spot. Send `x-auto-ssml: false` to bypass.

---

## Speed

| Value | Multiplier |
|---|---|
| `0.8` | 0.8× |
| `1.0` | 1.0× |
| `1.3` | 1.3× |

Range: `0.25` – `4.0`

---

## Limitations

- No voice cloning
- No voice design
- `temperature` and `seed` are accepted but ignored (ONNX is deterministic)
- Voice blending via `voice` field with comma-separated IDs (e.g. `"af_heart:0.3,af_bella:0.7"`)

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Model files not found | Download both `.onnx` and `.bin` to `models/kokoro/` |
| Unknown voice | Check `GET /v1/voices` for valid names |
| Audio sounds robotic | Try `af_heart` — it's a blend of bella + sarah, best quality |
