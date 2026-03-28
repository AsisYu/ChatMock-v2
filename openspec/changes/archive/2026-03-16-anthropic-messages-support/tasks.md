## 1. Core Infrastructure

- [x] 1.1 Create `chatmock/routes_anthropic.py` with Flask Blueprint `anthropic_bp`
- [x] 1.2 Implement `/v1/messages` POST endpoint skeleton with request validation
- [x] 1.3 Register `anthropic_bp` in `chatmock/__init__.py`
- [x] 1.4 Add Anthropic-specific configuration to `chatmock/config.py` (model mapping defaults)

## 2. Message Transformation

- [x] 2.1 Create `chatmock/transform_anthropic.py` module
- [x] 2.2 Implement `transform_anthropic_messages()` for text content blocks
- [x] 2.3 Implement `extract_system_prompt()` to map `system` → `instructions`
- [x] 2.4 Handle `image` content blocks in message transformation
- [x] 2.5 Implement `transform_anthropic_tools()` to convert `input_schema` → `parameters`
- [x] 2.6 Implement `tool_result` → `tool` role message transformation
- [x] 2.7 Handle `tool_use` content blocks in assistant messages

## 3. Tool Handling

- [x] 3.1 Implement `tool_choice` mapping (`auto`, `any`, specific tool)
- [x] 3.2 Enforce `web_search` tool type constraint with proper error response
- [x] 3.3 Handle tool result with `is_error: true` flag
- [x] 3.4 Handle tool result with multiple content items

## 4. Streaming Support

- [x] 4.1 Create `chatmock/sse_anthropic.py` module
- [x] 4.2 Implement `message_start` event generation from `response.created`
- [x] 4.3 Implement `content_block_start` / `content_block_delta` / `content_block_stop` for text streaming
- [x] 4.4 Implement tool call streaming events (`tool_use` type)
- [x] 4.5 Implement `message_delta` and `message_stop` events from `response.completed`
- [x] 4.6 Handle content block index management for multiple blocks
- [x] 4.7 Implement unknown event handling (log and skip)

## 5. Non-Streaming Response

- [x] 5.1 Transform Responses API output to Anthropic message format
- [x] 5.2 Map stop reasons correctly (end_turn, max_tokens, tool_use)
- [x] 5.3 Calculate and return usage statistics

## 6. Error Handling

- [x] 6.1 Implement Anthropic-compatible error response format
- [x] 6.2 Add validation errors for missing required fields (model, max_tokens, messages)
- [x] 6.3 Handle upstream API errors and transform to Anthropic format

## 7. Model Mapping

- [x] 7.1 Implement model name mapping with defaults (claude-3-opus → gpt-5, etc.)
- [x] 7.2 Add logging for unmapped model names (fallback to default)
- [x] 7.3 Support model reasoning effort suffixes (e.g., claude-3-opus-high)

## 8. Testing & Polish

- [x] 8.1 Test non-streaming message request with text content
- [x] 8.2 Test streaming message request with SSE events
- [x] 8.3 Test tool definition transformation
- [x] 8.4 Test tool_use and tool_result handling
- [x] 8.5 Test error response format
- [x] 8.6 Add comprehensive logging for debugging