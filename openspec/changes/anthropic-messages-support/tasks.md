## 1. Core Infrastructure

- [x] 1.1 Create `chatmock/routes_anthropic.py` Flask Blueprint for Anthropic endpoints
- [x] 1.2 Create `chatmock/transform_anthropic.py` for message and tool transformation
- [x] 1.3 Create `chatmock/sse_anthropic.py` for SSE streaming format conversion
- [x] 1.4 Register `anthropic_bp` blueprint in `chatmock/app.py`

## 2. Model Mapping

- [x] 2.1 Implement `_map_anthropic_model()` function for Anthropic → GPT model mapping
- [x] 2.2 Add `ANTHROPIC_MODEL_MAPPING` configuration in `chatmock/config.py`
- [x] 2.3 Support reasoning effort suffixes (e.g., `claude-3-opus-high`)

## 3. Request Transformation

- [x] 3.1 Implement `transform_anthropic_messages()` for message format conversion
- [x] 3.2 Implement `extract_system_prompt()` to extract top-level system parameter
- [x] 3.3 Implement `transform_anthropic_tools()` for tool definition transformation
- [x] 3.4 Implement `transform_tool_choice()` for tool choice mapping

## 4. Response Transformation

- [x] 4.1 Implement non-streaming response transformation to Anthropic format
- [x] 4.2 Implement `_transform_to_anthropic_response()` for response building
- [x] 4.3 Handle `thinking` content blocks for reasoning summaries
- [x] 4.4 Handle `tool_use` content blocks for function calls

## 5. SSE Streaming

- [x] 5.1 Implement `sse_anthropic_stream()` for streaming event translation
- [x] 5.2 Emit `message_start` event with initial message structure
- [x] 5.3 Emit `content_block_start` for text and tool_use blocks
- [x] 5.4 Emit `content_block_delta` for text and JSON deltas
- [x] 5.5 Emit `content_block_stop`, `message_delta`, `message_stop` events
- [x] 5.6 Maintain correct content block index sequencing

## 6. Error Handling

- [x] 6.1 Implement Anthropic-compatible error response format
- [x] 6.2 Validate required fields (model, max_tokens, messages)
- [x] 6.3 Handle tool type validation with appropriate error messages

## 7. Testing

- [x] 7.1 Create `tests/test_anthropic_messages.py` test suite
- [x] 7.2 Test model mapping for various Anthropic model names
- [x] 7.3 Test tool validation and transformation
- [x] 7.4 Test message transformation scenarios
- [x] 7.5 Test system prompt extraction
- [x] 7.6 Test SSE event sequences
- [x] 7.7 Test image block transformation

## 8. Documentation

- [x] 8.1 Update README.md with Anthropic API compatibility section
- [x] 8.2 Update README_CN.md with Anthropic API compatibility section
- [x] 8.3 Add usage examples for Anthropic clients