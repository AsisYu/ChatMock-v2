## 1. Tool Transformation Fix

- [x] 1.1 Import `convert_tools_chat_to_responses` in `chatmock/transform_anthropic.py`
- [x] 1.2 Modify `transform_anthropic_tools()` to wrap output through `convert_tools_chat_to_responses()`
- [x] 1.3 Verify output format has `name` at top level, not nested under `function`

## 2. System Prompt Extraction Fix

- [x] 2.1 Modify `extract_system_prompt()` to handle list-type `system` parameter
- [x] 2.2 Extract text from content blocks with type "text"
- [x] 2.3 Join multiple text blocks with double newlines
- [x] 2.4 Handle edge cases: empty arrays, non-text blocks, mixed content

## 3. Testing

- [x] 3.1 Add unit test for tool transformation to flat format
- [x] 3.2 Add unit test for system prompt as string
- [x] 3.3 Add unit test for system prompt as array of text blocks
- [x] 3.4 Add unit test for system prompt with mixed content types
- [x] 3.5 Run existing test suite to verify no regressions