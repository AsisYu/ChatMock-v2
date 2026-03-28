# Anthropic Tools Capability

## ADDED Requirements

### Requirement: Tool Definition Transformation

The system must transform Anthropic tool definitions to Responses API format.

#### Scenario: Tool with input_schema

WHEN a request includes tools with Anthropic `input_schema` format:
```json
{
  "name": "get_weather",
  "description": "Get weather info",
  "input_schema": {
    "type": "object",
    "properties": {"location": {"type": "string"}}
  }
}
```

THEN the system transforms to Responses API format:
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get weather info",
    "parameters": {
      "type": "object",
      "properties": {"location": {"type": "string"}}
    }
  }
}
```

#### Scenario: Multiple tools

WHEN a request includes multiple tool definitions

THEN the system:
- Transforms each tool individually
- Preserves tool order in the transformed array
- Maintains all tool properties (name, description, parameters)

### Requirement: Tool Use Content Block Handling

The system must handle assistant messages containing `tool_use` content blocks.

#### Scenario: Assistant message with tool_use

WHEN an assistant message includes a `tool_use` content block:
```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Let me check that."},
    {"type": "tool_use", "id": "toolu_01", "name": "get_weather", "input": {"location": "NYC"}}
  ]
}
```

THEN the system transforms to Responses API format:
- Text blocks become string content
- Tool use blocks become tool calls with `tool_call_id`, `function.name`, `function.arguments`

### Requirement: Tool Result Content Block Transformation

The system must transform `tool_result` content blocks to `tool` role messages.

#### Scenario: User message with tool_result

WHEN a user message includes a `tool_result` content block:
```json
{
  "role": "user",
  "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "Sunny, 72F"}
  ]
}
```

THEN the system transforms to Responses API format:
```json
{
  "role": "tool",
  "tool_call_id": "toolu_01",
  "content": "Sunny, 72F"
}
```

#### Scenario: Tool result with error

WHEN a `tool_result` includes `is_error: true`

THEN the system:
- Sets the `content` field with the error message
- Preserves the error status in the transformed message

#### Scenario: Tool result with multiple content items

WHEN a `tool_result` has array content

THEN the system:
- Concatenates or structures the content appropriately
- Handles text and image content within the result

### Requirement: Tool Type Constraint

The system must enforce the existing `web_search` tool type constraint for Anthropic tools.

#### Scenario: Web search tool

WHEN a tool definition matches supported types (web_search related)

THEN the system:
- Processes the tool normally
- Forwards to Responses API

#### Scenario: Unsupported tool type

WHEN a tool definition uses an unsupported type (not web_search)

THEN the system:
- Rejects the request with an appropriate error
- Returns error type `invalid_request_error` with message explaining the constraint

### Requirement: Tool Choice Mapping

The system must map Anthropic `tool_choice` values to Responses API format.

#### Scenario: tool_choice auto

WHEN `tool_choice` is `"auto"` or not specified

THEN the system passes `"auto"` to Responses API

#### Scenario: tool_choice any

WHEN `tool_choice` is `"any"`

THEN the system maps to appropriate Responses API equivalent

#### Scenario: tool_choice specific tool

WHEN `tool_choice` is `{"type": "tool", "name": "get_weather"}`

THEN the system transforms to Responses API `tool_choice` format

## MODIFIED Requirements

(None - this is a new capability)

## REMOVED Requirements

(None - this is a new capability)