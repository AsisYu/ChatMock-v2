"""
Pool Management API Routes for ChatMock.

Provides REST API endpoints for managing the account pool.
Security: These endpoints require either:
- Direct localhost access (no proxy headers, remote_addr is loopback)
- Valid API token via Authorization header (for reverse proxy setups)

Configure API token via CHATMOCK_POOL_API_TOKEN environment variable.
IMPORTANT: If using a reverse proxy (nginx, traefik, etc.), you MUST set
CHATMOCK_POOL_API_TOKEN to prevent unauthorized access.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Mapping
from flask import Blueprint, jsonify, request

from . import config
from .http import build_cors_headers
from .pool_manager import (
    get_pool_service,
    NoAvailableAccountError,
    AccountNotFoundError,
)
from .utils import eprint


pool_bp = Blueprint("pool", __name__, url_prefix="/v1/pool")

# API token for reverse proxy security (optional but recommended)
_POOL_API_TOKEN = os.environ.get("CHATMOCK_POOL_API_TOKEN")


def _get_main_api_token() -> str | None:
    """Get the main API token dynamically from config or environment."""
    token = getattr(config, "CHATMOCK_API_TOKEN", None)
    if token:
        return token
    env_token = os.environ.get("CHATMOCK_API_TOKEN")
    if env_token:
        config.CHATMOCK_API_TOKEN = env_token
        return env_token
    return None


def is_main_api_token_configured() -> bool:
    """Check if main API token authentication is enabled."""
    return bool(_get_main_api_token())


def _is_localhost_request() -> bool:
    """Check if request originates from localhost."""
    client_ip = request.remote_addr
    if client_ip is None:
        return False
    # Check common localhost addresses
    try:
        ip = ipaddress.ip_address(client_ip)
        return ip.is_loopback
    except ValueError:
        # Invalid IP, reject
        return False


def _has_proxy_headers() -> bool:
    """Check if request came through a proxy (has forwarding headers)."""
    proxy_headers = [
        "X-Forwarded-For",
        "X-Real-IP",
        "X-Forwarded-Host",
        "Forwarded",
    ]
    for header in proxy_headers:
        if request.headers.get(header):
            return True
    return False


def _has_valid_api_token() -> bool:
    """Check if request has valid API token in Authorization header."""
    if not _POOL_API_TOKEN:
        return False

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:]  # Remove "Bearer " prefix
    return hmac.compare_digest(token, _POOL_API_TOKEN)


def has_valid_main_api_token(headers: Mapping[str, str] | None = None) -> bool:
    """Check if request has valid main API token in Authorization header.

    Uses constant-time comparison to prevent timing attacks.
    Fetches token dynamically to support CLI-provided tokens.
    """
    token_expected = _get_main_api_token()
    if not token_expected:
        return False

    header_source = headers if headers is not None else request.headers
    auth_header = header_source.get("Authorization", "")
    if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
        return False

    provided = auth_header[7:]  # Remove "Bearer " prefix
    return hmac.compare_digest(provided, token_expected)


def require_api_token(f):
    """
    Decorator for optional API token authentication on main API endpoints.

    Security logic:
    1. If CHATMOCK_API_TOKEN is NOT set: allow all requests (backward compatible)
    2. If CHATMOCK_API_TOKEN IS set: require valid Bearer token
    3. If proxy headers detected without token configured: warn but allow

    This ensures backward compatibility while enabling authentication when needed.
    """
    def wrapped(*args, **kwargs):
        # Case 1: Token not configured - allow all (backward compatible)
        if not is_main_api_token_configured():
            # Security warning for proxy scenarios
            if _has_proxy_headers():
                eprint(
                    "WARNING: Server appears to be behind a reverse proxy but "
                    "CHATMOCK_API_TOKEN is not set. Consider setting it for security."
                )
            return f(*args, **kwargs)

        # Case 2: Token configured - require valid authentication
        if has_valid_main_api_token():
            return f(*args, **kwargs)

        # Case 3: Invalid or missing token
        response = jsonify({
            "error": {
                "type": "UnauthorizedError",
                "message": "Invalid or missing API token"
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 401

    wrapped.__name__ = f.__name__
    return wrapped


def secure_endpoint(f):
    """
    Decorator to secure pool management endpoints.

    Security logic (in order):
    1. If CHATMOCK_POOL_API_TOKEN is set: require valid Bearer token
    2. If request has proxy headers (X-Forwarded-For, etc.): require valid token
       (prevents bypass when behind reverse proxy)
    3. Otherwise: allow localhost access only (direct usage)

    This ensures that:
    - Direct localhost access works without configuration
    - Reverse proxy setups require token configuration
    - Proxy headers are detected and require authentication
    """
    def wrapped(*args, **kwargs):
        # Case 1: API token is explicitly configured - require it
        if _POOL_API_TOKEN:
            if _has_valid_api_token():
                return f(*args, **kwargs)
            response = jsonify({
                "success": False,
                "error": {
                    "type": "ForbiddenError",
                    "message": "Pool management endpoints require valid API token"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 403

        # Case 2: Request came through a proxy - require token
        # This prevents bypass when server is behind nginx/traefik
        if _has_proxy_headers():
            response = jsonify({
                "success": False,
                "error": {
                    "type": "ForbiddenError",
                    "message": "Requests through proxy require CHATMOCK_POOL_API_TOKEN to be configured"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 403

        # Case 3: Direct localhost access (no proxy, localhost IP)
        if _is_localhost_request():
            return f(*args, **kwargs)

        # Reject all other requests
        response = jsonify({
            "success": False,
            "error": {
                "type": "ForbiddenError",
                "message": "Pool management endpoints require localhost access or valid API token"
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 403
    wrapped.__name__ = f.__name__
    return wrapped


@pool_bp.route("/status", methods=["GET"])
@secure_endpoint
def get_pool_status():
    """
    Get the status of all accounts in the pool.

    Returns:
        JSON with pool status and account details
    """
    try:
        pool_service = get_pool_service()
        status = pool_service.get_pool_status()

        response = jsonify({
            "success": True,
            **status
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/reload", methods=["POST"])
@secure_endpoint
def reload_pool():
    """
    Force reload the pool from disk.

    Use after CLI modifications to sync server's in-memory state.
    """
    try:
        pool_service = get_pool_service()
        pool_service.reload_pool()
        status = pool_service.get_pool_status()

        response = jsonify({
            "success": True,
            "message": "Pool reloaded from disk",
            **status
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/accounts", methods=["GET"])
@secure_endpoint
def list_accounts():
    """
    List all accounts in the pool.

    Returns:
        JSON array of accounts
    """
    try:
        pool_service = get_pool_service()
        accounts = pool_service.list_accounts()

        response = jsonify({
            "success": True,
            "accounts": accounts
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/accounts/<account_id>", methods=["GET"])
@secure_endpoint
def get_account(account_id: str):
    """
    Get details for a specific account.

    Args:
        account_id: The account ID

    Returns:
        JSON with account details
    """
    try:
        pool_service = get_pool_service()
        account = pool_service.get_account_info(account_id)

        if not account:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "AccountNotFoundError",
                    "message": f"Account '{account_id}' not found"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 404

        response = jsonify({
            "success": True,
            "account": account
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/accounts/<account_id>", methods=["DELETE"])
@secure_endpoint
def remove_account(account_id: str):
    """
    Remove an account from the pool.

    Args:
        account_id: The account ID to remove

    Returns:
        JSON with success status
    """
    try:
        pool_service = get_pool_service()

        # Get account info before removal for response
        account = pool_service.get_account_info(account_id)
        if not account:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "AccountNotFoundError",
                    "message": f"Account '{account_id}' not found"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 404

        alias = account.get("alias", account_id)
        removed = pool_service.remove_account(account_id)

        if removed:
            response = jsonify({
                "success": True,
                "message": f"Account '{alias}' removed from pool"
            })
        else:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "RemoveFailedError",
                    "message": f"Failed to remove account '{account_id}'"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 500

        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/accounts/<account_id>", methods=["PATCH"])
@secure_endpoint
def update_account(account_id: str):
    """
    Update account settings.

    Args:
        account_id: The account ID to update

    Request Body:
        {
            "alias": "new-alias",  // optional
            "priority": 2          // optional, 1-10
        }

    Returns:
        JSON with updated account info
    """
    try:
        pool_service = get_pool_service()

        # Check account exists
        account = pool_service.get_account_info(account_id)
        if not account:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "AccountNotFoundError",
                    "message": f"Account '{account_id}' not found"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 404

        data = request.get_json() or {}

        # Update alias
        if "alias" in data:
            pool_service.set_account_alias(account_id, data["alias"])

        # Update priority
        if "priority" in data:
            try:
                priority = int(data["priority"])
                if not 1 <= priority <= 10:
                    raise ValueError("Priority must be between 1 and 10")
                pool_service.set_account_priority(account_id, priority)
            except (TypeError, ValueError) as e:
                response = jsonify({
                    "success": False,
                    "error": {
                        "type": "ValidationError",
                        "message": str(e)
                    }
                })
                for k, v in build_cors_headers().items():
                    response.headers.setdefault(k, v)
                return response, 400

        # Get updated account
        updated = pool_service.get_account_info(account_id)

        response = jsonify({
            "success": True,
            "account": updated
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/accounts/<account_id>/refresh", methods=["POST"])
@secure_endpoint
def refresh_account(account_id: str):
    """
    Force refresh tokens for an account.

    Args:
        account_id: The account ID to refresh

    Returns:
        JSON with refresh status
    """
    try:
        pool_service = get_pool_service()

        # Check account exists
        account = pool_service.get_account_info(account_id)
        if not account:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "AccountNotFoundError",
                    "message": f"Account '{account_id}' not found"
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 404

        # Token refresh not yet implemented - return proper 501
        response = jsonify({
            "success": False,
            "error": {
                "type": "NotImplementedError",
                "message": "Token refresh endpoint is not yet implemented"
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 501

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/config", methods=["GET"])
@secure_endpoint
def get_pool_config():
    """
    Get pool configuration.

    Returns:
        JSON with pool config
    """
    try:
        pool_service = get_pool_service()
        config = pool_service.pool.config

        response = jsonify({
            "success": True,
            "config": config.to_dict()
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500


@pool_bp.route("/config", methods=["PATCH"])
@secure_endpoint
def update_pool_config():
    """
    Update pool configuration.

    Request Body:
        {
            "cooldown_threshold": 90.0,
            "default_cooldown_seconds": 1800,
            "max_pool_size": 10
        }

    Returns:
        JSON with updated config
    """
    try:
        pool_service = get_pool_service()
        data = request.get_json() or {}

        config = pool_service.pool.config

        try:
            if "cooldown_threshold" in data:
                threshold = float(data["cooldown_threshold"])
                if not 0 < threshold <= 100:
                    raise ValueError("cooldown_threshold must be between 0 and 100")
                config.cooldown_threshold = threshold

            if "default_cooldown_seconds" in data:
                cooldown_seconds = int(data["default_cooldown_seconds"])
                if cooldown_seconds <= 0:
                    raise ValueError("default_cooldown_seconds must be positive")
                config.default_cooldown_seconds = cooldown_seconds

            if "max_pool_size" in data:
                max_pool_size = data["max_pool_size"]
                if max_pool_size is None:
                    config.max_pool_size = None
                else:
                    value = int(max_pool_size)
                    if value <= 0:
                        raise ValueError("max_pool_size must be positive")
                    config.max_pool_size = value

            if "health_cache_ttl_seconds" in data:
                ttl = int(data["health_cache_ttl_seconds"])
                if ttl <= 0:
                    raise ValueError("health_cache_ttl_seconds must be positive")
                config.health_cache_ttl_seconds = ttl

            if "max_consecutive_failures" in data:
                max_failures = int(data["max_consecutive_failures"])
                if max_failures <= 0:
                    raise ValueError("max_consecutive_failures must be positive")
                config.max_consecutive_failures = max_failures
        except (TypeError, ValueError) as exc:
            response = jsonify({
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": str(exc)
                }
            })
            for k, v in build_cors_headers().items():
                response.headers.setdefault(k, v)
            return response, 400

        # Save
        pool_service._save()

        response = jsonify({
            "success": True,
            "config": config.to_dict()
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response

    except Exception as e:
        response = jsonify({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        })
        for k, v in build_cors_headers().items():
            response.headers.setdefault(k, v)
        return response, 500