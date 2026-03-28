## ADDED Requirements

(This capability has been implemented. Full requirements exist in openspec/specs/anthropic-streaming/spec.md)

### Requirement: SSE Event Translation

The system must translate Responses API SSE events to Anthropic SSE event format during streaming responses.

#### Scenario: Message initialization

- **WHEN** the Responses API emits a `response.created` event

- **THEN** the system emits an Anthropic `message_start` event with id, type, role, content, model, stop_reason, usage

#### Scenario: Complete message flow

- **WHEN** streaming a complete response with text and tool calls

- **THEN** the system emits events in Anthropic order: message_start, content_block_start, content_block_delta, content_block_stop, message_delta, message_stop