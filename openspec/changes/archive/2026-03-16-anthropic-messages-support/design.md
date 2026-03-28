# Design: Anthropic Messages Support

## Context

ChatMock is a Flask-based API proxy that currently supports:
- **OpenAI API** (`/v1/chat/completions`, `/v1/completions`, `/v1/models`) via `openai_bp`
- **Ollama API** (`/api/chat`, `/api/generate`, `/api/tags`) via `ollama_bp`

All requests are transformed and forwarded to ChatGPT's Responses API (`https://chatgpt.com/backend-api/codex/responses`) using ChatGPT Plus/Pro OAuth tokens.

### Existing Patterns

1. **Blueprint Structure**: Each API format has its own Flask Blueprint with request transformation
2. **Message Transformation**: `transform.py` provides `convert_ollama_messages()` pattern
3. **Tool Normalization**: `normalize_ollama_tools()` wraps tools in function structure
4. **SSE Translation**: `sse_translate_chat()` transforms Responses API SSE to OpenAI format
5. **Upstream Request**: `start_upstream_request()` builds Responses API payload

### Key Constraints

| ID | Constraint | Source |
|----|------------|--------|
| HC-001 | Upstream only accepts Responses API format | upstream.py |
| HC-004 | Only `web_search` tool type supported | routes_openai.py:120-140 |
| HC-ANTH-002 | `system` → `instructions` mapping required | Anthropic API spec |
| HC-ANTH-003 | `input_schema` → `parameters` conversion needed | Anthropic API spec |
| HC-ANTH-004 | `tool_result` block → `tool` role message | Anthropic API spec |
| HC-ANTH-005 | Full SSE event translation layer required | Anthropic streaming spec |

## Goals

1. **Implement `/v1/messages` endpoint** with full Anthropic Claude API compatibility
2. **Support streaming responses** with proper SSE event translation
3. **Handle all content block types**: `text`, `image`, `tool_use`, `tool_result`
4. **Map tool definitions** from Anthropic format to Responses API format
5. **Provide model name mapping** configuration for Claude model names

## Non-Goals

1. **Batch API support** - Only single-message synchronous/streaming API
2. **Vision-only endpoints** - Images handled within message content blocks
3. **Custom tool types** - Only `web_search` supported (inherited constraint)
4. **Token counting endpoints** - No `/v1/messages/count_tokens` endpoint
5. **Legacy Claude API** - Only Claude 3+ Messages API format

## Decisions

### D1: Blueprint Structure

**Decision**: Create dedicated `anthropic_bp` Flask Blueprint

**Rationale**:
- Follows existing pattern (`openai_bp`, `ollama_bp`)
- Isolates Anthropic-specific logic
- Clean endpoint registration in `__init__.py`

**Implementation**:
```
chatmock/
├── routes_anthropic.py    # Flask Blueprint for /v1/messages
├── transform_anthropic.py # Message transformation functions
└── sse_anthropic.py       # SSE event translation
```

### D2: Message Transformation Strategy

**Decision**: Create dedicated transformation module with three functions

**Rationale**:
- Anthropic format differs significantly from OpenAI/Ollama
- Reusable transformation functions for testing
- Clear separation of concerns

**Functions**:
1. `transform_anthropic_messages(messages)` - Convert Anthropic messages to Responses API input
2. `transform_anthropic_tools(tools)` - Convert `input_schema` to `parameters`
3. `extract_system_prompt(request)` - Extract and map `system` to `instructions`

### D3: Tool Result Handling

**Decision**: Convert `tool_result` content blocks to `tool` role messages

**Rationale**:
- Anthropic: `{"type": "tool_result", "tool_use_id": "...", "content": "..."}`
- Responses API: `{"role": "tool", "tool_call_id": "...", "content": "..."}`

**Mapping**:
```
tool_result.type       → (implicit, role: tool)
tool_result.tool_use_id → tool_call_id
tool_result.content    → content
```

### D4: SSE Event Translation

**Decision**: Create bidirectional SSE translation layer

**Rationale**: Anthropic streaming events differ from Responses API events

**Event Mapping**:

| Responses API Event | Anthropic Event |
|---------------------|-----------------|
| `response.created` | `message_start` |
| `response.output_text.delta` | `content_block_delta` (type: text_delta) |
| `response.tool_call` | `content_block_start` (type: tool_use) |
| `response.completed` | `message_delta` + `message_stop` |

**Structure**:
```python
def translate_sse_to_anthropic(responses_event: dict) -> list[dict]:
    """Convert Responses API SSE event to Anthropic SSE events."""
    # Returns list because one Responses API event may map to multiple Anthropic events
```

### D5: Model Name Mapping

**Decision**: Configurable model mapping with sensible defaults

**Rationale**: Users expect Claude model names, but backend uses GPT models

**Configuration**:
```python
ANTHROPIC_MODEL_MAPPING = {
    "claude-3-opus": "gpt-5",
    "claude-3-opus-20240229": "gpt-5",
    "claude-3-sonnet": "gpt-5.1",
    "claude-3-sonnet-20240229": "gpt-5.1",
    "claude-3-haiku": "gpt-5.2",
    "claude-3-haiku-20240307": "gpt-5.2",
    "claude-3-5-sonnet": "gpt-5.4",
    "claude-3-5-sonnet-20241022": "gpt-5.4",
    "claude-3-5-haiku": "gpt-5.2",
    "claude-3-5-haiku-20241022": "gpt-5.2",
}
```

### D6: Error Response Format

**Decision**: Return Anthropic-compatible error responses

**Rationale**: Anthropic SDK expects specific error format

**Format**:
```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "..."
  }
}
```

## Risks & Trade-offs

### R1: Streaming Event Edge Cases

**Risk**: Complex streaming scenarios may have unmapped event types

**Mitigation**:
- Log unknown events for debugging
- Graceful degradation (pass through or skip)
- Comprehensive test coverage

**Severity**: Medium

### R2: API Format Changes

**Risk**: Anthropic or Responses API may change formats

**Mitigation**:
- Modular transformation functions for easy updates
- Version-specific handling if needed
- Monitoring of API changelogs

**Severity**: Medium

### R3: Model Capability Differences

**Risk**: Claude and GPT models have different capabilities

**Mitigation**:
- Document known differences
- Map to closest equivalent model
- User configuration for custom mapping

**Severity**: Low

### R4: Tool Use Flow Complexity

**Risk**: Tool use with multiple tool calls may have ordering issues

**Mitigation**:
- Track `tool_use_id` → `tool_call_id` mapping
- Preserve order in transformation
- Test multi-tool scenarios

**Severity**: Medium

## Implementation Phases

### Phase 1: Core Infrastructure
- Create `routes_anthropic.py` with `/v1/messages` endpoint
- Implement basic request handling
- Register blueprint in `__init__.py`

### Phase 2: Message Transformation
- Implement `transform_anthropic.py`
- Handle all content block types
- Add tool normalization

### Phase 3: Streaming Support
- Implement `sse_anthropic.py`
- Add SSE event translation
- Handle streaming edge cases

### Phase 4: Configuration & Polish
- Add model mapping configuration
- Implement error response format
- Add comprehensive logging