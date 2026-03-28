# Proposal: Multi-Account Pool Support

## Summary

Add support for managing multiple ChatGPT accounts in a single ChatMock instance, enabling automatic account switching when rate limits are reached, with a cooldown mechanism and pool status monitoring.

## Motivation

Currently, ChatMock supports only a single ChatGPT account. When the account's rate limit is exhausted, users must manually log in with a different account. This is inconvenient for users with multiple ChatGPT Plus/Pro accounts who want seamless operation without manual intervention.

## Goals

1. **Multi-account login**: Support logging in multiple accounts and persisting all sessions
2. **Automatic switching**: Detect when current account is unavailable and switch to next available account
3. **Cooldown mechanism**: Exhausted accounts enter cooldown period and become available again after reset time
4. **Pool status API**: Expose an endpoint to check the status of all accounts in the pool

## Non-Goals

- Parallel request distribution across accounts (single request uses single account)
- Automatic account discovery (user must explicitly add accounts)
- Cross-session state synchronization (pool state is local to the instance)

## User Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Account identifier | `account_id` from JWT | Unique and stable identifier from ChatGPT |
| Switch strategy | Weighted Round-Robin (by remaining quota) | Prefer accounts with more available quota, reduce hitting newly recovered accounts |
| Cooldown trigger | Rate Limit >= 95% | Near-exhaustion triggers preventive cooldown |
| Cooldown duration | Rate Limit Reset time (with fallback) | Use upstream-provided reset time, or default 1 hour if unavailable |
| Login flow | Interactive confirmation | User confirms before adding to pool |
| Storage structure | Single file extension (with backup) | Maintain backward compatibility, atomic writes with backup |
| Status detection | Pre-request check + health cache | Check availability before each request, cache health state |
| Pool size | Unlimited (configurable) | No artificial restriction, but allow config limit |
| Account removal | CLI + API | Both methods supported |

## Constraints

### Hard Constraints (from codebase analysis)

| ID | Constraint | Source |
|----|------------|--------|
| HC-1 | `write_auth_file()` overwrites existing auth, needs extension | `oauth.py:196` |
| HC-2 | `get_effective_chatgpt_auth()` returns single account directly | `utils.py:370-374` |
| HC-3 | `store_rate_limit_snapshot()` stores single account limits | `limits.py:98-127` |
| HC-4 | `start_upstream_request()` calls single-account auth getter | `upstream.py:39` |
| HC-5 | `cmd_login()` is single-flow, needs interactive confirmation | `cli.py:189-259` |
| HC-6 | OAuth callback port 1455 is fixed, no parallel login support | `oauth.py:21` |

### Soft Constraints (user decisions)

| ID | Constraint |
|----|------------|
| SC-1 | Use `chatgpt_account_id` from JWT as unique identifier |
| SC-2 | Weighted Round-Robin rotation (prefer accounts with more remaining quota) |
| SC-3 | Cooldown triggered at 95% rate limit usage |
| SC-4 | Use `x-codex-*-reset-after-seconds` for cooldown, fallback to 1 hour if missing |
| SC-5 | Interactive confirmation when adding new accounts |
| SC-6 | Extend existing `auth.json` with pool structure, atomic writes with backup |
| SC-7 | Check account status before each request with health state cache |
| SC-8 | No hard limit on pool size, but allow configuration |
| SC-9 | Support both CLI and API for account removal |

## Proposed Data Structure

```json
{
  "version": "2.0",
  "migration_state": "complete",
  "checksum": "sha256:abc123...",
  "accounts": [
    {
      "id": "account_abc123",
      "alias": "work-account",
      "priority": 1,
      "tokens": {
        "id_token": "...",
        "access_token": "...",
        "refresh_token": "...",
        "account_id": "chatgpt_xxx"
      },
      "status": "active",
      "usage": {
        "primary": {
          "used_percent": 45.0,
          "window_minutes": 300,
          "resets_in_seconds": 7200,
          "captured_at": "2025-03-28T12:00:00Z"
        },
        "secondary": {
          "used_percent": 20.0,
          "window_minutes": 10080,
          "resets_in_seconds": 86400,
          "captured_at": "2025-03-28T12:00:00Z"
        }
      },
      "diagnostics": {
        "error_reason": null,
        "last_error_at": null,
        "last_refresh_at": "2025-03-28T11:30:00Z",
        "last_successful_request_at": "2025-03-28T12:00:00Z",
        "consecutive_failures": 0
      },
      "cooldown_until": null,
      "health_cache": {
        "is_healthy": true,
        "checked_at": "2025-03-28T12:00:00Z",
        "cache_ttl_seconds": 60
      },
      "last_used": "2025-03-28T12:00:00Z",
      "created_at": "2025-03-20T10:00:00Z"
    }
  ],
  "current_index": 0,
  "config": {
    "cooldown_threshold": 95.0,
    "default_cooldown_seconds": 3600,
    "max_pool_size": null,
    "health_cache_ttl_seconds": 60,
    "max_consecutive_failures": 3
  }
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `migration_state` | string | One of: `none`, `in_progress`, `complete`, `failed` |
| `checksum` | string | SHA256 of accounts array for integrity verification |
| `priority` | integer | Lower number = higher priority (1 is highest) |
| `usage.secondary` | object | Weekly rate limit window (if provided by upstream) |
| `diagnostics.error_reason` | string | Last error message (null if no error) |
| `diagnostics.last_error_at` | string | ISO8601 timestamp of last error |
| `diagnostics.last_refresh_at` | string | When tokens were last refreshed |
| `diagnostics.consecutive_failures` | integer | Count of consecutive request failures |
| `health_cache` | object | Cached health check result to avoid repeated checks |

## Account States

```
                              ┌──────────────────────────────────┐
                              │                                  │
                              ▼                                  │
┌─────────┐   rate_limit >= 95%   ┌──────────┐   reset elapsed   │
│  ACTIVE │ ─────────────────────▶│ COOLDOWN │ ──────────────────┤
└─────────┘                        └──────────┘                   │
     ▲                                  │                         │
     │                                  │ reset_time elapsed      │
     │                                  ▼                         │
     │     manual fix            ┌──────────┐                    │
     │  (remove/re-login)        │  READY   │◀───────────────────┘
     │                           └──────────┘
     │                                 │
     │   auth failure / 429            │ next request
     │   consecutive_failures >= 3     │
     ▼                                 ▼
┌─────────┐                        ┌─────────┐
│  ERROR  │◀───────────────────────│  ACTIVE │
└─────────┘   unexpected 429       └─────────┘
              token revoked
              account banned

State Descriptions:
- ACTIVE: Currently in use, healthy
- COOLDOWN: Rate limit reached, waiting for reset
- READY: Cooldown complete, available for use
- ERROR: Requires manual intervention
```

## Concurrent Access Design

### Thread Safety Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Request Thread Flow                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Flask Request Thread                                          │
│   ┌─────────────┐                                              │
│   │  Request    │                                              │
│   │  Handler    │                                              │
│   └──────┬──────┘                                              │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────────────────────────────────┐                  │
│   │         pool_manager.get_account()       │                  │
│   │  ┌─────────────────────────────────────┐│                  │
│   │  │ 1. Acquire RLock (read)             ││                  │
│   │  │ 2. Check health cache (if valid)    ││                  │
│   │  │ 3. If cache miss, check status      ││                  │
│   │  │ 4. Select best account (weighted)   ││                  │
│   │  │ 5. Mark as in-use (atomic)          ││                  │
│   │  │ 6. Return account tokens            ││                  │
│   │  └─────────────────────────────────────┘│                  │
│   └──────────────────┬──────────────────────┘                  │
│                      │                                          │
│                      ▼                                          │
│   ┌─────────────────────────────────────────┐                  │
│   │      upstream.request(account)           │                  │
│   │      (actual API call)                   │                  │
│   └──────────────────┬──────────────────────┘                  │
│                      │                                          │
│          ┌───────────┴───────────┐                             │
│          ▼                       ▼                             │
│   ┌─────────────┐         ┌─────────────┐                      │
│   │   Success   │         │   Failure   │                      │
│   │   200 OK    │         │   429/401   │                      │
│   └──────┬──────┘         └──────┬──────┘                      │
│          │                       │                              │
│          ▼                       ▼                              │
│   ┌─────────────────┐    ┌─────────────────┐                   │
│   │ pool_manager    │    │ pool_manager    │                   │
│   │ .record_success │    │ .record_failure │                   │
│   │ (update usage)  │    │ (handle cooldown│                   │
│   │                 │    │  /error state)  │                   │
│   └─────────────────┘    └─────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Account Selection Algorithm (Weighted Round-Robin)

```python
def select_account(pool: AccountPool) -> Account:
    """
    Select the best available account using weighted round-robin.

    Weights are calculated based on:
    1. Priority (lower = higher weight)
    2. Remaining quota (100% - used_percent)
    3. Health cache status
    """
    with pool.lock:
        available = [
            acc for acc in pool.accounts
            if acc.status in ("active", "ready")
            and acc.health_cache.is_healthy
            and acc.cooldown_until is None
        ]

        if not available:
            raise NoAvailableAccountError()

        # Calculate weights
        weights = []
        for acc in available:
            priority_weight = 1.0 / (acc.priority or 10)
            quota_weight = (100.0 - acc.usage.primary.used_percent) / 100.0
            weight = priority_weight * quota_weight
            weights.append(weight)

        # Weighted random selection
        return weighted_choice(available, weights)
```

### Rollback on Failure

```python
def handle_request_failure(account_id: str, error: Exception):
    """
    Handle request failure with proper state rollback.
    """
    with pool.lock:
        account = pool.get_account_by_id(account_id)

        if isinstance(error, RateLimitError):
            # Enter cooldown
            cooldown_seconds = error.reset_after or pool.config.default_cooldown_seconds
            account.cooldown_until = now() + timedelta(seconds=cooldown_seconds)
            account.status = "cooldown"

        elif isinstance(error, AuthError):
            # Token invalid, mark as error
            account.status = "error"
            account.diagnostics.error_reason = str(error)
            account.diagnostics.last_error_at = now()

        else:
            # Track consecutive failures
            account.diagnostics.consecutive_failures += 1
            if account.diagnostics.consecutive_failures >= pool.config.max_consecutive_failures:
                account.status = "error"
                account.diagnostics.error_reason = f"Consecutive failures: {account.diagnostics.consecutive_failures}"
```

## API Changes

### New Endpoint: `GET /v1/pool/status`

Returns the status of all accounts in the pool:

```json
{
  "total_accounts": 3,
  "active_accounts": 2,
  "cooldown_accounts": 1,
  "error_accounts": 0,
  "current_account": {
    "id": "account_abc123",
    "alias": "work-account",
    "status": "active"
  },
  "accounts": [
    {
      "id": "account_abc123",
      "alias": "work-account",
      "status": "active",
      "priority": 1,
      "usage_percent": 45.0,
      "remaining_percent": 55.0,
      "resets_in": "2h",
      "last_used_at": "2025-03-28T12:00:00Z",
      "last_error": null
    },
    {
      "id": "account_def456",
      "alias": "personal",
      "status": "cooldown",
      "priority": 2,
      "usage_percent": 96.0,
      "remaining_percent": 4.0,
      "cooldown_remaining": "1h 30m",
      "cooldown_until": "2025-03-28T14:30:00Z",
      "last_used_at": "2025-03-28T11:00:00Z",
      "last_error": null
    },
    {
      "id": "account_xyz789",
      "alias": "backup",
      "status": "error",
      "priority": 3,
      "usage_percent": null,
      "last_used_at": "2025-03-27T10:00:00Z",
      "last_error": "Token refresh failed: invalid_grant",
      "last_error_at": "2025-03-27T10:05:00Z"
    }
  ]
}
```

### New Endpoint: `DELETE /v1/pool/accounts/<account_id>`

Remove an account from the pool.

**Response:**
```json
{
  "success": true,
  "message": "Account 'work-account' removed from pool"
}
```

### New Endpoint: `POST /v1/pool/accounts/<account_id>/refresh`

Force refresh an account's token.

**Response:**
```json
{
  "success": true,
  "account_id": "account_abc123",
  "refreshed_at": "2025-03-28T12:05:00Z"
}
```

## CLI Commands

```bash
# Add new account (interactive)
chatmock login
# Prompts:
# - "New account detected: email@example.com (Plus)"
# - "Add to pool? [Y/n]: "
# - "Enter alias for this account [default: account_abc123]: "

# List all accounts with status
chatmock account list
# Output:
# ID              Alias          Status    Usage    Priority
# account_abc123  work-account   active    45%      1
# account_def456  personal       cooldown  96%      2
# account_xyz789  backup         error     -        3

# Show detailed account info
chatmock account show <account_id>

# Remove account
chatmock account remove <account_id>
# Prompts: "Remove account 'work-account'? [y/N]: "

# Set account priority
chatmock account priority <account_id> <1-10>

# Rename account alias
chatmock account rename <account_id> <new_alias>

# Force refresh account token
chatmock account refresh <account_id>

# Show pool status (same as info but pool-focused)
chatmock pool status

# Pool configuration
chatmock pool config --cooldown-threshold 90 --default-cooldown 1800
```

## Implementation Phases

### Phase 0: Migration & Infrastructure (NEW)

**Goal**: Ensure safe upgrade path for existing users

- [ ] Create `auth_backup.py` module for v1→v2 migration
- [ ] Implement backup strategy: `auth.json` → `auth.json.v1.bak`
- [ ] Create migration detection: detect v1 format and auto-migrate
- [ ] Add rollback capability: restore from backup on failure
- [ ] Add `migration_state` and `checksum` fields
- [ ] **Test**: Migration unit tests, rollback tests

**Deliverables**:
- `chatmock/migration.py`
- `chatmock/auth_backup.py`
- Migration tests in `tests/test_migration.py`

### Phase 1: Pool Manager Core

**Goal**: Create the core pool management logic

- [ ] Create `chatmock/pool_manager.py`
  - [ ] `AccountPool` class with thread-safe operations
  - [ ] `Account` dataclass with all fields
  - [ ] Weighted round-robin selector
  - [ ] Health cache management
  - [ ] Cooldown tracker
- [ ] Create `chatmock/pool_config.py` for configuration
- [ ] Extend `auth.json` structure with pool format
- [ ] **Test**: Pool manager unit tests, thread safety tests

**Deliverables**:
- `chatmock/pool_manager.py`
- `chatmock/pool_config.py`
- `tests/test_pool_manager.py`

### Phase 2: Auth Integration

**Goal**: Integrate pool manager with existing auth flow

- [ ] Refactor `utils.py`:
  - [ ] `get_effective_chatgpt_auth()` → `pool_manager.get_account()`
  - [ ] `load_chatgpt_tokens()` → support multi-account
  - [ ] Add per-account rate limit tracking
- [ ] Refactor `upstream.py`:
  - [ ] Call pool manager instead of direct auth getter
  - [ ] Handle request success/failure callbacks
- [ ] Update `limits.py` for per-account storage
- [ ] **Test**: Auth integration tests, rate limit tracking tests

**Deliverables**:
- Updated `chatmock/utils.py`
- Updated `chatmock/upstream.py`
- Updated `chatmock/limits.py`
- `tests/test_pool_auth.py`

### Phase 3: CLI Updates

**Goal**: Add pool management commands to CLI

- [ ] Update `cli.py`:
  - [ ] Add interactive confirmation to `cmd_login()`
  - [ ] Add `chatmock account list` command
  - [ ] Add `chatmock account show` command
  - [ ] Add `chatmock account remove` command
  - [ ] Add `chatmock account priority` command
  - [ ] Add `chatmock account rename` command
  - [ ] Add `chatmock account refresh` command
  - [ ] Add `chatmock pool status` command
  - [ ] Add `chatmock pool config` command
  - [ ] Update `chatmock info` to show pool status
- [ ] Create shared service layer for CLI/API reuse
- [ ] **Test**: CLI command tests

**Deliverables**:
- Updated `chatmock/cli.py`
- `chatmock/pool_service.py` (shared service layer)
- `tests/test_cli_pool.py`

### Phase 4: API Endpoints

**Goal**: Expose pool management via API

- [ ] Create `chatmock/routes_pool.py`:
  - [ ] `GET /v1/pool/status`
  - [ ] `DELETE /v1/pool/accounts/<id>`
  - [ ] `POST /v1/pool/accounts/<id>/refresh`
- [ ] Register pool blueprint in `app.py`
- [ ] Use shared service layer from Phase 3
- [ ] **Test**: API endpoint tests

**Deliverables**:
- `chatmock/routes_pool.py`
- Updated `chatmock/app.py`
- `tests/test_routes_pool.py`

### Phase 5: Testing & Documentation

**Goal**: Comprehensive testing and documentation

- [ ] Integration tests:
  - [ ] Multi-account login flow
  - [ ] Account switching on rate limit
  - [ ] Cooldown and recovery
  - [ ] Error state handling
  - [ ] Concurrent request handling
- [ ] Load testing:
  - [ ] Multi-threaded stress test
  - [ ] Pool performance with many accounts
- [ ] Documentation:
  - [ ] Update README with multi-account usage
  - [ ] Add migration guide
  - [ ] Add troubleshooting guide

**Deliverables**:
- `tests/integration/test_pool_integration.py`
- `tests/load/test_pool_stress.py`
- Updated `README.md`
- `docs/multi-account.md`
- `docs/migration-guide.md`

## Success Criteria

### Functional Requirements

1. ✅ Multiple accounts can be logged in and persisted
2. ✅ When active account hits 95% rate limit, it enters cooldown
3. ✅ System automatically switches to best available account (weighted selection)
4. ✅ Cooled-down accounts become available after reset time
5. ✅ Pool status is visible via API and CLI
6. ✅ Accounts can be removed via CLI and API
7. ✅ Error accounts require manual intervention (re-login or removal)

### Non-Functional Requirements

8. ✅ Old v1 `auth.json` is automatically migrated with backup
9. ✅ Migration is reversible (can restore from backup)
10. ✅ Thread-safe: multiple concurrent requests handled correctly
11. ✅ Multi-threaded stress test passes (100 concurrent requests, 5 accounts)
12. ✅ Pool file corruption is detected via checksum

### Performance Requirements

13. ✅ Account selection < 10ms (with health cache)
14. ✅ Pool status API response < 50ms
15. ✅ No degradation for single-account users (backward compatible)

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Backward compatibility | Medium | High | Auto-migration with backup, v1 fallback mode |
| Token refresh race conditions | Medium | High | Thread-safe pool manager with RLock, atomic operations |
| OAuth port conflict | Low | Medium | Sequential login only, document limitation |
| Data corruption | Low | High | Atomic writes, checksum verification, backup before write |
| Upstream missing reset header | Medium | Medium | Fallback to configurable default cooldown (1 hour) |
| Unexpected 429 responses | Medium | Medium | Immediate cooldown entry, exponential backoff for retries |
| Token revoked externally | Low | Medium | Detect on failure, mark as ERROR, prompt re-login |
| Large pool performance | Low | Low | Configurable max pool size, lazy loading |
| Health cache stale | Low | Medium | Configurable TTL, force refresh on error |

## Open Questions

| Question | Status | Decision Needed By |
|----------|--------|-------------------|
| Should we support account grouping (e.g., "work" vs "personal")? | Open | Phase 1 |
| Should we support minimum cooldown time even if reset is shorter? | Open | Phase 1 |
| Should we add webhook notifications for pool events? | Open | Phase 4 |
| Should we support account health check via independent probe? | Open | Phase 2 |

## Appendix: Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Error Handling Decision Tree                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Request to ChatGPT API                                        │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────┐                                               │
│   │   Success?  │──Yes──▶ Update usage, reset failure count    │
│   └──────┬──────┘                                               │
│          │ No                                                   │
│          ▼                                                      │
│   ┌─────────────────┐                                          │
│   │  Error Type?    │                                          │
│   └────────┬────────┘                                          │
│            │                                                    │
│   ┌────────┼────────┬────────────┬─────────────┐              │
│   ▼        ▼        ▼            ▼             ▼              │
│  429     401     500-503      Timeout      Other              │
│  Rate    Auth    Server       Network      Unknown            │
│  Limit   Error   Error        Error        Error              │
│   │        │        │            │            │               │
│   ▼        ▼        ▼            ▼            ▼               │
│ Enter    Mark     Retry with   Retry with   Increment         │
│ Cooldown ERROR    next acct    next acct    failure count     │
│          State    (up to 3)    (up to 3)    (up to 3)         │
│                    │            │            │                │
│                    ▼            ▼            ▼                │
│               If all fail   If all fail   If >= 3,           │
│               return 502    return 502     mark ERROR         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```