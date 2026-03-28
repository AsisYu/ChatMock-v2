## Why

Enable Anthropic Claude API compatibility in ChatMock so that applications built for Anthropic's API can seamlessly use ChatGPT's GPT-5 models through ChatMock's OAuth-authenticated proxy. This eliminates the need for users to maintain separate API integrations or migrate their codebases when switching between Anthropic and OpenAI ecosystems.

## What Changes

- Add new `/v1/messages` endpoint implementing Anthropic Messages API format
- Transform Anthropic-style requests to ChatGPT Responses API format
- Transform ChatGPT Responses API output back to Anthropic response format
- Map Anthropic model names (claude-3-opus, claude-3-sonnet, claude-3-haiku) to GPT-5 equivalents
- Support both streaming (SSE) and non-streaming responses in Anthropic format
- Handle Anthropic-specific features: system prompts, tool definitions, tool choice
- Support Anthropic thinking content blocks for reasoning summaries

## Capabilities

### New Capabilities

- `anthropic-messages`: Core `/v1/messages` endpoint with request/response transformation, model mapping, system prompt handling, and error formatting per Anthropic API specification
- `anthropic-streaming`: SSE streaming format conversion from ChatGPT Responses API to Anthropic's streaming event sequence (message_start, content_block_start, content_block_delta, content_block_stop, message_delta, message_stop)
- `anthropic-tools`: Tool/function calling transformation between Anthropic and ChatGPT formats, including tool_result message handling and web_search tool support

### Modified Capabilities

(None - this is a new feature addition with no changes to existing OpenAI/Ollama endpoints)

## Impact

**New Files:**
- `chatmock/routes_anthropic.py` - Flask Blueprint for Anthropic endpoints
- `chatmock/transform_anthropic.py` - Message and tool transformation utilities
- `chatmock/sse_anthropic.py` - SSE streaming format conversion

**Modified Files:**
- `chatmock/app.py` - Register anthropic_bp blueprint
- `chatmock/config.py` - Add ANTHROPIC_MODEL_MAPPING and related constants

**API Surface:**
- New endpoint: `POST /v1/messages` (Anthropic-compatible)
- No changes to existing OpenAI (`/v1/*`) or Ollama (`/api/*`) endpoints

**Dependencies:**
- No new external dependencies
- Uses existing Flask, requests, and JWT handling infrastructure

**Testing:**
- `tests/test_anthropic_messages.py` - Comprehensive test coverage for model mapping, tool validation, message transformation, SSE events, and image block handling