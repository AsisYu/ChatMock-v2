from __future__ import annotations

import errno
import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime

from .app import create_app
from .config import CLIENT_ID_DEFAULT
from .limits import RateLimitWindow, compute_reset_at, load_rate_limit_snapshot
from .oauth import OAuthHTTPServer, OAuthHandler, REQUIRED_PORT, URL_BASE
from .utils import eprint, get_home_dir, load_chatgpt_tokens, parse_jwt_claims, read_auth_file
from .pool_manager import get_pool_service, AccountStatus


_STATUS_LIMIT_BAR_SEGMENTS = 30
_STATUS_LIMIT_BAR_FILLED = "█"
_STATUS_LIMIT_BAR_EMPTY = "░"
_STATUS_LIMIT_BAR_PARTIAL = "▓"


def _clamp_percent(value: float) -> float:
    try:
        percent = float(value)
    except Exception:
        return 0.0
    if percent != percent:
        return 0.0
    if percent < 0.0:
        return 0.0
    if percent > 100.0:
        return 100.0
    return percent


def _render_progress_bar(percent_used: float) -> str:
    ratio = max(0.0, min(1.0, percent_used / 100.0))
    filled_exact = ratio * _STATUS_LIMIT_BAR_SEGMENTS
    filled = int(filled_exact)
    partial = filled_exact - filled
    
    has_partial = partial > 0.5
    if has_partial:
        filled += 1
    
    filled = max(0, min(_STATUS_LIMIT_BAR_SEGMENTS, filled))
    empty = _STATUS_LIMIT_BAR_SEGMENTS - filled
    
    if has_partial and filled > 0:
        bar = _STATUS_LIMIT_BAR_FILLED * (filled - 1) + _STATUS_LIMIT_BAR_PARTIAL + _STATUS_LIMIT_BAR_EMPTY * empty
    else:
        bar = _STATUS_LIMIT_BAR_FILLED * filled + _STATUS_LIMIT_BAR_EMPTY * empty
    
    return f"[{bar}]"


def _get_usage_color(percent_used: float) -> str:
    if percent_used >= 90:
        return "\033[91m" 
    elif percent_used >= 75:
        return "\033[93m"  
    elif percent_used >= 50:
        return "\033[94m"  
    else:
        return "\033[92m" 


def _reset_color() -> str:
    """ANSI reset color code"""
    return "\033[0m"


def _format_window_duration(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    try:
        total = int(minutes)
    except Exception:
        return None
    if total <= 0:
        return None
    minutes = total
    weeks, remainder = divmod(minutes, 7 * 24 * 60)
    days, remainder = divmod(remainder, 24 * 60)
    hours, remainder = divmod(remainder, 60)
    parts = []
    if weeks:
        parts.append(f"{weeks} week" + ("s" if weeks != 1 else ""))
    if days:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if remainder:
        parts.append(f"{remainder} minute" + ("s" if remainder != 1 else ""))
    if not parts:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts)


def _format_reset_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    try:
        value = int(seconds)
    except Exception:
        return None
    if value < 0:
        value = 0
    days, remainder = divmod(value, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, remainder = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts and remainder:
        parts.append("under 1m")
    if not parts:
        parts.append("0m")
    return " ".join(parts)


def _format_local_datetime(dt: datetime) -> str:
    local = dt.astimezone()
    tz_name = local.tzname() or "local"
    return f"{local.strftime('%b %d, %Y %H:%M')} {tz_name}"


def _print_usage_limits_block() -> None:
    stored = load_rate_limit_snapshot()
    
    print("📊 Usage Limits")
    
    if stored is None:
        print("  No usage data available yet. Send a request through ChatMock first.")
        print()
        return

    update_time = _format_local_datetime(stored.captured_at)
    print(f"Last updated: {update_time}")
    print()

    windows: list[tuple[str, str, RateLimitWindow]] = []
    if stored.snapshot.primary is not None:
        windows.append(("⚡", "5 hour limit", stored.snapshot.primary))
    if stored.snapshot.secondary is not None:
        windows.append(("📅", "Weekly limit", stored.snapshot.secondary))

    if not windows:
        print("  Usage data was captured but no limit windows were provided.")
        print()
        return

    for i, (icon_label, desc, window) in enumerate(windows):
        if i > 0:
            print()
        
        percent_used = _clamp_percent(window.used_percent)
        remaining = max(0.0, 100.0 - percent_used)
        color = _get_usage_color(percent_used)
        reset = _reset_color()
        
        progress = _render_progress_bar(percent_used)
        usage_text = f"{percent_used:5.1f}% used"
        remaining_text = f"{remaining:5.1f}% left"
        
        print(f"{icon_label} {desc}")
        print(f"{color}{progress}{reset} {color}{usage_text}{reset} | {remaining_text}")
        
        reset_in = _format_reset_duration(window.resets_in_seconds)
        reset_at = compute_reset_at(stored.captured_at, window)
        
        if reset_in and reset_at:
            reset_at_str = _format_local_datetime(reset_at)
            print(f"    ⏳ Resets in: {reset_in} at {reset_at_str}")
        elif reset_in:
            print(f"    ⏳ Resets in: {reset_in}")
        elif reset_at:
            reset_at_str = _format_local_datetime(reset_at)
            print(f"    ⏳ Resets at: {reset_at_str}")

    print()

def cmd_login(no_browser: bool, verbose: bool) -> int:
    home_dir = get_home_dir()
    client_id = CLIENT_ID_DEFAULT
    if not client_id:
        eprint("ERROR: No OAuth client id configured. Set CHATGPT_LOCAL_CLIENT_ID.")
        return 1

    # Preload pool service so we can merge new tokens into the in-memory pool snapshot.
    get_pool_service()

    try:
        bind_host = os.getenv("CHATGPT_LOCAL_LOGIN_BIND", "127.0.0.1")
        httpd = OAuthHTTPServer((bind_host, REQUIRED_PORT), OAuthHandler, home_dir=home_dir, client_id=client_id, verbose=verbose)
    except OSError as e:
        eprint(f"ERROR: {e}")
        if e.errno == errno.EADDRINUSE:
            return 13
        return 1

    auth_url = httpd.auth_url()
    with httpd:
        eprint(f"Starting local login server on {URL_BASE}")
        if not no_browser:
            try:
                webbrowser.open(auth_url, new=1, autoraise=True)
            except Exception as e:
                eprint(f"Failed to open browser: {e}")
        eprint(f"If your browser did not open, navigate to:\n{auth_url}")

        def _stdin_paste_worker() -> None:
            try:
                eprint(
                    "If the browser can't reach this machine, paste the full redirect URL here and press Enter (or leave blank to keep waiting):"
                )
                line = sys.stdin.readline().strip()
                if not line:
                    return
                try:
                    from urllib.parse import urlparse, parse_qs

                    parsed = urlparse(line)
                    params = parse_qs(parsed.query)
                    code = (params.get("code") or [None])[0]
                    state = (params.get("state") or [None])[0]
                    if not code:
                        eprint("Input did not contain an auth code. Ignoring.")
                        return
                    if state and state != httpd.state:
                        eprint("State mismatch. Ignoring pasted URL for safety.")
                        return
                    eprint("Received redirect URL. Completing login without callback…")
                    bundle, _ = httpd.exchange_code(code)
                    if httpd.persist_auth(bundle):
                        httpd.exit_code = 0
                        eprint("Login successful. Tokens saved.")
                    else:
                        eprint("ERROR: Unable to persist auth file.")
                    httpd.shutdown()
                except Exception as exc:
                    eprint(f"Failed to process pasted redirect URL: {exc}")
            except Exception:
                pass

        try:
            import threading

            threading.Thread(target=_stdin_paste_worker, daemon=True).start()
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            eprint("\nKeyboard interrupt received, exiting.")
        exit_code = httpd.exit_code

    if exit_code == 0:
        _sync_auth_file_into_pool()
    return exit_code


def _sync_auth_file_into_pool() -> None:
    """Import the latest login tokens into the account pool."""
    auth = read_auth_file()
    if not isinstance(auth, dict):
        return
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return

    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not (isinstance(id_token, str) and isinstance(access_token, str) and isinstance(refresh_token, str)):
        return

    try:
        account = get_pool_service().add_account_from_oauth(
            id_token=id_token,
            access_token=access_token,
            refresh_token=refresh_token,
            replace_existing=True,
        )
        eprint(f"[pool] Account '{account.alias}' ({account.id}) synced successfully.")
    except Exception as exc:
        eprint(f"WARNING: unable to sync login credentials into pool: {exc}")


def cmd_serve(
    host: str,
    port: int,
    verbose: bool,
    verbose_obfuscation: bool,
    reasoning_effort: str,
    reasoning_summary: str,
    reasoning_compat: str,
    fast_mode: bool,
    debug_model: str | None,
    expose_reasoning_models: bool,
    default_web_search: bool,
) -> int:
    app = create_app(
        verbose=verbose,
        verbose_obfuscation=verbose_obfuscation,
        reasoning_effort=reasoning_effort,
        reasoning_summary=reasoning_summary,
        reasoning_compat=reasoning_compat,
        fast_mode=fast_mode,
        debug_model=debug_model,
        expose_reasoning_models=expose_reasoning_models,
        default_web_search=default_web_search,
    )

    app.run(host=host, use_reloader=False, port=port, threaded=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="ChatMock: login & OpenAI-compatible proxy")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Authorize with ChatGPT and store tokens")
    p_login.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    p_login.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    p_serve = sub.add_parser("serve", help="Run local OpenAI-compatible server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    p_serve.add_argument(
        "--verbose-obfuscation",
        action="store_true",
        help="Also dump raw SSE/obfuscation events (in addition to --verbose request/response logs).",
    )
    p_serve.add_argument(
        "--debug-model",
        dest="debug_model",
        default=os.getenv("CHATGPT_LOCAL_DEBUG_MODEL"),
        help="Forcibly override requested 'model' with this value",
    )
    p_serve.add_argument(
        "--fast-mode",
        action=argparse.BooleanOptionalAction,
        default=(os.getenv("CHATGPT_LOCAL_FAST_MODE") or "").strip().lower() in ("1", "true", "yes", "on"),
        help="Enable GPT fast mode by default for supported models; request-level overrides still take precedence.",
    )
    p_serve.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=os.getenv("CHATGPT_LOCAL_REASONING_EFFORT", "medium").lower(),
        help="Reasoning effort level for Responses API (default: medium)",
    )
    p_serve.add_argument(
        "--reasoning-summary",
        choices=["auto", "concise", "detailed", "none"],
        default=os.getenv("CHATGPT_LOCAL_REASONING_SUMMARY", "auto").lower(),
        help="Reasoning summary verbosity (default: auto)",
    )
    p_serve.add_argument(
        "--reasoning-compat",
        choices=["legacy", "o3", "think-tags", "current"],
        default=os.getenv("CHATGPT_LOCAL_REASONING_COMPAT", "think-tags").lower(),
        help=(
            "Compatibility mode for exposing reasoning to clients (legacy|o3|think-tags). "
            "'current' is accepted as an alias for 'legacy'"
        ),
    )
    p_serve.add_argument(
        "--expose-reasoning-models",
        action="store_true",
        default=(os.getenv("CHATGPT_LOCAL_EXPOSE_REASONING_MODELS") or "").strip().lower() in ("1", "true", "yes", "on"),
        help=(
            "Expose GPT-5 family reasoning effort variants (none|minimal|low|medium|high|xhigh where supported) "
            "as separate models from /v1/models. This allows choosing effort via model selection in compatible UIs."
        ),
    )
    p_serve.add_argument(
        "--enable-web-search",
        action=argparse.BooleanOptionalAction,
        default=(os.getenv("CHATGPT_LOCAL_ENABLE_WEB_SEARCH") or "").strip().lower() in ("1", "true", "yes", "on"),
        help=(
            "Enable default web_search tool when a request omits responses_tools (off by default). "
            "Also configurable via CHATGPT_LOCAL_ENABLE_WEB_SEARCH."
        ),
    )

    p_info = sub.add_parser("info", help="Print current stored tokens and derived account id")
    p_info.add_argument("--json", action="store_true", help="Output raw auth.json contents")

    # Account subcommands
    p_account = sub.add_parser("account", help="Manage accounts in the pool")
    account_sub = p_account.add_subparsers(dest="account_command", required=True)

    p_account_list = account_sub.add_parser("list", help="List all accounts")
    p_account_list.add_argument("--json", action="store_true", help="Output as JSON")

    p_account_show = account_sub.add_parser("show", help="Show account details")
    p_account_show.add_argument("account_id", help="Account ID to show")

    p_account_remove = account_sub.add_parser("remove", help="Remove an account")
    p_account_remove.add_argument("account_id", help="Account ID to remove")
    p_account_remove.add_argument("--force", action="store_true", help="Skip confirmation")

    p_account_rename = account_sub.add_parser("rename", help="Rename account alias")
    p_account_rename.add_argument("account_id", help="Account ID")
    p_account_rename.add_argument("alias", help="New alias")

    p_account_priority = account_sub.add_parser("priority", help="Set account priority (1=highest, 10=lowest)")
    p_account_priority.add_argument("account_id", help="Account ID")
    p_account_priority.add_argument("priority", type=int, help="Priority (1-10)")

    # Pool subcommands
    p_pool = sub.add_parser("pool", help="Manage the account pool")
    pool_sub = p_pool.add_subparsers(dest="pool_command", required=True)

    p_pool_status = pool_sub.add_parser("status", help="Show pool status")
    p_pool_status.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command == "login":
        sys.exit(cmd_login(no_browser=args.no_browser, verbose=args.verbose))
    elif args.command == "serve":
        sys.exit(
            cmd_serve(
                host=args.host,
                port=args.port,
                verbose=args.verbose,
                verbose_obfuscation=args.verbose_obfuscation,
                reasoning_effort=args.reasoning_effort,
                reasoning_summary=args.reasoning_summary,
                reasoning_compat=args.reasoning_compat,
                fast_mode=args.fast_mode,
                debug_model=args.debug_model,
                expose_reasoning_models=args.expose_reasoning_models,
                default_web_search=args.enable_web_search,
            )
        )
    elif args.command == "info":
        auth = read_auth_file()
        if getattr(args, "json", False):
            print(json.dumps(auth or {}, indent=2))
            sys.exit(0)
        access_token, account_id, id_token = load_chatgpt_tokens()
        if not access_token or not id_token:
            print("👤 Account")
            print("  • Not signed in")
            print("  • Run: python3 chatmock.py login")
            print("")
            _print_usage_limits_block()
            sys.exit(0)

        id_claims = parse_jwt_claims(id_token) or {}
        access_claims = parse_jwt_claims(access_token) or {}

        email = id_claims.get("email") or id_claims.get("preferred_username") or "<unknown>"
        plan_raw = (access_claims.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type") or "unknown"
        plan_map = {
            "plus": "Plus",
            "pro": "Pro",
            "free": "Free",
            "team": "Team",
            "enterprise": "Enterprise",
        }
        plan = plan_map.get(str(plan_raw).lower(), str(plan_raw).title() if isinstance(plan_raw, str) else "Unknown")

        print("👤 Account")
        print("  • Signed in with ChatGPT")
        print(f"  • Login: {email}")
        print(f"  • Plan: {plan}")
        if account_id:
            print(f"  • Account ID: {account_id}")
        print("")
        _print_usage_limits_block()
        sys.exit(0)
    elif args.command == "account":
        _handle_account_command(args)
    elif args.command == "pool":
        _handle_pool_command(args)
    else:
        parser.error("Unknown command")


def _handle_account_command(args) -> None:
    """Handle account subcommands."""
    pool_service = get_pool_service()

    if args.account_command == "list":
        accounts = pool_service.list_accounts()
        if getattr(args, "json", False):
            print(json.dumps(accounts, indent=2))
            return

        if not accounts:
            print("No accounts in pool. Run 'chatmock login' to add one.")
            return

        print("📋 Accounts in Pool\n")
        print(f"{'ID':<20} {'Alias':<20} {'Status':<10} {'Priority':<8} {'Usage':<8}")
        print("-" * 70)
        for acc in accounts:
            status = acc.get("status", "unknown")
            status_color = {
                "active": "\033[92m",
                "ready": "\033[92m",
                "cooldown": "\033[93m",
                "error": "\033[91m",
            }.get(status, "")
            reset = "\033[0m"
            usage = acc.get("usage_percent", 0)
            print(f"{acc['id'][:18]:<20} {acc['alias']:<20} {status_color}{status:<10}{reset} {acc.get('priority', 5):<8} {usage:.1f}%")

    elif args.account_command == "show":
        account = pool_service.get_account_info(args.account_id)
        if not account:
            print(f"Account '{args.account_id}' not found.")
            sys.exit(1)

        print(f"📋 Account: {account.get('alias', args.account_id)}\n")
        print(f"  ID:              {account.get('id')}")
        print(f"  Alias:           {account.get('alias')}")
        print(f"  Status:          {account.get('status')}")
        print(f"  Priority:        {account.get('priority')}")
        print(f"  Usage:           {account.get('usage_percent', 0):.1f}%")
        print(f"  Remaining:       {account.get('remaining_percent', 100):.1f}%")

        if account.get("cooldown_remaining"):
            print(f"  Cooldown:        {account.get('cooldown_remaining')}")

        if account.get("last_error"):
            print(f"  Last Error:      {account.get('last_error')}")

    elif args.account_command == "remove":
        account = pool_service.get_account_info(args.account_id)
        if not account:
            print(f"Account '{args.account_id}' not found.")
            sys.exit(1)

        if not args.force:
            alias = account.get("alias", args.account_id)
            confirm = input(f"Remove account '{alias}'? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return

        if pool_service.remove_account(args.account_id):
            print(f"Account '{args.account_id}' removed from pool.")
        else:
            print(f"Failed to remove account '{args.account_id}'.")
            sys.exit(1)

    elif args.account_command == "rename":
        if pool_service.set_account_alias(args.account_id, args.alias):
            print(f"Account '{args.account_id}' renamed to '{args.alias}'.")
        else:
            print(f"Account '{args.account_id}' not found.")
            sys.exit(1)

    elif args.account_command == "priority":
        if not 1 <= args.priority <= 10:
            print("Priority must be between 1 and 10.")
            sys.exit(1)

        if pool_service.set_account_priority(args.account_id, args.priority):
            print(f"Account '{args.account_id}' priority set to {args.priority}.")
        else:
            print(f"Account '{args.account_id}' not found.")
            sys.exit(1)


def _handle_pool_command(args) -> None:
    """Handle pool subcommands."""
    pool_service = get_pool_service()

    if args.pool_command == "status":
        status = pool_service.get_pool_status()

        if getattr(args, "json", False):
            print(json.dumps(status, indent=2))
            return

        print("📊 Pool Status\n")
        print(f"  Total Accounts:     {status.get('total_accounts', 0)}")
        print(f"  Active:             {status.get('active_accounts', 0)}")
        print(f"  Cooldown:           {status.get('cooldown_accounts', 0)}")
        print(f"  Error:              {status.get('error_accounts', 0)}")

        accounts = status.get("accounts", [])
        if accounts:
            print("\n📋 Accounts\n")
            print(f"{'Alias':<20} {'Status':<10} {'Priority':<8} {'Usage':<8}")
            print("-" * 50)
            for acc in accounts:
                status_str = acc.get("status", "unknown")
                usage = acc.get("usage_percent", 0)
                print(f"{acc.get('alias', acc.get('id', 'unknown')):<20} {status_str:<10} {acc.get('priority', 5):<8} {usage:.1f}%")


if __name__ == "__main__":
    main()
