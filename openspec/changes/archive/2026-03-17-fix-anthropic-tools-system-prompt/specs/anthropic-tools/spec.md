## MODIFIED Requirements

### Requirement: Tool Definition Transformation

The system MUST transform Anthropic tool definitions to Responses API **flat** format with `name` at top level.

#### Scenario: Tool with input_schema transformed to flat format

- **WHEN** a request includes tools with Anthropic `input_schema` format:
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

- **THEN** the system transforms to Responses API **flat** format:
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

- **WHEN** a request includes multiple tool definitions

- **THEN** the system:
- Transforms each tool to flat format with `name` at top level
- Preserves tool order in the transformed array
- Maintains all tool properties (name, description, parameters)

#### Scenario: Tool transformation produces no nested function object

- **WHEN** tools are transformed for Responses API

- **THEN** the output does NOT contain nested `function` object (i.e., NOT `{"type": "function", "function": {"name": "..."}}`)
- **AND** the output has `name` directly accessible as `tools[i].name`