"""
Multi-Account Pool Manager for ChatMock.

This module provides thread-safe management of multiple ChatGPT accounts
with automatic switching, cooldown management, and weighted selection.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ==============================================================================
# Exceptions
# ==============================================================================

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


class AccountNotFoundError(Exception):
    """Raised when account is not found in pool."""
    pass


# ==============================================================================
# Enums
# ==============================================================================

class AccountStatus(Enum):
    """Account status in the pool."""
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    READY = "ready"
    ERROR = "error"


# ==============================================================================
# Data Classes
# ==============================================================================

@dataclass
class RateLimitWindow:
    """Rate limit window data from upstream headers."""
    used_percent: float
    window_minutes: Optional[int] = None
    resets_in_seconds: Optional[int] = None
    captured_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "used_percent": self.used_percent,
            "window_minutes": self.window_minutes,
            "resets_in_seconds": self.resets_in_seconds,
            "captured_at": _dt_to_iso(self.captured_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RateLimitWindow":
        return cls(
            used_percent=data.get("used_percent", 0.0),
            window_minutes=data.get("window_minutes"),
            resets_in_seconds=data.get("resets_in_seconds"),
            captured_at=_parse_iso8601(data.get("captured_at")),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary.to_dict() if self.primary else None,
            "secondary": self.secondary.to_dict() if self.secondary else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsageInfo":
        return cls(
            primary=RateLimitWindow.from_dict(data["primary"]) if data.get("primary") else None,
            secondary=RateLimitWindow.from_dict(data["secondary"]) if data.get("secondary") else None,
        )


@dataclass
class DiagnosticsInfo:
    """Diagnostic information for troubleshooting."""
    error_reason: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_refresh_at: Optional[datetime] = None
    last_successful_request_at: Optional[datetime] = None
    consecutive_failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_reason": self.error_reason,
            "last_error_at": _dt_to_iso(self.last_error_at),
            "last_refresh_at": _dt_to_iso(self.last_refresh_at),
            "last_successful_request_at": _dt_to_iso(self.last_successful_request_at),
            "consecutive_failures": self.consecutive_failures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticsInfo":
        return cls(
            error_reason=data.get("error_reason"),
            last_error_at=_parse_iso8601(data.get("last_error_at")),
            last_refresh_at=_parse_iso8601(data.get("last_refresh_at")),
            last_successful_request_at=_parse_iso8601(data.get("last_successful_request_at")),
            consecutive_failures=data.get("consecutive_failures", 0),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_healthy": self.is_healthy,
            "checked_at": _dt_to_iso(self.checked_at),
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthCache":
        return cls(
            is_healthy=data.get("is_healthy", True),
            checked_at=_parse_iso8601(data.get("checked_at")),
            cache_ttl_seconds=data.get("cache_ttl_seconds", 60),
        )


@dataclass
class AccountTokens:
    """OAuth tokens for an account."""
    id_token: str
    access_token: str
    refresh_token: str
    account_id: str  # chatgpt_account_id from JWT

    def to_dict(self) -> Dict[str, str]:
        return {
            "id_token": self.id_token,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "account_id": self.account_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountTokens":
        return cls(
            id_token=data.get("id_token", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            account_id=data.get("account_id", ""),
        )


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
            # Cooldown expired
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
            "tokens": self.tokens.to_dict(),
            "status": self.status.value,
            "usage": self.usage.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "health_cache": self.health_cache.to_dict(),
            "cooldown_until": _dt_to_iso(self.cooldown_until),
            "last_used": _dt_to_iso(self.last_used),
            "created_at": _dt_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", ""),
            alias=data.get("alias", ""),
            tokens=AccountTokens.from_dict(data.get("tokens", {})),
            status=AccountStatus(data.get("status", "active")),
            priority=data.get("priority", 5),
            usage=UsageInfo.from_dict(data.get("usage", {})),
            diagnostics=DiagnosticsInfo.from_dict(data.get("diagnostics", {})),
            health_cache=HealthCache.from_dict(data.get("health_cache", {})),
            cooldown_until=_parse_iso8601(data.get("cooldown_until")),
            last_used=_parse_iso8601(data.get("last_used")),
            created_at=_parse_iso8601(data.get("created_at")),
        )


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


# ==============================================================================
# Account Pool Manager
# ==============================================================================

class AccountPool:
    """
    Thread-safe account pool manager.

    Manages multiple ChatGPT accounts with:
    - Weighted round-robin selection
    - Automatic cooldown management
    - Health status caching
    - Thread-safe operations
    """

    VERSION = "2.0"

    def __init__(self, config: Optional[PoolConfig] = None):
        self.config = config or PoolConfig()
        self.accounts: List[Account] = []
        self.current_index: int = 0
        self._lock = threading.RLock()
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

            # Get available accounts
            available = [acc for acc in self.accounts if acc.is_available()]

            if not available:
                raise NoAvailableAccountError("No accounts available in pool")

            # Calculate weights
            weights = [acc.calculate_weight() for acc in available]
            total_weight = sum(weights)

            if total_weight <= 0:
                # All have zero weight, pick randomly
                acc = random.choice(available)
                acc.last_used = datetime.now(timezone.utc)
                return acc

            # Weighted random selection
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
        account.status = AccountStatus.ERROR
        account.diagnostics.error_reason = reason

        if self._on_account_status_changed:
            self._on_account_status_changed(account, AccountStatus.ERROR)

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

    def list_account_statuses(self) -> List[Dict[str, Any]]:
        """Thread-safe snapshot of all account statuses."""
        with self._lock:
            self._update_cooldowns()
            return [self._account_to_status_dict(acc) for acc in self.accounts]

    def get_account_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Thread-safe helper for retrieving a single account status."""
        with self._lock:
            self._update_cooldowns()
            for acc in self.accounts:
                if acc.id == account_id:
                    return self._account_to_status_dict(acc)
            return None

    def _account_to_status_dict(self, account: Account) -> Dict[str, Any]:
        """Convert account to status API response format."""
        result = {
            "id": account.id,
            "alias": account.alias,
            "status": account.status.value,
            "priority": account.priority,
            "usage_percent": account.usage.get_max_used_percent(),
            "remaining_percent": 100.0 - account.usage.get_max_used_percent(),
            "last_used_at": _dt_to_iso(account.last_used),
            "last_error": account.diagnostics.error_reason,
        }

        if account.cooldown_until:
            remaining = (account.cooldown_until - datetime.now(timezone.utc)).total_seconds()
            result["cooldown_remaining"] = _format_duration(remaining)
            result["cooldown_until"] = _dt_to_iso(account.cooldown_until)

        return result

    # ==================== Serialization ====================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize pool to dictionary using a consistent snapshot."""
        with self._lock:
            accounts_data = [acc.to_dict() for acc in self.accounts]

            # Calculate checksum while holding the lock to keep the snapshot consistent.
            accounts_json = json.dumps(accounts_data, sort_keys=True)
            checksum = hashlib.sha256(accounts_json.encode()).hexdigest()

            migration_state = self._migration_state
            current_index = self.current_index
            config_dict = self.config.to_dict()

        return {
            "version": self.VERSION,
            "migration_state": migration_state,
            "checksum": f"sha256:{checksum}",
            "accounts": accounts_data,
            "current_index": current_index,
            "config": config_dict,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountPool":
        """Deserialize pool from dictionary."""
        config = PoolConfig.from_dict(data.get("config", {}))
        pool = cls(config=config)

        pool._migration_state = data.get("migration_state", "complete")
        pool._checksum = data.get("checksum")
        pool.current_index = data.get("current_index", 0)

        for acc_data in data.get("accounts", []):
            account = Account.from_dict(acc_data)
            pool.accounts.append(account)

        return pool


# ==============================================================================
# Pool Storage (with migration)
# ==============================================================================

class PoolStorage:
    """
    Handles persistent storage of the account pool.

    Features:
    - Atomic writes with backup
    - Checksum verification
    - Migration from v1 format
    - Multi-process race condition detection (via mtime tracking)
    """

    AUTH_FILENAME = "auth.json"
    BACKUP_SUFFIX = ".v1.bak"

    def __init__(self, home_dir: Optional[str] = None):
        self.home_dir = home_dir or self._get_default_home()
        self.auth_path = Path(self.home_dir) / self.AUTH_FILENAME
        self.backup_path = Path(str(self.auth_path) + self.BACKUP_SUFFIX)
        self._last_mtime: Optional[float] = None
        self._last_checksum: Optional[str] = None

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

        Also tracks file mtime for race condition detection.
        """
        if not self.auth_path.exists():
            return AccountPool()

        # Track file modification time
        self._last_mtime = self.auth_path.stat().st_mtime

        try:
            with open(self.auth_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            # Try to recover from backup
            return self._recover_from_backup()

        # Detect format version
        version = data.get("version", "1.0")

        if version == "1.0":
            # Migrate from v1
            return self._migrate_from_v1(data)
        elif version == AccountPool.VERSION:
            # Load v2 format
            pool = self._load_v2(data)
            # Track checksum after successful load
            self._last_checksum = data.get("checksum")
            return pool
        else:
            raise ValueError(f"Unknown auth file version: {version}")

    def save_pool(self, pool: AccountPool) -> Tuple[bool, Optional[AccountPool]]:
        """
        Save the account pool to disk atomically.

        Uses atomic write pattern:
        1. Write to temp file
        2. Rename temp to target

        Detects external modifications via mtime to prevent race conditions.

        Returns:
            Tuple of (success_status, merged_pool_or_none)
            merged_pool is returned when external changes were merged
        """
        # Ensure directory exists
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)

        merged_pool: Optional[AccountPool] = None

        # Check for external modifications (race condition detection)
        if self._has_external_modification():
            # Merge with external changes before saving
            merged_pool = self._merge_with_external_changes(pool)
            pool = merged_pool

        # Prepare data
        data = pool.to_dict()

        # Atomic write
        tmp_path = None
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

            # Update tracking after successful save
            self._last_mtime = self.auth_path.stat().st_mtime
            self._last_checksum = data.get("checksum")

            return True, merged_pool

        except Exception:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
            raise

    def _has_external_modification(self) -> bool:
        """
        Check if the auth file was modified by another process.

        Returns:
            True if file was modified externally
        """
        if not self.auth_path.exists():
            return False

        current_mtime = self.auth_path.stat().st_mtime

        # First time loading or file doesn't exist yet
        if self._last_mtime is None:
            return False

        # Check if mtime changed
        if current_mtime != self._last_mtime:
            return True

        # Also verify checksum for extra safety
        if self._last_checksum:
            try:
                with open(self.auth_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                current_checksum = data.get("checksum")
                if current_checksum != self._last_checksum:
                    return True
            except Exception:
                # Can't read file, assume modified
                return True

        return False

    def _merge_with_external_changes(self, current_pool: AccountPool) -> AccountPool:
        """
        Merge current pool with externally modified data.

        Field-level merge strategy for accounts in both:
        - Keep LOCAL: alias, priority (user-configured, may have been changed)
        - Take EXTERNAL: usage, diagnostics, status, cooldown_until, health_cache (runtime state)
        - Take EXTERNAL: tokens (may have been refreshed by another process)

        For new accounts:
        - From external: add (may have been added by CLI)
        - From current only: add (new account not yet saved)

        Returns:
            Merged pool
        """
        try:
            external_pool = self.load_pool()

            with current_pool._lock:
                current_accounts = {acc.id: acc.to_dict() for acc in current_pool.accounts}

            with external_pool._lock:
                external_accounts = {acc.id: acc.to_dict() for acc in external_pool.accounts}

            # Merge accounts
            merged_accounts = []
            all_ids = set(current_accounts.keys()) | set(external_accounts.keys())

            for account_id in all_ids:
                if account_id in current_accounts and account_id in external_accounts:
                    # Both exist: field-level merge
                    current = current_accounts[account_id]
                    external = external_accounts[account_id]

                    # Start with external (has runtime state)
                    merged = dict(external)

                    # Preserve local user-configured fields
                    merged["alias"] = current.get("alias", merged.get("alias"))
                    merged["priority"] = current.get("priority", merged.get("priority"))

                    # Reconstruct account from merged dict
                    merged_accounts.append(Account.from_dict(merged))

                elif account_id in current_accounts:
                    # Only in current: new local account
                    merged_accounts.append(Account.from_dict(current_accounts[account_id]))
                else:
                    # Only in external: new external account
                    merged_accounts.append(Account.from_dict(external_accounts[account_id]))

            # Create merged pool with current config
            merged_pool = AccountPool(config=current_pool.config)
            merged_pool.accounts = merged_accounts
            merged_pool._migration_state = current_pool._migration_state

            return merged_pool

        except Exception:
            # If merge fails, proceed with current pool (best effort)
            return current_pool

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

        return AccountPool.from_dict(data)

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


# ==============================================================================
# Pool Service (Singleton)
# ==============================================================================

_pool_service: Optional["PoolService"] = None


def get_pool_service() -> "PoolService":
    """Get the singleton pool service instance."""
    global _pool_service
    if _pool_service is None:
        _pool_service = PoolService()
    return _pool_service


def reset_pool_service() -> None:
    """Reset the singleton pool service. For testing only."""
    global _pool_service
    _pool_service = None


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

    def reload_pool(self) -> AccountPool:
        """
        Force reload the pool from disk.

        Use this after CLI modifies the pool to sync with server's in-memory state.
        """
        self._pool = self.storage.load_pool()
        return self._pool

    def _save(self) -> bool:
        """Save the pool and return success status. Updates in-memory pool if merged."""
        result, merged_pool = self.storage.save_pool(self.pool)
        if merged_pool is not None:
            # Update in-memory pool with merged data to preserve external changes
            self._pool = merged_pool
        return result

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

        # TODO: Ensure tokens are fresh
        # self._ensure_fresh_tokens(account)

        return (
            account.tokens.access_token,
            account.tokens.account_id,
            account.id,
        )

    def record_request_success(
        self,
        internal_account_id: str,
        usage: Optional[UsageInfo] = None,
    ) -> None:
        """Record a successful request and update usage info."""
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

    # ==================== Account Management ====================

    def add_account_from_oauth(
        self,
        id_token: str,
        access_token: str,
        refresh_token: str,
        alias: Optional[str] = None,
        replace_existing: bool = False,
    ) -> Account:
        """
        Add a new account from OAuth callback.

        Returns:
            The created account

        Raises:
            ValueError: If account already exists and replace_existing=False
        """
        from .utils import parse_jwt_claims

        # Extract account info from JWT
        claims = parse_jwt_claims(id_token) or {}
        auth_claims = claims.get("https://api.openai.com/auth", {})
        account_id = auth_claims.get("chatgpt_account_id")

        if not account_id:
            raise ValueError("Could not extract account_id from id_token")

        # Check for duplicate
        existing = self.pool.get_account_by_id(account_id)
        if existing:
            if not replace_existing:
                raise ValueError(f"Account {account_id} already exists in pool")
            # Remove the previous record before inserting the refreshed tokens.
            self.pool.remove_account(account_id)

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
        """Set a new alias for an account. Thread-safe."""
        with self.pool._lock:
            account = self.pool.get_account_by_id(account_id)
            if not account:
                return False
            account.alias = alias
        self._save()
        return True

    def set_account_priority(self, account_id: str, priority: int) -> bool:
        """Set priority for an account (1=highest, 10=lowest). Thread-safe."""
        if not 1 <= priority <= 10:
            raise ValueError("Priority must be between 1 and 10")

        with self.pool._lock:
            account = self.pool.get_account_by_id(account_id)
            if not account:
                return False
            account.priority = priority
        self._save()
        return True

    def update_account_tokens(
        self,
        account_id: str,
        id_token: str,
        access_token: str,
        refresh_token: str,
    ) -> bool:
        """
        Update tokens for an existing account without losing metadata.

        Preserves: alias, priority, status, usage, diagnostics, cooldown state.
        Thread-safe: acquires pool lock for the entire update.

        Returns:
            True if updated, False if account not found
        """
        with self.pool._lock:
            account = self.pool.get_account_by_id(account_id)
            if not account:
                return False

            account.tokens.id_token = id_token
            account.tokens.access_token = access_token
            account.tokens.refresh_token = refresh_token
            account.diagnostics.last_refresh_at = datetime.now(timezone.utc)

        self._save()
        return True

    # ==================== Status & Query ====================

    def get_pool_status(self) -> Dict[str, Any]:
        """Get the full pool status for API/CLI."""
        return self.pool.get_pool_status()

    def get_account_info(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed info for a single account."""
        return self.pool.get_account_status(account_id)

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Get a summary list of all accounts."""
        summaries = self.pool.list_account_statuses()
        return [
            {
                "id": acc.get("id"),
                "alias": acc.get("alias"),
                "status": acc.get("status"),
                "priority": acc.get("priority"),
                "usage_percent": acc.get("usage_percent"),
            }
            for acc in summaries
        ]


# ==============================================================================
# Helper Functions
# ==============================================================================

def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO8601 string."""
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO8601 string to datetime."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


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