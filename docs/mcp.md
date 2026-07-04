# MCP (Model Context Protocol) — Sonus

Sonus exposes an MCP server over [Streamable HTTP](https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/transports/streamable-http/) transport at:

```
POST http://localhost:8000/mcp
```

MCP lets AI assistants (Claude, Cline, Continue, etc.) discover Sonus capabilities — list models, browse voices, search sound effects, inspect presets, and more — without needing to know the REST API.

> **Note:** MCP is for *discovery* and *orchestration*, not for generating audio. To synthesize speech, use the REST API (`POST /v1/audio/speech`) or the Web UI.

---

## Quick Start

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sonus": {
      "command": "uvx",
      "args": ["mcp", "run", "http://localhost:8000/mcp"]
    }
  }
}
```

Or with curl:

```bash
# List all resources
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"resources/list"}'

# Read a resource
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"sonus://models"}}'

# List all tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list"}'

# Call a tool
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_voices","arguments":{"engine":"kokoro"}}}'
```

### Python (mcp SDK)

```python
from mcp import ClientSession, StdioClientSession
from mcp.client.http import HTTPClientSession
import httpx

async with httpx.AsyncClient() as transport:
    async with HTTPClientSession(transport, "http://localhost:8000/mcp") as session:
        resources = await session.list_resources()
        tools = await session.list_tools()
        models = await session.read_resource("sonus://models")
```

---

## Resources

Resources are read-only data URIs an LLM can browse. Sonus exposes these:

| URI | Description |
|---|---|
| `sonus://` | Root overview of all available resources and tools |
| `sonus://models` | All TTS models with capabilities, languages, availability |
| `sonus://voices` | All voices across every engine (104+) with metadata |
| `sonus://voices/{model_id}` | Voices for a specific model (e.g. `sonus://voices/kokoro`) |
| `sonus://stt_models` | All STT models with availability and install instructions |
| `sonus://engines` | All engines (TTS + STT) with model summaries |
| `sonus://sfx` | All sound effects with size, duration, format |
| `sonus://presets` | Saved voice presets |
| `sonus://outputs` | Recently generated audio files |
| `sonus://formats` | Full SSML format specification |

---

## Tools

Tools are actions an LLM can invoke. Sonus provides these:

### `list_models`

Filter and search TTS models.

| Param | Type | Default | Description |
|---|---|---|---|
| `engine` | string | `""` | Filter by engine name (e.g. `kokoro`, `qwen`) |
| `capability` | string | `""` | Filter by capability (e.g. `speaker`, `voice_clone`, `voice_prompt`) |
| `mode` | string | `""` | Filter by mode (e.g. `speaker`, `design`, `clone`) |
| `available_only` | bool | `false` | Show only locally available models |
| `query` | string | `""` | Text search across model ID and name |

### `list_voices`

List voices with optional filters — globally or per-model.

| Param | Type | Default | Description |
|---|---|---|---|
| `model_id` | string | `""` | Restrict to a specific model (e.g. `kokoro`) |
| `language` | string | `""` | Filter by language code (e.g. `en-us`, `ja`, `zh`) |
| `gender` | string | `""` | Filter by gender (`male`, `female`) |
| `tone` | string | `""` | Filter by tone tag (e.g. `warm`, `deep`, `playful`) |
| `category` | string | `""` | Filter by category (`built_in`, `cloneable`) |

### `list_sfx`

List all sound effects. No parameters.

Returns name, size, duration, and format for each file in the `sfx/` directory.

### `list_stt_models`

List speech-to-text models.

| Param | Type | Default | Description |
|---|---|---|---|
| `available_only` | bool | `false` | Show only locally available models |
| `engine` | string | `""` | Filter by engine (`faster_whisper`, `whisper_mlx`) |

### `list_outputs`

List recently generated audio outputs.

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | integer | `20` | Max items to return (max 100) |

### `search_voices`

Advanced cross-engine voice search with relevance scoring.

| Param | Type | Default | Description |
|---|---|---|---|
| `query` | string | `""` | Free-text search in voice name/description/tone_tags |
| `language` | string | `""` | Filter by locale prefix (e.g. `en`, `ja`) |
| `gender` | string | `""` | Filter by gender |
| `age_tier` | string | `""` | Filter by age tier (`young_adult`, `adult`, `senior`) |
| `quality_min` | string | `""` | Minimum quality grade (e.g. `c`, `b`, `a`) |
| `model_id` | string | `""` | Restrict to a specific model |
| `engine` | string | `""` | Restrict to a specific engine |

### `preview_voice`

Get detailed description for a specific voice.

| Param | Type | Description |
|---|---|---|
| `model_id` | string | Model the voice belongs to (e.g. `kokoro`, `qwen-custom`) |
| `voice_id` | string | Voice ID (e.g. `af_heart`, `serena`) |

### `suggest_voice_for_character`

Score and rank voices by character criteria.

| Param | Type | Default | Description |
|---|---|---|---|
| `model_id` | string | — | Model to search within (required) |
| `gender` | string | `""` | Desired gender (2pts) |
| `age` | string | `""` | Desired age tier (2pts) |
| `tone` | string | `""` | Desired tone tag (3pts) |
| `language` | string | `""` | Desired language (2pts) |

### `get_capabilities`

Full Sonus overview — features, available models, resources, tools, and REST API endpoints.

No parameters. Returns a comprehensive document LLMs can use to understand what Sonus can do.

---

## Best Practices for LLMs

1. **Start with `get_capabilities()`** to understand what's available.
2. **Browse resources** (`sonus://models`, `sonus://voices`) to find what you need.
3. **Use `search_voices()`** when you need a voice with specific qualities (warm, deep, female, Japanese, etc.).
4. **Use `list_models()`** with filters to narrow down to the right engine.
5. **Call `preview_voice()`** to get a full voice description before suggesting it.
6. **Check `sonus://sfx`** to see available sound effects for SSML `<audio>` embedding.
7. **Browse `sonus://presets`** to reuse existing configurations.
