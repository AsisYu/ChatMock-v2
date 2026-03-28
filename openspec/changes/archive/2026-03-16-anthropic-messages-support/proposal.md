## Why

ChatMock currently supports OpenAI (`/v1/chat/completions`) and Ollama (`/api/chat`) API formats, but lacks support for Anthropic Claude API (`/v1/messages`). Adding Anthropic compatibility would enable users with Anthropic SDK integrations to use ChatMock as a drop-in replacement, expanding the proxy's utility to a third major API ecosystem.

This is valuable because:
- Anthropic SDK is widely adopted in AI applications
- Users can migrate existing Anthropic-based applications without code changes
- Provides unified access to ChatGPT backend through multiple API standards

## What Changes

- **NEW**: Flask Blueprint `anthropic_bp` handling `/v1/messages` endpoint
- **NEW**: Message format transformation layer (Anthropic → Responses API)
- **NEW**: Tool definition normalization (`input_schema` → `parameters`)
- **NEW**: Tool result conversion (`tool_result` content block → `tool` role message)
- **NEW**: SSE streaming event translation (Responses API → Anthropic format)
- **NEW**: Configuration options for Anthropic model mapping
- **MODIFIED**: `__init__.py` to register the new blueprint

## Capabilities

### New Capabilities

- `anthropic-messages`: Anthropic Claude `/v1/messages` API endpoint with request/response transformation
- `anthropic-streaming`: SSE event translation for Anthropic streaming format
- `anthropic-tools`: Tool use and tool result handling for Anthropic API format

### Modified Capabilities

(None - this is a new feature with no requirement changes to existing capabilities)

## Impact

**New Files:**
- `chatmock/routes_anthropic.py` - Flask Blueprint for `/v1/messages`
- `chatmock/transform_anthropic.py` - Message and tool format transformations
- `chatmock/sse_anthropic.py` - SSE event translation for Anthropic format

**Modified Files:**
- `chatmock/__init__.py` - Register `anthropic_bp`
- `chatmock/config.py` - Add Anthropic-specific configuration

**API Endpoints:**
- `POST /v1/messages` - Anthropic messages endpoint (streaming and non-streaming)

**Key Constraints:**
- System prompt maps directly: `system` → `instructions` (low complexity)
- Tool definitions require `input_schema` → `parameters` renaming (low complexity)
- Tool results need role conversion: `tool_result` block → `tool` role message (medium complexity)
- Streaming events need full translation layer (high complexity)
- Only `web_search` tool type supported (inherited from HC-004)