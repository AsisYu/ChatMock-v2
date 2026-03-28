# Migration Guide: v1 to v2 Auth Format

This guide explains how to migrate from the single-account (v1) format to the multi-account pool (v2) format.

## Overview

ChatMock v2 introduces a multi-account pool system that allows you to:

- Store multiple ChatGPT accounts
- Automatically switch accounts when rate limits are hit
- Manage accounts via CLI and API

The migration from v1 to v2 is **automatic** and **backward compatible**.

## What Changes

### v1 Format (Single Account)

```json
{
  "tokens": {
    "id_token": "...",
    "access_token": "...",
    "refresh_token": "...",
    "account_id": "..."
  },
  "last_refresh": "2024-01-15T10:30:00Z"
}
```

### v2 Format (Multi-Account Pool)

```json
{
  "version": "2.0",
  "migration_state": "complete",
  "checksum": "sha256:...",
  "accounts": [
    {
      "id": "account-uuid",
      "alias": "user@example.com",
      "tokens": {
        "id_token": "...",
        "access_token": "...",
        "refresh_token": "...",
        "account_id": "..."
      },
      "status": "active",
      "priority": 5,
      "usage": {...},
      "diagnostics": {...}
    }
  ],
  "config": {
    "cooldown_threshold": 95.0,
    "default_cooldown_seconds": 3600
  }
}
```

## Automatic Migration

When you run `chatmock login` or `chatmock serve`, ChatMock automatically:

1. Detects v1 format (no `version` field)
2. Creates a backup at `~/.chatgpt-local/auth.json.v1.bak`
3. Converts to v2 format with your existing account
4. Saves the new format

You don't need to do anything manually.

## Manual Migration

If you want to trigger migration explicitly:

```bash
# Just run any chatmock command
chatmock info

# Or start the server
chatmock serve
```

## Rollback

If you need to rollback to v1 format:

### Automatic Rollback

```bash
# Restore from backup
cp ~/.chatgpt-local/auth.json.v1.bak ~/.chatgpt-local/auth.json
```

### Fresh Login

```bash
# Remove v2 file and re-login
rm ~/.chatgpt-local/auth.json
chatmock login
```

## Troubleshooting

### "Checksum verification failed"

This means the auth file was corrupted. To fix:

```bash
# Restore from backup
cp ~/.chatgpt-local/auth.json.v1.bak ~/.chatgpt-local/auth.json

# Or start fresh
rm ~/.chatgpt-local/auth.json
chatmock login
```

### "Migration failed"

Check the backup file exists:

```bash
ls -la ~/.chatgpt-local/auth.json.v1.bak
```

If it exists, restore it manually. If not, you'll need to re-login.

### "Account not found after migration"

The migration extracts your account ID from the JWT token. If this fails:

```bash
# Check the auth file
cat ~/.chatgpt-local/auth.json | python3 -m json.tool

# Re-login if needed
chatmock login
```

### Multiple processes overwriting auth.json

If you run CLI and server simultaneously, changes may conflict. The v2 format includes:

- **Atomic writes**: Changes are written to a temp file first
- **mtime tracking**: Detects external modifications
- **Merge strategy**: Combines local and external changes

If conflicts still occur:

```bash
# Force reload from disk (server)
curl -X POST http://localhost:8000/v1/pool/reload
```

## What Happens to Existing Tokens

Your tokens are **preserved** during migration:

- `access_token`, `id_token`, `refresh_token` are copied verbatim
- Token refresh continues to work
- No re-authentication required

## After Migration

Once migrated, you can:

```bash
# View your account
chatmock account list

# Add more accounts
chatmock login

# Check pool status
chatmock pool status
```

## FAQ

### Will my existing setup break?

No. The migration is backward compatible. Single-account usage continues to work seamlessly.

### Do I need to re-login?

No. Your existing tokens are preserved and continue to work.

### Can I stay on v1?

Technically yes, but v2 is recommended. If you delete `~/.chatgpt-local/auth.json`, you'll get v1 behavior until the next login.

### How do I know if I'm on v2?

```bash
cat ~/.chatgpt-local/auth.json | grep '"version"'
```

If you see `"version": "2.0"`, you're on v2.

### What if I have issues?

1. Check the backup: `ls ~/.chatgpt-local/auth.json.v1.bak`
2. Try restoring from backup
3. If all else fails, re-login: `chatmock login`