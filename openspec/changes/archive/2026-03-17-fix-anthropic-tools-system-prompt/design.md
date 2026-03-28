## Context

ChatMock's Anthropic `/v1/messages` endpoint has two bugs causing 400 errors:

1. **Tool format mismatch**: `transform_anthropic_tools()` outputs OpenAI Chat nested format (`tools[0].function.name`) but Responses API expects flat format (`tools[0].name`)

2. **System prompt array handling**: Claude Code and other clients send `system` as an array of content blocks. Current code does `str(system)` which produces invalid string representation instead of extracting text.

**Current Implementation:**
- `transform_anthropic_tools()` at `chatmock/transform_anthropic.py:338-401`
- `extract_system_prompt()` at `chatmock/transform_anthropic.py:18-40`
- OpenAI route uses `convert_tools_chat_to_responses()` at `chatmock/utils.py:193-219` for correct format

## Goals / Non-Goals

**Goals:**
- Fix tool transformation to output Responses API flat format
- Fix system prompt extraction to handle array content blocks
- Restore full Anthropic API compatibility

**Non-Goals:**
- Adding new features beyond bug fixes
- Changing behavior for working cases (string system prompts)
- Modifying other endpoints

## Decisions

### Decision 1: Reuse `convert_tools_chat_to_responses()` for tool format conversion

**Rationale:** This function already exists and produces the correct Responses API format. The OpenAI route uses it successfully.

**Implementation:** After `transform_anthropic_tools()` produces OpenAI Chat format, pass the result through `convert_tools_chat_to_responses()` to get flat format.

**Alternative considered:** Modify `transform_anthropic_tools()` directly to output flat format. Rejected because it would create code duplication with `convert_tools_chat_to_responses()`.

### Decision 2: Extract text from array-format system prompts

**Rationale:** Anthropic API spec allows `system` to be either a string or an array of content blocks. We must handle both.

**Implementation:**
```python
if isinstance(system, list):
    # Extract text from content blocks
    text_parts = []
    for block in system:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str):
                text_parts.append(text)
    system = "\n\n".join(text_parts) if text_parts else None
elif system is not None and not isinstance(system, str):
    system = str(system) if system else None
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Tool format conversion adds overhead | Negligible - both functions are O(n) where n is number of tools |
| System prompt array may have non-text blocks | Only extract text blocks, ignore others (images, etc.) |
| Breaking change for edge cases | Test with both string and array formats before deploying |