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

List all TTS models. No parameters.

Returns every registered model with its engine, mode, capabilities, languages, and availability status.

### `list_voices`

List all voices across every engine. No parameters.

Returns voices enriched with metadata (gender, age_tier, tone_tags, quality_grade, description).

### `list_sfx`

List all sound effects. No parameters.

Returns name, size, duration, and format for each file in the `sfx/` directory.

### `list_stt_models`

List all speech-to-text models. No parameters.

Returns every STT model with engine, languages, availability, and install info.

### `list_outputs`

List recently generated audio outputs (last 20). No parameters.

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
2. **Use `list_models()`** or browse the `sonus://models` resource to see all TTS models.
3. **Use `list_voices()`** or browse `sonus://voices` to see all available voices.
4. **Use `search_voices()`** when you need a voice with specific qualities (warm, deep, female, Japanese, etc.).
5. **Call `preview_voice()`** to get a full voice description before suggesting it.
6. **Check `sonus://sfx`** to see available sound effects for SSML `<audio>` embedding.
7. **Browse `sonus://presets`** to reuse existing configurations.
