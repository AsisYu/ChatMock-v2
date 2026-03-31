<div align="center">

# ChatMock

**Allows Codex to work in your favourite chat apps and coding tools.**

[中文](README.md) | [English](README_EN.md)

[![PyPI](https://img.shields.io/pypi/v/chatmock?color=blue&label=pypi)](https://pypi.org/project/chatmock/)
[![Python](https://img.shields.io/pypi/pyversions/chatmock)](https://pypi.org/project/chatmock/)
[![License](https://img.shields.io/github/license/RayBytes/ChatMock)](LICENSE)
[![Stars](https://img.shields.io/github/stars/RayBytes/ChatMock?style=flat)](https://github.com/RayBytes/ChatMock/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/commits/main)
[![Issues](https://img.shields.io/github/issues/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/issues)

<br>


</div>

<br>

## Install

#### Homebrew
```bash
brew tap RayBytes/chatmock
brew install chatmock
```

#### pipx / pip
```bash
pipx install chatmock
```

#### GUI
Download from [releases](https://github.com/RayBytes/ChatMock/releases) (macOS & Windows)

#### Docker
See [DOCKER.md](DOCKER.md)

<br>

## Getting Started

```bash
# 1. Sign in with your ChatGPT account
chatmock login

# 2. Start the server
chatmock serve
```

The server runs at `http://127.0.0.1:8000` by default. Use `http://127.0.0.1:8000/v1` as your base URL for OpenAI-compatible apps.

<br>

## Multi-Account Pool

ChatMock supports multiple ChatGPT accounts with automatic switching when rate limits are hit.

### Adding Accounts

```bash
# Add first account
chatmock login

# Add additional accounts (run login again)
chatmock login
```

Each login prompts you to confirm adding the account to the pool.

### Managing Accounts

```bash
# List all accounts
chatmock account list

# Show account details
chatmock account show <account-id>

# Set account priority (1=highest, 10=lowest)
chatmock account priority <account-id> 1

# Rename an account
chatmock account rename <account-id> "work-account"

# Reset an account from error state to active
chatmock account reset <account-id>

# Remove an account
chatmock account remove <account-id>
```

### Account Status

| Status | Icon | Description |
|--------|------|-------------|
| `active` | ✅ | Available for use |
| `ready` | ✅ | Cooldown finished, ready to use |
| `cooldown` | ⏳ | Rate limit cooldown |
| `error` | ❌ | Auth failed or consecutive failures, requires manual reset |

**Recovering error accounts**:
```bash
# Check which accounts have errors
chatmock pool status

# Reset a single account
chatmock account reset <account-id>
```

### Pool Status

```bash
# View pool status
chatmock pool status

# View as JSON
chatmock pool status --json
```

### API Endpoints

Pool management API (localhost only by default):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/pool/status` | GET | Get pool status |
| `/v1/pool/accounts` | GET | List all accounts |
| `/v1/pool/accounts/<id>` | GET | Get account details |
| `/v1/pool/accounts/<id>` | DELETE | Remove account |
| `/v1/pool/accounts/<id>` | PATCH | Update alias/priority |
| `/v1/pool/reload` | POST | Reload pool from disk |
| `/v1/pool/config` | GET/PATCH | View/update config |

### Security for Reverse Proxy

If running behind nginx/traefik, set an API token:

```bash
export CHATMOCK_POOL_API_TOKEN="your-secret-token"
```

Then include the token in requests:
```bash
curl -H "Authorization: Bearer your-secret-token" http://your-server/v1/pool/status
```

### How It Works

- **Automatic switching**: When an account hits rate limits, it enters cooldown and the next available account is used
- **Weighted selection**: Accounts with higher priority and more remaining quota are preferred
- **Cooldown recovery**: Accounts automatically become available again after rate limit reset
- **Thread-safe**: Safe for concurrent requests

<br>

## Usage

<details open>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="anything"  # not checked
)

response = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "hello"}]
)
print(response.choices[0].message.content)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

</details>

<br>

## Supported Models

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.2`
- `gpt-5.1`
- `gpt-5`
- `gpt-5.3-codex`
- `gpt-5.3-codex-spark`
- `gpt-5.2-codex`
- `gpt-5-codex`
- `gpt-5.1-codex`
- `gpt-5.1-codex-max`
- `gpt-5.1-codex-mini`
- `codex-mini`

<br>

## Features

- Tool / function calling
- Vision / image input
- Thinking summaries (via think tags)
- Configurable thinking effort
- Fast mode for supported models
- Web search tool
- OpenAI-compatible `/v1/responses` (HTTP + WebSocket)
- Ollama-compatible endpoints
- Reasoning effort exposed as separate models (optional)
- Optional API token authentication

<br>

## API Authentication

By default, ChatMock accepts requests without authentication (suitable for localhost development).

To enable authentication, set an API token:

```bash
# Via environment variable
export CHATMOCK_API_TOKEN="your-secret-token"
chatmock serve

# Or via CLI flag
chatmock serve --api-token "your-secret-token"
```

When enabled, clients must include the token:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your-secret-token"  # Must match the configured token
)
```

```bash
curl -H "Authorization: Bearer your-secret-token" \
  http://127.0.0.1:8000/v1/chat/completions \
  -d '{"model": "gpt-5.4", "messages": [{"role": "user", "content": "hello"}]}'
```

<br>

## Configuration

All flags go after `chatmock serve`. These can also be set as environment variables.

| Flag | Env var | Options | Default | Description |
|------|---------|---------|---------|-------------|
| `--reasoning-effort` | `CHATGPT_LOCAL_REASONING_EFFORT` | none, minimal, low, medium, high, xhigh | medium | How hard the model thinks |
| `--reasoning-summary` | `CHATGPT_LOCAL_REASONING_SUMMARY` | auto, concise, detailed, none | auto | Thinking summary verbosity |
| `--reasoning-compat` | `CHATGPT_LOCAL_REASONING_COMPAT` | legacy, o3, think-tags | think-tags | How reasoning is returned to the client |
| `--fast-mode` | `CHATGPT_LOCAL_FAST_MODE` | true/false | false | Priority processing for supported models |
| `--enable-web-search` | `CHATGPT_LOCAL_ENABLE_WEB_SEARCH` | true/false | false | Allow the model to search the web |
| `--expose-reasoning-models` | `CHATGPT_LOCAL_EXPOSE_REASONING_MODELS` | true/false | false | List each reasoning level as its own model |
| `--api-token` | `CHATMOCK_API_TOKEN` | string | none | API token for authentication |

<details>
<summary><b>Web search in a request</b></summary>

```json
{
  "model": "gpt-5.4",
  "messages": [{"role": "user", "content": "latest news on ..."}],
  "responses_tools": [{"type": "web_search"}],
  "responses_tool_choice": "auto"
}
```

</details>

<details>
<summary><b>Fast mode in a request</b></summary>

```json
{
  "model": "gpt-5.4",
  "input": "summarize this",
  "fast_mode": true
}
```

</details>

<br>

## Notes

Use responsibly and at your own risk. This project is not affiliated with OpenAI.

<br>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=RayBytes/ChatMock&type=Timeline)](https://www.star-history.com/#RayBytes/ChatMock&Timeline)
