## Context

ChatMock is an OpenAI/Ollama compatible API proxy that routes requests to ChatGPT's Responses API using OAuth authentication. Users have requested the ability to use Anthropic Claude SDK-compatible clients with ChatMock, enabling them to switch between Anthropic and OpenAI backends without code changes.

The existing architecture uses Flask Blueprints for routing, with transformation layers between incoming request formats and the ChatGPT Responses API. This design extends that pattern to support Anthropic's Messages API format.

**Current State:**
- OpenAI-compatible endpoints at `/v1/chat/completions`, `/v1/completions`, `/v1/models`
- Ollama-compatible endpoints at `/api/chat`, `/api/generate`, `/api/tags`
- Model mapping: GPT-5 family with reasoning effort suffixes
- SSE streaming translation for OpenAI format

**Constraints:**
- Must not break existing OpenAI/Ollama endpoints
- Must use existing OAuth infrastructure (no separate Anthropic auth)
- Must map Anthropic models to GPT-5 equivalents (no actual Claude models available)

## Goals / Non-Goals

**Goals:**
- Provide Anthropic-compatible `/v1/messages` endpoint
- Support both streaming and non-streaming responses
- Transform Anthropic tool/function calling format
- Support Anthropic-specific features (system prompt, thinking blocks)
- Maintain API parity for common use cases

**Non-Goals:**
- Full Anthropic API feature coverage (e.g., caching controls, metadata)
- Actual Claude model access (only GPT-5 model mapping)
- Anthropic-specific authentication (uses ChatGPT OAuth)
- Prompt caching optimizations

## Decisions

### 1. Blueprint Architecture
**Decision:** Create separate `anthropic_bp` Flask Blueprint at `/v1/messages`

**Rationale:**
- Follows existing pattern (`openai_bp`, `ollama_bp`)
- Clean separation of concerns
- No risk of endpoint conflicts
- Easy to enable/disable independently

**Alternatives Considered:**
- Merge into `openai_bp`: Would complicate routing and transformation logic
- Single unified transformation layer: Too complex with divergent formats

### 2. Model Mapping Strategy
**Decision:** Map Anthropic model names to GPT-5 equivalents with fallback

**Mapping Table:**
| Anthropic Model | GPT Equivalent | Rationale |
|-----------------|----------------|-----------|
| claude-3-opus | gpt-5 | Flagship model mapping |
| claude-3-sonnet | gpt-5.1 | Mid-tier capability |
| claude-3-haiku | gpt-5.2 | Fast, efficient option |
| claude-3-5-sonnet | gpt-5.3 | Latest mid-tier |
| claude-3-5-haiku | gpt-5.4 | Latest fast model |

**Rationale:**
- Provides sensible defaults for common Anthropic model names
- Allows users to specify GPT models directly (passthrough)
- Supports reasoning effort suffixes (e.g., `claude-3-opus-high`)

### 3. System Prompt Handling
**Decision:** Map Anthropic's top-level `system` parameter to Responses API `instructions`

**Rationale:**
- Direct semantic mapping
- Responses API accepts `instructions` as a top-level parameter
- No message array manipulation needed

### 4. Tool Result Transformation
**Decision:** Transform Anthropic `tool_result` content blocks to `tool` role messages

**Rationale:**
- Anthropic: `tool_result` is a content block within a user message
- Responses API: Tool results are separate `tool` role messages
- Transformation happens during message conversion

**Implementation:**
1. Detect `tool_result` content blocks in user messages
2. Split into separate `tool` role messages with `tool_call_id`
3. Preserve content and error status

### 5. SSE Event Translation
**Decision:** Implement bidirectional SSE event translation for streaming

**Anthropic Event Sequence:**
1. `message_start` - Initialize message with id, model, empty content
2. `content_block_start` - Start text or tool_use block
3. `content_block_delta` - Stream text or JSON deltas
4. `content_block_stop` - Close content block
5. `message_delta` - Update stop_reason and usage
6. `message_stop` - Signal completion

**Rationale:**
- Anthropic clients expect specific event sequence
- Must maintain content block indices across stream
- Tool use requires nested JSON delta handling

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Model capability mismatch | Document mapping clearly; users can override with GPT model names directly |
| Missing Anthropic features | Return helpful errors for unsupported features; document limitations |
| SSE event ordering bugs | Comprehensive test coverage for event sequences |
| Tool transformation edge cases | Extensive test suite for message/tool transformations |
| Rate limit header differences | Use existing ChatGPT rate limit tracking |

## Migration Plan

**Deployment:**
1. No migration needed - additive feature
2. Update documentation to mention Anthropic compatibility
3. Users can immediately start using `/v1/messages` endpoint

**Rollback:**
- Remove `anthropic_bp` registration in `app.py`
- No data migration required
- No configuration changes needed

## Open Questions

(None - implementation complete and tested)