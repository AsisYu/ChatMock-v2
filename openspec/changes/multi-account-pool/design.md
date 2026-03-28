# Design: Multi-Account Pool Support

## Overview

This document details the technical design for the multi-account pool feature, including module architecture, data flows, API specifications, and implementation guidelines.

## Module Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ChatMock Multi-Account Architecture               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Presentation Layer                            │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │ routes_     │  │ routes_     │  │ routes_     │  │   cli.py   │ │   │
│  │  │ openai.py   │  │ ollama.py   │  │ pool.py     │  │ (commands) │ │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬─────┘ │   │
│  │         │                │                │                │        │   │
│  └─────────┼────────────────┼────────────────┼────────────────┼────────┘   │
│            │                │                │                │            │
│            ▼                ▼                ▼                ▼            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Service Layer                                │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  ┌───────────────────────────────────────────────────────────────┐ │   │
│  │  │                     pool_service.py                            │ │   │
│  │  │  • get_available_account()                                     │ │   │
│  │  │  • record_request_result()                                     │ │   │
│  │  │  • add_account()                                               │ │   │
│  │  │  • remove_account()                                            │ │   │
│  │  │  • get_pool_status()                                           │ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                          Core Layer                                  │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐           │   │
│  │  │ pool_manager  │  │ pool_config   │  │  migration    │           │   │
│  │  │    .py        │  │    .py        │  │    .py        │           │   │
│  │  │               │  │               │  │               │           │   │
│  │  │ • AccountPool │  │ • PoolConfig  │  │ • migrate_v1  │           │   │
│  │  │ • Account     │  │ • defaults    │  │ • rollback    │           │   │
│  │  │ • Selector    │  │               │  │               │           │   │
│  │  └───────┬───────┘  └───────────────┘  └───────────────┘           │   │
│  │          │                                                            │   │
│  │          ▼                                                            │   │
│  │  ┌───────────────────────────────────────────────────────────────┐ │   │
│  │  │                    pool_storage.py                             │ │   │
│  │  │  • load_pool()                                                 │ │   │
│  │  │  • save_pool() (atomic write with backup)                      │ │   │
│  │  │  • verify_checksum()                                           │ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Storage Layer                                  │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  ┌───────────────────────────────────────────────────────────────┐ │   │
│  │  │                      auth.json (v2)                            │ │   │
│  │  │  ~/.chatgpt-local/auth.json                                    │ │   │
│  │  │  ~/.chatgpt-local/auth.json.v1.bak (backup)                    │ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Class Design

### 1. AccountPool (pool_manager.py)

```python
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class AccountStatus(Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    READY = "ready"
    ERROR = "error"


@dataclass
class RateLimitWindow:
    """Rate limit window data from upstream headers."""
    used_percent: float
    window_minutes: Optional[int] = None
    resets_in_seconds: Optional[int] = None
    captured_at: Optional[datetime] = None


@dataclass
class UsageInfo:
    """Usage information for an account."""
    primary: Optional[RateLimitWindow] = None
    secondary: Optional[RateLimitWindow] = None

    def get_max_used_percent(self) -> float:
        """Get the maximum usage percentage across all windows."""
        values = []
        if self.primary:
            values.append(self.primary.used_percent)
        if self.secondary:
            values.append(self.secondary.used_percent)
        return max(values) if values else 0.0


@dataclass
class DiagnosticsInfo:
    """Diagnostic information for troubleshooting."""
    error_reason: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_refresh_at: Optional[datetime] = None
    last_successful_request_at: Optional[datetime] = None
    consecutive_failures: int = 0


@dataclass
class HealthCache:
    """Cached health check result."""
    is_healthy: bool = True
    checked_at: Optional[datetime] = None
    cache_ttl_seconds: int = 60

    def is_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self.checked_at:
            return False
        age = (datetime.now(timezone.utc) - self.checked_at).total_seconds()
        return age < self.cache_ttl_seconds


@dataclass
class AccountTokens:
    """OAuth tokens for an account."""
    id_token: str
    access_token: str
    refresh_token: str
    account_id: str  # chatgpt_account_id from JWT


@dataclass
class Account:
    """Represents a single ChatGPT account in the pool."""
    id: str  # Derived from account_id
    alias: str
    tokens: AccountTokens
    status: AccountStatus = AccountStatus.ACTIVE
    priority: int = 5  # 1 = highest, 10 = lowest
    usage: UsageInfo = field(default_factory=UsageInfo)
    diagnostics: DiagnosticsInfo = field(default_factory=DiagnosticsInfo)
    health_cache: HealthCache = field(default_factory=HealthCache)
    cooldown_until: Optional[datetime] = None
    last_used: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def is_available(self) -> bool:
        """Check if account is available for use."""
        if self.status == AccountStatus.ERROR:
            return False
        if self.status == AccountStatus.COOLDOWN:
            if self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until:
                return False
            # Cooldown expired, mark as ready
            return True
        return True

    def needs_cooldown(self, threshold: float) -> bool:
        """Check if account should enter cooldown based on usage."""
        return self.usage.get_max_used_percent() >= threshold

    def calculate_weight(self) -> float:
        """Calculate selection weight (higher = more likely to be selected)."""
        if not self.is_available():
            return 0.0

        # Priority weight: lower priority number = higher weight
        priority_weight = 1.0 / (self.priority or 10)

        # Quota weight: more remaining = higher weight
        remaining_percent = 100.0 - self.usage.get_max_used_percent()
        quota_weight = max(0.0, remaining_percent) / 100.0

        return priority_weight * quota_weight

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "id": self.id,
            "alias": self.alias,
            "priority": self.priority,
            "tokens": {
                "id_token": self.tokens.id_token,
                "access_token": self.tokens.access_token,
                "refresh_token": self.tokens.refresh_token,
                "account_id": self.tokens.account_id,
            },
            "status": self.status.value,
            "usage": {
                "primary": self._window_to_dict(self.usage.primary),
                "secondary": self._window_to_dict(self.usage.secondary),
            },
            "diagnostics": {
                "error_reason": self.diagnostics.error_reason,
                "last_error_at": self._dt_to_iso(self.diagnostics.last_error_at),
                "last_refresh_at": self._dt_to_iso(self.diagnostics.last_refresh_at),
                "last_successful_request_at": self._dt_to_iso(self.diagnostics.last_successful_request_at),
                "consecutive_failures": self.diagnostics.consecutive_failures,
            },
            "health_cache": {
                "is_healthy": self.health_cache.is_healthy,
                "checked_at": self._dt_to_iso(self.health_cache.checked_at),
                "cache_ttl_seconds": self.health_cache.cache_ttl_seconds,
            },
            "cooldown_until": self._dt_to_iso(self.cooldown_until),
            "last_used": self._dt_to_iso(self.last_used),
            "created_at": self._dt_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        """Deserialize from dictionary."""
        # Implementation details...
        pass

    @staticmethod
    def _window_to_dict(window: Optional[RateLimitWindow]) -> Optional[Dict]:
        if not window:
            return None
        return {
            "used_percent": window.used_percent,
            "window_minutes": window.window_minutes,
            "resets_in_seconds": window.resets_in_seconds,
            "captured_at": Account._dt_to_iso(window.captured_at),
        }

    @staticmethod
    def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
        if not dt:
            return None
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class PoolConfig:
    """Configuration for the account pool."""
    cooldown_threshold: float = 95.0
    default_cooldown_seconds: int = 3600  # 1 hour fallback
    max_pool_size: Optional[int] = None  # None = unlimited
    health_cache_ttl_seconds: int = 60
    max_consecutive_failures: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cooldown_threshold": self.cooldown_threshold,
            "default_cooldown_seconds": self.default_cooldown_seconds,
            "max_pool_size": self.max_pool_size,
            "health_cache_ttl_seconds": self.health_cache_ttl_seconds,
            "max_consecutive_failures": self.max_consecutive_failures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoolConfig":
        return cls(
            cooldown_threshold=data.get("cooldown_threshold", 95.0),
            default_cooldown_seconds=data.get("default_cooldown_seconds", 3600),
            max_pool_size=data.get("max_pool_size"),
            health_cache_ttl_seconds=data.get("health_cache_ttl_seconds", 60),
            max_consecutive_failures=data.get("max_consecutive_failures", 3),
        )


class AccountPool:
    """
    Thread-safe account pool manager.

    Manages multiple ChatGPT accounts with:
    - Weighted round-robin selection
    - Automatic cooldown management
    - Health status caching
    - Thread-safe operations
    """

    def __init__(self, config: Optional[PoolConfig] = None):
        self.config = config or PoolConfig()
        self.accounts: List[Account] = []
        self.current_index: int = 0
        self._lock = threading.RLock()
        self._version: str = "2.0"
        self._migration_state: str = "complete"
        self._checksum: Optional[str] = None

        # Callbacks for external hooks
        self._on_account_added: Optional[Callable[[Account], None]] = None
        self._on_account_removed: Optional[Callable[[Account], None]] = None
        self._on_account_status_changed: Optional[Callable[[Account, AccountStatus], None]] = None

    # ==================== Account Selection ====================

    def get_available_account(self) -> Account:
        """
        Get the best available account using weighted selection.

        Raises:
            NoAvailableAccountError: If no accounts are available
        """
        with self._lock:
            # Update cooldowns (expired cooldowns become ready)
            self._update_cooldowns()

            # Get available accounts with valid health cache
            available = [acc for acc in self.accounts if acc.is_available()]

            if not available:
                raise NoAvailableAccountError("No accounts available in pool")

            # Calculate weights
            weights = [acc.calculate_weight() for acc in available]
            total_weight = sum(weights)

            if total_weight <= 0:
                raise NoAvailableAccountError("All accounts have zero weight")

            # Weighted random selection
            import random
            r = random.uniform(0, total_weight)
            cumulative = 0.0
            for acc, weight in zip(available, weights):
                cumulative += weight
                if r <= cumulative:
                    acc.last_used = datetime.now(timezone.utc)
                    return acc

            # Fallback to last account
            acc = available[-1]
            acc.last_used = datetime.now(timezone.utc)
            return acc

    def _update_cooldowns(self) -> None:
        """Update cooldown states for all accounts."""
        now = datetime.now(timezone.utc)
        for acc in self.accounts:
            if acc.status == AccountStatus.COOLDOWN:
                if acc.cooldown_until and now >= acc.cooldown_until:
                    acc.status = AccountStatus.READY
                    acc.cooldown_until = None

    # ==================== Account Management ====================

    def add_account(self, account: Account) -> bool:
        """
        Add a new account to the pool.

        Returns:
            True if added, False if account already exists
        """
        with self._lock:
            # Check for duplicate
            if any(a.id == account.id for a in self.accounts):
                return False

            # Check max pool size
            if self.config.max_pool_size and len(self.accounts) >= self.config.max_pool_size:
                raise PoolSizeLimitError(f"Pool size limit reached: {self.config.max_pool_size}")

            account.created_at = datetime.now(timezone.utc)
            self.accounts.append(account)

            if self._on_account_added:
                self._on_account_added(account)

            return True

    def remove_account(self, account_id: str) -> bool:
        """
        Remove an account from the pool.

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            for i, acc in enumerate(self.accounts):
                if acc.id == account_id:
                    removed = self.accounts.pop(i)
                    # Adjust current_index if needed
                    if self.current_index >= len(self.accounts) and len(self.accounts) > 0:
                        self.current_index = len(self.accounts) - 1

                    if self._on_account_removed:
                        self._on_account_removed(removed)

                    return True
            return False

    def get_account_by_id(self, account_id: str) -> Optional[Account]:
        """Get an account by its ID."""
        with self._lock:
            for acc in self.accounts:
                if acc.id == account_id:
                    return acc
            return None

    def get_account_by_alias(self, alias: str) -> Optional[Account]:
        """Get an account by its alias."""
        with self._lock:
            for acc in self.accounts:
                if acc.alias == alias:
                    return acc
            return None

    # ==================== Request Result Recording ====================

    def record_request_success(
        self,
        account_id: str,
        usage: Optional[UsageInfo] = None,
    ) -> None:
        """Record a successful request and update usage info."""
        with self._lock:
            account = self.get_account_by_id(account_id)
            if not account:
                return

            account.diagnostics.consecutive_failures = 0
            account.diagnostics.last_successful_request_at = datetime.now(timezone.utc)
            account.diagnostics.error_reason = None

            if usage:
                account.usage = usage

            # Check if cooldown needed
            if account.needs_cooldown(self.config.cooldown_threshold):
                self._enter_cooldown(account)

    def record_request_failure(
        self,
        account_id: str,
        error: Exception,
        reset_after: Optional[int] = None,
    ) -> None:
        """
        Record a failed request and handle state transitions.

        Args:
            account_id: The account that failed
            error: The exception that occurred
            reset_after: Seconds until rate limit reset (from 429 response)
        """
        with self._lock:
            account = self.get_account_by_id(account_id)
            if not account:
                return

            account.diagnostics.last_error_at = datetime.now(timezone.utc)
            account.diagnostics.error_reason = str(error)

            # Handle different error types
            if isinstance(error, RateLimitError):
                # 429: Enter cooldown
                cooldown_seconds = reset_after or self.config.default_cooldown_seconds
                self._enter_cooldown(account, cooldown_seconds)

            elif isinstance(error, AuthenticationError):
                # 401: Mark as error
                self._set_error_status(account, "Authentication failed")

            else:
                # Other errors: track consecutive failures
                account.diagnostics.consecutive_failures += 1
                if account.diagnostics.consecutive_failures >= self.config.max_consecutive_failures:
                    self._set_error_status(
                        account,
                        f"Consecutive failures: {account.diagnostics.consecutive_failures}"
                    )

    def _enter_cooldown(self, account: Account, seconds: Optional[int] = None) -> None:
        """Put an account into cooldown state."""
        cooldown_seconds = seconds or self.config.default_cooldown_seconds
        account.status = AccountStatus.COOLDOWN
        account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)

        if self._on_account_status_changed:
            self._on_account_status_changed(account, AccountStatus.COOLDOWN)

    def _set_error_status(self, account: Account, reason: str) -> None:
        """Mark an account as error state."""
        old_status = account.status
        account.status = AccountStatus.ERROR
        account.diagnostics.error_reason = reason

        if self._on_account_status_changed:
            self._on_account_status_changed(account, old_status)

    # ==================== Pool Status ====================

    def get_pool_status(self) -> Dict[str, Any]:
        """Get the overall pool status."""
        with self._lock:
            self._update_cooldowns()

            status_counts = {
                AccountStatus.ACTIVE: 0,
                AccountStatus.COOLDOWN: 0,
                AccountStatus.READY: 0,
                AccountStatus.ERROR: 0,
            }

            for acc in self.accounts:
                status_counts[acc.status] += 1

            return {
                "total_accounts": len(self.accounts),
                "active_accounts": status_counts[AccountStatus.ACTIVE] + status_counts[AccountStatus.READY],
                "cooldown_accounts": status_counts[AccountStatus.COOLDOWN],
                "error_accounts": status_counts[AccountStatus.ERROR],
                "accounts": [self._account_to_status_dict(acc) for acc in self.accounts],
            }

    def _account_to_status_dict(self, account: Account) -> Dict[str, Any]:
        """Convert account to status API response format."""
        result = {
            "id": account.id,
            "alias": account.alias,
            "status": account.status.value,
            "priority": account.priority,
            "usage_percent": account.usage.get_max_used_percent(),
            "remaining_percent": 100.0 - account.usage.get_max_used_percent(),
            "last_used_at": Account._dt_to_iso(account.last_used),
            "last_error": account.diagnostics.error_reason,
        }

        if account.cooldown_until:
            remaining = (account.cooldown_until - datetime.now(timezone.utc)).total_seconds()
            result["cooldown_remaining"] = self._format_duration(remaining)
            result["cooldown_until"] = Account._dt_to_iso(account.cooldown_until)

        return result

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds <= 0:
            return "0m"

        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)


# ==================== Custom Exceptions ====================

class NoAvailableAccountError(Exception):
    """Raised when no accounts are available in the pool."""
    pass


class PoolSizeLimitError(Exception):
    """Raised when pool size limit is reached."""
    pass


class RateLimitError(Exception):
    """Raised when rate limit is hit (429 response)."""
    def __init__(self, message: str, reset_after: Optional[int] = None):
        super().__init__(message)
        self.reset_after = reset_after


class AuthenticationError(Exception):
    """Raised when authentication fails (401 response)."""
    pass
```

### 2. PoolStorage (pool_storage.py)

```python
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .pool_manager import AccountPool, Account, PoolConfig


class PoolStorage:
    """
    Handles persistent storage of the account pool.

    Features:
    - Atomic writes with backup
    - Checksum verification
    - Migration from v1 format
    """

    AUTH_FILENAME = "auth.json"
    BACKUP_SUFFIX = ".v1.bak"
    VERSION = "2.0"

    def __init__(self, home_dir: Optional[str] = None):
        self.home_dir = home_dir or self._get_default_home()
        self.auth_path = Path(self.home_dir) / self.AUTH_FILENAME
        self.backup_path = Path(str(self.auth_path) + self.BACKUP_SUFFIX)

    @staticmethod
    def _get_default_home() -> str:
        """Get the default home directory for auth storage."""
        return os.getenv("CHATGPT_LOCAL_HOME") or os.path.expanduser("~/.chatgpt-local")

    def load_pool(self) -> AccountPool:
        """
        Load the account pool from disk.

        Handles:
        - v1 format migration
        - Corrupted files
        - Missing files
        """
        if not self.auth_path.exists():
            return AccountPool()

        try:
            with open(self.auth_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # Try to recover from backup
            return self._recover_from_backup()

        # Detect format version
        version = data.get("version", "1.0")

        if version == "1.0":
            # Migrate from v1
            return self._migrate_from_v1(data)
        elif version == self.VERSION:
            # Load v2 format
            return self._load_v2(data)
        else:
            raise ValueError(f"Unknown auth file version: {version}")

    def save_pool(self, pool: AccountPool) -> bool:
        """
        Save the account pool to disk atomically.

        Uses atomic write pattern:
        1. Write to temp file
        2. Rename temp to target
        3. Sync directory
        """
        # Ensure directory exists
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare data
        data = {
            "version": self.VERSION,
            "migration_state": pool._migration_state,
            "checksum": "",  # Will be filled after serialization
            "accounts": [acc.to_dict() for acc in pool.accounts],
            "current_index": pool.current_index,
            "config": pool.config.to_dict(),
        }

        # Calculate checksum
        accounts_json = json.dumps(data["accounts"], sort_keys=True)
        checksum = hashlib.sha256(accounts_json.encode()).hexdigest()
        data["checksum"] = f"sha256:{checksum}"

        # Atomic write
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.auth_path.parent,
                prefix=".auth_tmp_",
                delete=False
            ) as tmp:
                json.dump(data, tmp, indent=2)
                tmp_path = Path(tmp.name)

            # Atomic rename
            tmp_path.replace(self.auth_path)

            return True
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def verify_checksum(self, pool_data: Dict[str, Any]) -> bool:
        """Verify the integrity of pool data using checksum."""
        stored_checksum = pool_data.get("checksum", "")
        if not stored_checksum.startswith("sha256:"):
            return False

        accounts_json = json.dumps(pool_data.get("accounts", []), sort_keys=True)
        computed = hashlib.sha256(accounts_json.encode()).hexdigest()
        expected = stored_checksum[7:]  # Remove "sha256:" prefix

        return computed == expected

    def _migrate_from_v1(self, data: Dict[str, Any]) -> AccountPool:
        """
        Migrate from v1 single-account format to v2 pool format.

        v1 format:
        {
            "OPENAI_API_KEY": "...",
            "tokens": {
                "id_token": "...",
                "access_token": "...",
                "refresh_token": "...",
                "account_id": "..."
            },
            "last_refresh": "..."
        }
        """
        from .models import TokenData
        from .utils import parse_jwt_claims

        # Backup original file
        self._create_backup()

        tokens = data.get("tokens", {})
        if not tokens:
            return AccountPool()

        # Extract account info
        id_token = tokens.get("id_token", "")
        claims = parse_jwt_claims(id_token) or {}
        auth_claims = claims.get("https://api.openai.com/auth", {})
        account_id = auth_claims.get("chatgpt_account_id") or tokens.get("account_id", "unknown")

        # Get email for alias
        email = claims.get("email") or claims.get("preferred_username") or f"account_{account_id[:8]}"

        # Create account
        account = Account(
            id=account_id,
            alias=email,
            tokens=AccountTokens(
                id_token=id_token,
                access_token=tokens.get("access_token", ""),
                refresh_token=tokens.get("refresh_token", ""),
                account_id=account_id,
            ),
            created_at=datetime.now(timezone.utc),
        )

        # Create pool with migrated account
        pool = AccountPool()
        pool._migration_state = "complete"
        pool.accounts = [account]

        # Save in new format
        self.save_pool(pool)

        return pool

    def _create_backup(self) -> None:
        """Create a backup of the current auth file."""
        if self.auth_path.exists() and not self.backup_path.exists():
            shutil.copy2(self.auth_path, self.backup_path)

    def _recover_from_backup(self) -> AccountPool:
        """Attempt to recover from backup file."""
        if self.backup_path.exists():
            try:
                with open(self.backup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._migrate_from_v1(data)
            except Exception:
                pass
        return AccountPool()

    def _load_v2(self, data: Dict[str, Any]) -> AccountPool:
        """Load v2 format pool data."""
        # Verify checksum
        if not self.verify_checksum(data):
            raise ValueError("Checksum verification failed - file may be corrupted")

        config = PoolConfig.from_dict(data.get("config", {}))
        pool = AccountPool(config=config)

        pool._migration_state = data.get("migration_state", "complete")
        pool._checksum = data.get("checksum")
        pool.current_index = data.get("current_index", 0)

        for acc_data in data.get("accounts", []):
            account = Account.from_dict(acc_data)
            pool.accounts.append(account)

        return pool

    def rollback_migration(self) -> bool:
        """
        Rollback to v1 format from backup.

        Returns:
            True if rollback succeeded
        """
        if not self.backup_path.exists():
            return False

        try:
            # Restore from backup
            shutil.copy2(self.backup_path, self.auth_path)
            return True
        except Exception:
            return False
```

### 3. PoolService (pool_service.py)

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .pool_manager import (
    AccountPool,
    Account,
    AccountStatus,
    NoAvailableAccountError,
    RateLimitError,
    AuthenticationError,
)
from .pool_storage import PoolStorage
from .limits import parse_rate_limit_headers, RateLimitSnapshot
from .utils import refresh_chatgpt_tokens, parse_jwt_claims


class PoolService:
    """
    Service layer for account pool operations.

    Provides a unified interface for:
    - CLI commands
    - API endpoints
    - Internal auth integration
    """

    def __init__(self, storage: Optional[PoolStorage] = None):
        self.storage = storage or PoolStorage()
        self._pool: Optional[AccountPool] = None

    @property
    def pool(self) -> AccountPool:
        """Lazy-load the pool on first access."""
        if self._pool is None:
            self._pool = self.storage.load_pool()
        return self._pool

    def _save(self) -> bool:
        """Save the pool and return success status."""
        return self.storage.save_pool(self.pool)

    # ==================== Auth Integration ====================

    def get_account_for_request(self) -> Tuple[str, str, str]:
        """
        Get account credentials for an upstream request.

        Returns:
            Tuple of (access_token, account_id, internal_account_id)

        Raises:
            NoAvailableAccountError: If no accounts available
        """
        account = self.pool.get_available_account()

        # Ensure tokens are fresh
        self._ensure_fresh_tokens(account)

        return (
            account.tokens.access_token,
            account.tokens.account_id,
            account.id,
        )

    def record_request_success(
        self,
        internal_account_id: str,
        response_headers: Any,
    ) -> None:
        """Record a successful request and update rate limit info."""
        from .pool_manager import UsageInfo, RateLimitWindow

        # Parse rate limit headers
        snapshot = parse_rate_limit_headers(response_headers)

        usage = UsageInfo()
        if snapshot and snapshot.primary:
            usage.primary = RateLimitWindow(
                used_percent=snapshot.primary.used_percent,
                window_minutes=snapshot.primary.window_minutes,
                resets_in_seconds=snapshot.primary.resets_in_seconds,
                captured_at=datetime.now(timezone.utc),
            )
        if snapshot and snapshot.secondary:
            usage.secondary = RateLimitWindow(
                used_percent=snapshot.secondary.used_percent,
                window_minutes=snapshot.secondary.window_minutes,
                resets_in_seconds=snapshot.secondary.resets_in_seconds,
                captured_at=datetime.now(timezone.utc),
            )

        self.pool.record_request_success(internal_account_id, usage)
        self._save()

    def record_request_failure(
        self,
        internal_account_id: str,
        error: Exception,
        reset_after: Optional[int] = None,
    ) -> None:
        """Record a failed request."""
        self.pool.record_request_failure(internal_account_id, error, reset_after)
        self._save()

    def _ensure_fresh_tokens(self, account: Account) -> None:
        """Ensure account tokens are fresh, refresh if needed."""
        # Token refresh logic similar to existing load_chatgpt_tokens
        # but for a single account
        pass

    # ==================== Account Management ====================

    def add_account_from_oauth(
        self,
        id_token: str,
        access_token: str,
        refresh_token: str,
        alias: Optional[str] = None,
    ) -> Account:
        """
        Add a new account from OAuth callback.

        Returns:
            The created account

        Raises:
            ValueError: If account already exists
        """
        # Extract account info from JWT
        claims = parse_jwt_claims(id_token) or {}
        auth_claims = claims.get("https://api.openai.com/auth", {})
        account_id = auth_claims.get("chatgpt_account_id")

        if not account_id:
            raise ValueError("Could not extract account_id from id_token")

        # Check for duplicate
        if self.pool.get_account_by_id(account_id):
            raise ValueError(f"Account {account_id} already exists in pool")

        # Create alias if not provided
        if not alias:
            alias = claims.get("email") or claims.get("preferred_username") or f"account_{account_id[:8]}"

        account = Account(
            id=account_id,
            alias=alias,
            tokens=AccountTokens(
                id_token=id_token,
                access_token=access_token,
                refresh_token=refresh_token,
                account_id=account_id,
            ),
            created_at=datetime.now(timezone.utc),
        )

        self.pool.add_account(account)
        self._save()

        return account

    def remove_account(self, account_id: str) -> bool:
        """Remove an account from the pool."""
        result = self.pool.remove_account(account_id)
        if result:
            self._save()
        return result

    def set_account_alias(self, account_id: str, alias: str) -> bool:
        """Set a new alias for an account."""
        account = self.pool.get_account_by_id(account_id)
        if not account:
            return False
        account.alias = alias
        self._save()
        return True

    def set_account_priority(self, account_id: str, priority: int) -> bool:
        """Set priority for an account (1=highest, 10=lowest)."""
        if not 1 <= priority <= 10:
            raise ValueError("Priority must be between 1 and 10")

        account = self.pool.get_account_by_id(account_id)
        if not account:
            return False
        account.priority = priority
        self._save()
        return True

    def refresh_account(self, account_id: str) -> bool:
        """Force refresh tokens for an account."""
        account = self.pool.get_account_by_id(account_id)
        if not account:
            return False

        # Refresh tokens
        new_tokens = refresh_chatgpt_tokens(account.tokens.refresh_token)
        if new_tokens:
            account.tokens.access_token = new_tokens.get("access_token", account.tokens.access_token)
            account.tokens.id_token = new_tokens.get("id_token", account.tokens.id_token)
            if new_tokens.get("refresh_token"):
                account.tokens.refresh_token = new_tokens["refresh_token"]
            account.diagnostics.last_refresh_at = datetime.now(timezone.utc)
            self._save()
            return True

        return False

    # ==================== Status & Query ====================

    def get_pool_status(self) -> Dict[str, Any]:
        """Get the full pool status for API/CLI."""
        return self.pool.get_pool_status()

    def get_account_info(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed info for a single account."""
        account = self.pool.get_account_by_id(account_id)
        if not account:
            return None
        return self.pool._account_to_status_dict(account)

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Get a summary list of all accounts."""
        return [
            {
                "id": acc.id,
                "alias": acc.alias,
                "status": acc.status.value,
                "priority": acc.priority,
                "usage_percent": acc.usage.get_max_used_percent(),
            }
            for acc in self.pool.accounts
        ]


# Singleton instance for global access
_pool_service: Optional[PoolService] = None


def get_pool_service() -> PoolService:
    """Get the singleton pool service instance."""
    global _pool_service
    if _pool_service is None:
        _pool_service = PoolService()
    return _pool_service
```

## Data Flow Diagrams

### 1. Request Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Request Processing Flow                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Client Request                                                            │
│        │                                                                    │
│        ▼                                                                    │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  routes_openai.py: chat_completions()                             │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  pool_service.get_account_for_request()                           │     │
│   │  ┌────────────────────────────────────────────────────────────┐  │     │
│   │  │ 1. pool.get_available_account()                             │  │     │
│   │  │    - Update cooldowns                                       │  │     │
│   │  │    - Calculate weights                                      │  │     │
│   │  │    - Select best account                                    │  │     │
│   │  │ 2. _ensure_fresh_tokens()                                   │  │     │
│   │  │    - Check expiry                                           │  │     │
│   │  │    - Refresh if needed                                      │  │     │
│   │  │ 3. Return (access_token, account_id, internal_id)           │  │     │
│   │  └────────────────────────────────────────────────────────────┘  │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  upstream.start_upstream_request()                                │     │
│   │  - Build request with selected account's tokens                   │     │
│   │  - Send to ChatGPT Responses API                                  │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                      ┌────────────┴────────────┐                           │
│                      ▼                         ▼                           │
│               ┌──────────┐              ┌──────────┐                       │
│               │  Success │              │  Failure │                       │
│               └────┬─────┘              └────┬─────┘                       │
│                    │                         │                             │
│                    ▼                         ▼                             │
│   ┌─────────────────────────┐   ┌──────────────────────────────┐          │
│   │ pool_service            │   │ pool_service                 │          │
│   │ .record_request_success │   │ .record_request_failure      │          │
│   │ - Update usage          │   │ - Parse error type           │          │
│   │ - Check cooldown need   │   │ - Handle 429 → cooldown      │          │
│   │ - Save pool             │   │ - Handle 401 → error state   │          │
│   └─────────────────────────┘   │ - Save pool                  │          │
│                                  └──────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Login Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Login Flow                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   $ chatmock login                                                          │
│        │                                                                    │
│        ▼                                                                    │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  cli.py: cmd_login()                                              │     │
│   │  - Start OAuth server on port 1455                                │     │
│   │  - Open browser to auth.openai.com                                │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  User authenticates in browser                                    │     │
│   │  - Callback to localhost:1455/auth/callback                       │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  oauth.py: OAuthHandler.do_GET()                                  │     │
│   │  - Exchange code for tokens                                       │     │
│   │  - Extract account_id from id_token                               │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  Interactive Confirmation (NEW)                                   │     │
│   │  ┌────────────────────────────────────────────────────────────┐  │     │
│   │  │ New account detected:                                       │  │     │
│   │  │   Email: user@example.com                                   │  │     │
│   │  │   Plan: Plus                                                │  │     │
│   │  │   Account ID: chatgpt_abc123                                │  │     │
│   │  │                                                            │  │     │
│   │  │ Add to pool? [Y/n]: y                                      │  │     │
│   │  │ Enter alias [default: user@example.com]: work-account      │  │     │
│   │  └────────────────────────────────────────────────────────────┘  │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  pool_service.add_account_from_oauth()                            │     │
│   │  - Create Account object                                          │     │
│   │  - Add to pool                                                    │     │
│   │  - Save to auth.json                                              │     │
│   └───────────────────────────────┬──────────────────────────────────┘     │
│                                   │                                         │
│                                   ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐     │
│   │  Success Message                                                  │     │
│   │  "Account 'work-account' added to pool. Total accounts: 2"        │     │
│   └──────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API Specification

### GET /v1/pool/status

**Description**: Get the status of all accounts in the pool.

**Response**:
```json
{
  "total_accounts": 3,
  "active_accounts": 2,
  "cooldown_accounts": 1,
  "error_accounts": 0,
  "accounts": [
    {
      "id": "chatgpt_abc123",
      "alias": "work-account",
      "status": "active",
      "priority": 1,
      "usage_percent": 45.0,
      "remaining_percent": 55.0,
      "resets_in": "2h",
      "cooldown_remaining": null,
      "last_used_at": "2025-03-28T12:00:00Z",
      "last_error": null
    }
  ]
}
```

### DELETE /v1/pool/accounts/{account_id}

**Description**: Remove an account from the pool.

**Parameters**:
- `account_id` (path): The account ID to remove

**Response**:
```json
{
  "success": true,
  "message": "Account 'work-account' removed from pool"
}
```

**Errors**:
- `404`: Account not found

### POST /v1/pool/accounts/{account_id}/refresh

**Description**: Force refresh tokens for an account.

**Parameters**:
- `account_id` (path): The account ID to refresh

**Response**:
```json
{
  "success": true,
  "account_id": "chatgpt_abc123",
  "refreshed_at": "2025-03-28T12:05:00Z"
}
```

**Errors**:
- `404`: Account not found
- `400`: Refresh failed

### PATCH /v1/pool/accounts/{account_id}

**Description**: Update account settings.

**Parameters**:
- `account_id` (path): The account ID to update

**Request Body**:
```json
{
  "alias": "new-alias",
  "priority": 2
}
```

**Response**:
```json
{
  "success": true,
  "account": {
    "id": "chatgpt_abc123",
    "alias": "new-alias",
    "priority": 2
  }
}
```

## CLI Specification

### chatmock login

```
Usage: chatmock login [OPTIONS]

Authorize with ChatGPT and add account to pool.

Options:
  --no-browser    Do not open browser automatically
  --alias TEXT    Account alias (skip interactive prompt)
  --verbose       Enable verbose logging

Examples:
  chatmock login
  chatmock login --alias work-account
  chatmock login --no-browser
```

### chatmock account list

```
Usage: chatmock account list [OPTIONS]

List all accounts in the pool.

Options:
  --format TEXT   Output format: table, json  [default: table]

Output:
  ID              Alias          Status    Priority   Usage
  chatgpt_abc123  work-account   active    1          45%
  chatgpt_def456  personal       cooldown  2          96%
```

### chatmock account show

```
Usage: chatmock account show <ACCOUNT_ID>

Show detailed information for an account.

Output:
  ID:              chatgpt_abc123
  Alias:           work-account
  Status:          active
  Priority:        1
  Usage:
    Primary:       45.0% (resets in 2h)
    Secondary:     20.0% (resets in 5d)
  Last Used:       2025-03-28 12:00:00 UTC
  Created:         2025-03-20 10:00:00 UTC
```

### chatmock account remove

```
Usage: chatmock account remove <ACCOUNT_ID> [OPTIONS]

Remove an account from the pool.

Options:
  --force    Skip confirmation prompt

Examples:
  chatmock account remove chatgpt_abc123
  chatmock account remove chatgpt_abc123 --force
```

### chatmock account rename

```
Usage: chatmock account rename <ACCOUNT_ID> <NEW_ALIAS>

Rename an account's alias.

Example:
  chatmock account rename chatgpt_abc123 my-work-account
```

### chatmock account priority

```
Usage: chatmock account priority <ACCOUNT_ID> <PRIORITY>

Set account priority (1=highest, 10=lowest).

Example:
  chatmock account priority chatgpt_abc123 1
```

### chatmock account refresh

```
Usage: chatmock account refresh <ACCOUNT_ID>

Force refresh tokens for an account.

Example:
  chatmock account refresh chatgpt_abc123
```

### chatmock pool status

```
Usage: chatmock pool status [OPTIONS]

Show overall pool status.

Options:
  --json    Output in JSON format

Output:
  Pool Status
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total Accounts:     3
  Active:             2
  Cooldown:           1
  Error:              0

  Accounts:
  ┌────────────────┬─────────────┬──────────┬─────────┐
  │ Alias          │ Status      │ Priority │ Usage   │
  ├────────────────┼─────────────┼──────────┼─────────┤
  │ work-account   │ active      │ 1        │ 45%     │
  │ personal       │ cooldown    │ 2        │ 96%     │
  │ backup         │ active      │ 3        │ 10%     │
  └────────────────┴─────────────┴──────────┴─────────┘
```

### chatmock pool config

```
Usage: chatmock pool config [OPTIONS]

View or modify pool configuration.

Options:
  --cooldown-threshold FLOAT    Set cooldown trigger threshold (0-100)
  --default-cooldown INT        Set default cooldown seconds
  --max-pool-size INT           Set maximum pool size (0=unlimited)

Examples:
  chatmock pool config
  chatmock pool config --cooldown-threshold 90
  chatmock pool config --default-cooldown 1800
```

## Error Handling

### Error Types

| Error Type | HTTP Status | Handling |
|------------|-------------|----------|
| `NoAvailableAccountError` | 503 | All accounts in cooldown or error |
| `RateLimitError` | 429 | Account enters cooldown |
| `AuthenticationError` | 401 | Account marked as ERROR |
| `PoolSizeLimitError` | 400 | Max pool size reached |
| `AccountNotFoundError` | 404 | Account ID not found |

### Error Response Format

```json
{
  "error": {
    "type": "NoAvailableAccountError",
    "message": "No accounts available in pool",
    "details": {
      "total_accounts": 3,
      "cooldown_accounts": 2,
      "error_accounts": 1
    }
  }
}
```

## Testing Strategy

### Unit Tests

| Module | Test File | Coverage Target |
|--------|-----------|-----------------|
| `pool_manager.py` | `tests/test_pool_manager.py` | 95% |
| `pool_storage.py` | `tests/test_pool_storage.py` | 90% |
| `pool_service.py` | `tests/test_pool_service.py` | 90% |
| `migration.py` | `tests/test_migration.py` | 95% |

### Integration Tests

| Scenario | Test File |
|----------|-----------|
| Multi-account login | `tests/integration/test_multi_login.py` |
| Account switching | `tests/integration/test_account_switching.py` |
| Rate limit cooldown | `tests/integration/test_cooldown.py` |
| Error recovery | `tests/integration/test_error_recovery.py` |

### Load Tests

| Test | Description |
|------|-------------|
| Concurrent requests | 100 concurrent requests with 5 accounts |
| Pool stress | 1000 accounts in pool |
| Long-running stability | 24-hour continuous operation |

## Migration Guide

### v1 to v2 Migration

**Automatic Migration**:
1. Detect v1 format (no `version` field)
2. Create backup: `auth.json` → `auth.json.v1.bak`
3. Convert to v2 format
4. Save new format
5. Update `migration_state` to `complete`

**Rollback**:
```bash
chatmock pool rollback
```

### Manual Migration

If automatic migration fails:

1. Backup existing auth.json
2. Run: `chatmock login` for each account
3. Remove old backup after verification

## Security Considerations

1. **Token Storage**: Tokens stored in `~/.chatgpt-local/auth.json` with 0600 permissions
2. **Backup Security**: Backup files also have 0600 permissions
3. **Memory Safety**: Tokens only held in memory during request processing
4. **Log Safety**: Never log token values, only account IDs/aliases
5. **API Security**: Pool status API only accessible from localhost (no external exposure)