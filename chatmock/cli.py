from __future__ import annotations

import argparse
import json
import errno
import os
import sys
import webbrowser

from .app import create_app
from .config import CLIENT_ID_DEFAULT
from .oauth import OAuthHTTPServer, OAuthHandler, REQUIRED_PORT, URL_BASE
from .utils import eprint, get_home_dir, load_chatgpt_tokens, parse_jwt_claims, read_auth_file


def cmd_login(no_browser: bool, verbose: bool) -> int:
    home_dir = get_home_dir()
    client_id = CLIENT_ID_DEFAULT
    if not client_id:
        eprint("ERROR: No OAuth client id configured. Set CHATGPT_LOCAL_CLIENT_ID.")
        return 1

    try:
        httpd = OAuthHTTPServer(("127.0.0.1", REQUIRED_PORT), OAuthHandler, home_dir=home_dir, client_id=client_id, verbose=verbose)
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
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            eprint("\nKeyboard interrupt received, exiting.")
        return httpd.exit_code


def cmd_serve(
    host: str,
    port: int,
    verbose: bool,
    reasoning_effort: str,
    reasoning_summary: str,
    reasoning_compat: str,
    debug_model: str | None,
) -> int:
    app = create_app(
        verbose=verbose,
        reasoning_effort=reasoning_effort,
        reasoning_summary=reasoning_summary,
        reasoning_compat=reasoning_compat,
        debug_model=debug_model,
    )

    app.run(host=host, debug=False, use_reloader=False, port=port, threaded=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="ChatGPT Local: login & OpenAI-compatible proxy")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Authorize with ChatGPT and store tokens")
    p_login.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    p_login.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    p_serve = sub.add_parser("serve", help="Run local OpenAI-compatible server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    p_serve.add_argument(
        "--debug-model",
        dest="debug_model",
        default=os.getenv("CHATGPT_LOCAL_DEBUG_MODEL"),
        help="Forcibly override requested 'model' with this value",
    )
    p_serve.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "none"],
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

    p_info = sub.add_parser("info", help="Print current stored tokens and derived account id")
    p_info.add_argument("--json", action="store_true", help="Output raw auth.json contents")

    args = parser.parse_args()

    if args.command == "login":
        sys.exit(cmd_login(no_browser=args.no_browser, verbose=args.verbose))
    elif args.command == "serve":
        sys.exit(
            cmd_serve(
                host=args.host,
                port=args.port,
                verbose=args.verbose,
                reasoning_effort=args.reasoning_effort,
                reasoning_summary=args.reasoning_summary,
                reasoning_compat=args.reasoning_compat,
                debug_model=args.debug_model,
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
        sys.exit(0)
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
