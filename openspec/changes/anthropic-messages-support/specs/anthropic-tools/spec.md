## ADDED Requirements

(This capability has been implemented. Full requirements exist in openspec/specs/anthropic-tools/spec.md)

### Requirement: Tool Definition Transformation

The system must transform Anthropic tool definitions to Responses API format.

#### Scenario: Tool with input_schema

- **WHEN** a request includes tools with Anthropic `input_schema` format

- **THEN** the system transforms to Responses API function definition format with name, description, parameters

### Requirement: Tool Result Content Block Transformation

The system must transform `tool_result` content blocks to `tool` role messages.

#### Scenario: User message with tool_result

- **WHEN** a user message includes a `tool_result` content block with tool_use_id and content

- **THEN** the system transforms to Responses API `tool` role message with tool_call_id and content