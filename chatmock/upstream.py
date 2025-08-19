from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

import requests
from flask import Response, jsonify, make_response

from .config import CHATGPT_RESPONSES_URL
from .http import build_cors_headers
from .utils import get_effective_chatgpt_auth


def normalize_model_name(name: str | None, debug_model: str | None = None) -> str:
    if isinstance(debug_model, str) and debug_model.strip():
        return debug_model.strip()
    if not isinstance(name, str) or not name.strip():
        return "gpt-5"
    base = name.split(":", 1)[0].strip()
    mapping = {
        "gpt5": "gpt-5",
        "gpt-5-latest": "gpt-5",
        "gpt-5": "gpt-5",
        "codex": "codex-mini-latest",
        "codex-mini": "codex-mini-latest",
        "codex-mini-latest": "codex-mini-latest",
    }
    return mapping.get(base, base)


def start_upstream_request(
    model: str,
    input_items: List[Dict[str, Any]],
    *,
    instructions: str | None = None,
    tools: List[Dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
    parallel_tool_calls: bool = False,
    reasoning_param: Dict[str, Any] | None = None,
):
    access_token, account_id = get_effective_chatgpt_auth()
    if not access_token or not account_id:
        resp = make_response(
            jsonify(
                {
                    "error": {
                        "message": "Missing ChatGPT credentials. Run 'python3 chatmock.py login' first.",
                    }
                }
            ),
            401,
        )
        for k, v in build_cors_headers().items():
            resp.headers.setdefault(k, v)
        return None, resp

    include: List[str] = []
    if isinstance(reasoning_param, dict) and reasoning_param.get("effort") != "none":
        include.append("reasoning.encrypted_content")

    responses_payload = {
        "model": model,
        "instructions": instructions if isinstance(instructions, str) and instructions.strip() else instructions,
        "input": input_items,
        "tools": tools or [],
        "tool_choice": tool_choice if tool_choice in ("auto", "none") or isinstance(tool_choice, dict) else "auto",
        "parallel_tool_calls": bool(parallel_tool_calls),
        "store": False,
        "stream": True,
        "include": include,
    }

    if reasoning_param is not None:
        responses_payload["reasoning"] = reasoning_param

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
    }

    try:
        upstream = requests.post(
            CHATGPT_RESPONSES_URL,
            headers=headers,
            json=responses_payload,
            stream=True,
            timeout=600,
        )
    except requests.RequestException as e:
        resp = make_response(jsonify({"error": {"message": f"Upstream ChatGPT request failed: {e}"}}), 502)
        for k, v in build_cors_headers().items():
            resp.headers.setdefault(k, v)
        return None, resp
    return upstream, None

