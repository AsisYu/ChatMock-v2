## MODIFIED Requirements

### Requirement: System Prompt Extraction

The system MUST handle both string and array content block formats for the `system` parameter.

#### Scenario: System prompt as string

- **WHEN** the `system` parameter is a string: `"You are a helpful assistant."`

- **THEN** the system uses the string directly as instructions

#### Scenario: System prompt as array of content blocks

- **WHEN** the `system` parameter is an array of content blocks:
```json
[
  {"type": "text", "text": "You are a helpful assistant."},
  {"type": "text", "text": "Be concise in your responses."}
]
```

- **THEN** the system extracts and concatenates text from all text blocks
- **AND** joins them with double newlines: `"You are a helpful assistant.\n\nBe concise in your responses."`

#### Scenario: System prompt array with mixed content types

- **WHEN** the `system` parameter contains non-text blocks (e.g., images)

- **THEN** the system extracts only text blocks
- **AND** ignores non-text blocks

#### Scenario: System prompt array with no text blocks

- **WHEN** the `system` parameter is an empty array or contains no text blocks

- **THEN** the system returns `None` for instructions