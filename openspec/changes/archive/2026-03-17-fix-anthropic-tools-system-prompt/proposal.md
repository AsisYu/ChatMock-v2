## Why

The Anthropic `/v1/messages` endpoint returns 400 errors when clients send requests with tools or array-format system prompts. This breaks compatibility with Claude Code and other Anthropic SDK clients that use these features.

## What Changes

- Fix `transform_anthropic_tools()` to output Responses API flat format instead of OpenAI Chat nested format
- Fix `extract_system_prompt()` to properly extract text from array-format system prompts
- Both fixes restore full Anthropic API compatibility without breaking existing functionality

## Capabilities

### New Capabilities

(None - this is a bug fix, not a new feature)

### Modified Capabilities

- `anthropic-tools`: Tool definitions must be transformed to Responses API flat format with `name` at top level, not nested under `function`
- `anthropic-messages`: System prompt extraction must handle both string and array content block formats

## Impact

**Modified Files:**
- `chatmock/transform_anthropic.py` - Fix tool transformation output format and system prompt extraction

**API Behavior:**
- `/v1/messages` with `tools` parameter: Now returns 200 instead of 400
- `/v1/messages` with array-format `system` parameter: Now correctly extracts text content

**No Breaking Changes:**
- String-format system prompts continue to work as before
- Tool-free requests continue to work as before