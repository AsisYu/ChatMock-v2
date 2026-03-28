## ADDED Requirements

(This capability has been implemented. Full requirements exist in openspec/specs/anthropic-messages/spec.md)

### Requirement: POST /v1/messages Endpoint

The system must provide an Anthropic-compatible `/v1/messages` endpoint that accepts Anthropic Claude API format requests and returns valid responses.

#### Scenario: Non-streaming message request

- **WHEN** a client sends a POST request to `/v1/messages` with Anthropic format (model, max_tokens, messages, optional system)

- **THEN** the system transforms the request to Responses API format, forwards to ChatGPT, and returns a valid Anthropic-format response

#### Scenario: Streaming message request

- **WHEN** a client sends a POST request to `/v1/messages` with `stream: true`

- **THEN** the system returns SSE events in Anthropic streaming format (message_start, content_block_start, content_block_delta, content_block_stop, message_delta, message_stop)