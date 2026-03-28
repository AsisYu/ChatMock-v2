# Multi-Account Guide

This guide covers the multi-account pool feature in ChatMock, including setup, best practices, and advanced usage.

## Overview

The multi-account pool allows you to:

- Store and manage multiple ChatGPT Plus/Pro accounts
- Automatically switch accounts when rate limits are hit
- Configure priority and cooldown settings
- Monitor account usage and health

## Quick Start

### Adding Accounts

```bash
# Add your first account
chatmock login
# Follow the OAuth flow in your browser
# Confirm adding to pool when prompted

# Add additional accounts (repeat as needed)
chatmock login
```

### Viewing Accounts

```bash
# List all accounts
chatmock account list

# Example output:
# ID              Alias           Status    Priority  Usage%
# acc_abc123      work@email.com  active    1         45%
# acc_def456      personal@email  active    5         12%
```

### Checking Pool Status

```bash
chatmock pool status

# Example output:
# Pool Status
# ─────────────────────────────────────
# Total accounts:     2
# Active accounts:    2
# Cooldown accounts:  0
# Error accounts:     0
```

## Account Management

### Setting Priority

Priority determines account selection order. Lower number = higher priority.

```bash
# Set highest priority (1)
chatmock account priority acc_abc123 1

# Set lower priority (10)
chatmock account priority acc_def456 10
```

When selecting an account, the pool considers:
1. Account priority (lower = preferred)
2. Remaining quota (more = preferred)
3. Account status (active vs cooldown vs error)

### Renaming Accounts

```bash
# Set a friendly alias
chatmock account rename acc_abc123 "work-account"
chatmock account rename acc_def456 "personal"
```

### Removing Accounts

```bash
# Remove with confirmation
chatmock account remove acc_abc123

# Force remove without confirmation
chatmock account remove acc_abc123 --force
```

## Account Status

### Status Types

| Status | Description |
|--------|-------------|
| `active` | Available for use |
| `ready` | Recovered from cooldown, ready to use |
| `cooldown` | Rate limit reached, waiting for reset |
| `error` | Authentication failed or consecutive errors |

### Cooldown Behavior

When an account hits the rate limit threshold (default: 95%):

1. Account enters `cooldown` status
2. Pool selects next available account
3. After reset time, account becomes `ready` then `active`

### Error Recovery

Accounts enter `error` status when:

- Authentication fails (401 response)
- Too many consecutive failures (default: 3)

To recover an error account:

```bash
# Re-authenticate
chatmock login
# Select the same account, it will be refreshed
```

## Pool Configuration

### Viewing Configuration

```bash
chatmock pool config

# Or via API
curl http://localhost:8000/v1/pool/config
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `cooldown_threshold` | 95.0 | Usage % that triggers cooldown |
| `default_cooldown_seconds` | 3600 | Fallback cooldown duration |
| `max_pool_size` | None | Maximum accounts (None = unlimited) |
| `health_cache_ttl_seconds` | 60 | Health check cache duration |
| `max_consecutive_failures` | 3 | Failures before error status |

### Updating Configuration

```bash
# Via API
curl -X PATCH http://localhost:8000/v1/pool/config \
  -H "Content-Type: application/json" \
  -d '{"cooldown_threshold": 90.0}'
```

## Weighted Selection

The pool uses weighted selection to choose accounts:

```
weight = (1 / priority) × remaining_quota_percent
```

Example with 3 accounts:

| Account | Priority | Usage | Weight |
|---------|----------|-------|--------|
| work | 1 | 50% | 0.5 × 0.5 = 0.25 |
| personal | 5 | 20% | 0.2 × 0.8 = 0.16 |
| backup | 10 | 10% | 0.1 × 0.9 = 0.09 |

The account with the highest weight is most likely to be selected.

## API Reference

### Get Pool Status

```bash
GET /v1/pool/status
```

Response:
```json
{
  "success": true,
  "total_accounts": 2,
  "active_accounts": 2,
  "cooldown_accounts": 0,
  "error_accounts": 0,
  "accounts": [...]
}
```

### List Accounts

```bash
GET /v1/pool/accounts
```

### Get Account Details

```bash
GET /v1/pool/accounts/<account-id>
```

### Update Account

```bash
PATCH /v1/pool/accounts/<account-id>
Content-Type: application/json

{
  "alias": "new-alias",
  "priority": 2
}
```

### Remove Account

```bash
DELETE /v1/pool/accounts/<account-id>
```

### Reload Pool from Disk

```bash
POST /v1/pool/reload
```

Use this after CLI modifications to sync the server's in-memory state.

### Get/Update Configuration

```bash
GET /v1/pool/config
PATCH /v1/pool/config
```

## Security

### Localhost Access (Default)

Pool endpoints are only accessible from localhost by default. This is secure for local development.

### Reverse Proxy Setup

If running behind nginx/traefik, set an API token:

```bash
# Set environment variable
export CHATMOCK_POOL_API_TOKEN="your-secret-token"
```

Then include in requests:

```bash
curl -H "Authorization: Bearer your-secret-token" \
  http://your-server/v1/pool/status
```

**Important**: Without `CHATMOCK_POOL_API_TOKEN`, pool endpoints are blocked when accessed through a reverse proxy.

### Token Storage

Account tokens are stored in `~/.chatgpt-local/auth.json` with permissions `0600` (owner read/write only).

## Best Practices

### 1. Use Priority for Primary/Backup

```bash
# Primary account
chatmock account priority primary-id 1

# Backup accounts
chatmock account priority backup-id 5
chatmock account priority emergency-id 10
```

### 2. Monitor Usage

```bash
# Check usage regularly
chatmock account list

# Set lower threshold for critical workloads
curl -X PATCH http://localhost:8000/v1/pool/config \
  -H "Content-Type: application/json" \
  -d '{"cooldown_threshold": 80.0}'
```

### 3. Name Accounts Meaningfully

```bash
# Use descriptive aliases
chatmock account rename acc_123 "work-plus"
chatmock account rename acc_456 "personal-pro"
chatmock account rename acc_789 "team-shared"
```

### 4. CLI + Server Coordination

When using CLI while server is running:

```bash
# After CLI changes, reload server state
curl -X POST http://localhost:8000/v1/pool/reload
```

### 5. Health Monitoring

Set up monitoring:

```bash
# Simple health check script
#!/bin/bash
STATUS=$(curl -s http://localhost:8000/v1/pool/status)
ACTIVE=$(echo $STATUS | jq '.active_accounts')
if [ "$ACTIVE" -eq 0 ]; then
  echo "WARNING: No active accounts!"
  exit 1
fi
```

## Troubleshooting

### "No available account"

All accounts are in cooldown or error:

```bash
# Check status
chatmock pool status

# Wait for cooldown to expire
# Or add more accounts
chatmock login
```

### Accounts Not Switching

Check rate limit headers are being captured:

```bash
# Verbose logging
chatmock serve --verbose
```

Look for `x-codex-primary-used-percent` headers in logs.

### Token Refresh Issues

If tokens expire without refresh:

```bash
# Re-login to refresh tokens
chatmock login
# Select the existing account
```

### Race Conditions (CLI vs Server)

If CLI changes are lost:

```bash
# Always reload after CLI changes
curl -X POST http://localhost:8000/v1/pool/reload
```

## FAQ

### How many accounts can I add?

Unlimited by default. Set `max_pool_size` to limit:

```bash
curl -X PATCH http://localhost:8000/v1/pool/config \
  -H "Content-Type: application/json" \
  -d '{"max_pool_size": 5}'
```

### Do I need multiple ChatGPT subscriptions?

Yes, each account needs its own ChatGPT Plus/Pro subscription.

### Can I share the pool across machines?

The auth file is local. To share:

1. Copy `~/.chatgpt-local/auth.json` to another machine
2. Set appropriate permissions: `chmod 600 auth.json`
3. Restart the server

### What happens if all accounts hit rate limits?

The pool returns `NoAvailableAccountError`. Requests fail until an account exits cooldown.

### Can I use different models per account?

No, model selection is independent of accounts. The pool manages authentication, not model capabilities.