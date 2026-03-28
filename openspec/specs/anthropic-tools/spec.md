# anthropic-tools Specification

## Purpose
Tool transformation for Anthropic Claude API compatibility - converts Anthropic tool format to Responses API flat format.
## Requirements
### Requirement: Tool Definition Transformation

The system MUST transform Anthropic tool definitions to Responses API **flat** format with `name` at top level.

#### Scenario: Tool with input_schema transformed to flat format

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

THEN the system transforms to Responses API **flat** format:
```json
{
  "type": "function",
  "name": "get_weather",
  "description": "Get weather info",
  "strict": false,
  "parameters": {
    "type": "object",
    "properties": {"location": {"type": "string"}}
  }
}
```

#### Scenario: Multiple tools preserve order and structure

WHEN a request includes multiple tool definitions

THEN the system:
- Transforms each tool to flat format with `name` at top level
- Preserves tool order in the transformed array
- Maintains all tool properties (name, description, parameters)

#### Scenario: Tool transformation produces no nested function object

WHEN tools are transformed for Responses API

THEN the output does NOT contain nested `function` object (i.e., NOT `{"type": "function", "function": {"name": "..."}}`)
AND the output has `name` directly accessible as `tools[i].name`

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

