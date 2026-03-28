# Anthropic Messages Capability

## ADDED Requirements

### Requirement: POST /v1/messages Endpoint

The system must provide an Anthropic-compatible `/v1/messages` endpoint that accepts Anthropic Claude API format requests and returns valid responses.

#### Scenario: Non-streaming message request

WHEN a client sends a POST request to `/v1/messages` with:
- `model`: Anthropic model name (e.g., `claude-3-opus-20240229`)
- `max_tokens`: Maximum tokens to generate
- `messages`: Array of message objects with `role` and `content`
- `system`: (optional) System prompt

THEN the system:
- Transforms the Anthropic format to Responses API format
- Forwards the request to ChatGPT Responses API
- Returns a valid Anthropic-format response with `id`, `type`, `role`, `content`, `model`, `stop_reason`, `usage`

#### Scenario: Streaming message request

WHEN a client sends a POST request to `/v1/messages` with `stream: true`

THEN the system:
- Returns SSE events in Anthropic streaming format
- Emits events: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`

### Requirement: System Prompt Mapping

The system must map Anthropic's top-level `system` parameter to Responses API's `instructions` parameter.

#### Scenario: System prompt provided

WHEN a request includes a `system` parameter at the top level

THEN the system:
- Maps `system` value to the `instructions` field in the Responses API payload
- Preserves the system prompt content without modification

#### Scenario: No system prompt provided

WHEN a request does not include a `system` parameter

THEN the system:
- Sends `instructions` as null or omits the field in the Responses API payload

### Requirement: Model Name Mapping

The system must provide configurable model name mapping from Anthropic model names to GPT model names.

#### Scenario: Known Anthropic model name

WHEN a request specifies a known Anthropic model (e.g., `claude-3-opus`, `claude-3-sonnet`, `claude-3-haiku`)

THEN the system:
- Maps to the configured GPT model equivalent
- Default mapping: `claude-3-opus` → `gpt-5`, `claude-3-sonnet` → `gpt-5.1`, `claude-3-haiku` → `gpt-5.2`

#### Scenario: Unknown model name

WHEN a request specifies an unmapped model name

THEN the system:
- Falls back to a default model (e.g., `gpt-5`)
- Logs a warning about the unmapped model

### Requirement: max_tokens Parameter Handling

The system must accept the required `max_tokens` parameter from Anthropic API.

#### Scenario: max_tokens provided

WHEN a request includes `max_tokens`

THEN the system:
- Accepts the parameter without error
- Does not forward to Responses API (not supported upstream)
- Processes the request normally

### Requirement: Error Response Format

The system must return Anthropic-compatible error responses.

#### Scenario: Invalid request

WHEN the system encounters an error (validation, upstream failure, etc.)

THEN the system returns:
```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "..."
  }
}
```

## MODIFIED Requirements

(None - this is a new capability)

## REMOVED Requirements

(None - this is a new capability)