"""Baseten managed Model API transport; no hardware, capture, or tool dispatch.

The model is already hosted by Baseten. BASETEN_MODEL is its catalog slug, not a
custom deployment ID. No Truss push or OpenAI service/API key is involved.
"""
from __future__ import annotations

import json
import math
import os
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "moonshotai/Kimi-K3"
INFERENCE_URL = "https://inference.baseten.co/v1"
MANAGEMENT_URL = "https://api.baseten.co/v1"


class BasetenError(RuntimeError):
    """A provider/contract failure. Never a reason to replay a physical action."""


class BasetenRequestError(BasetenError):
    """Infrastructure/access failure, distinct from a model's invalid tool response."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 kind: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind or ("http_error" if status_code is not None else "transport_error")


def load_env_file(path: Path) -> None:
    """Single-line .env values, no shell execution/interpolation or secret output."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            raise ValueError(f"Invalid quoted value in {path.name}; check .env syntax") from None
        value = " ".join(parts)
        if key and value and not os.environ.get(key):
            os.environ[key] = value


def load_env() -> None:
    # Existing nonempty environment > guitar/.env > repository .env.
    load_env_file(ROOT / ".env")
    load_env_file(ROOT.parent / ".env")


def api_key() -> str:
    load_env()
    key = os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")
    if not key:
        raise ValueError("Set BASETEN_API_KEY in guitar/.env or the repository .env")
    return key


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward authorization headers to another host.
        return None


def request_json(url: str, *, key: str, payload: dict | None = None,
                 timeout_s: float = 180, session_id: str | None = None) -> dict:
    if not any(url.startswith(base + "/") for base in (INFERENCE_URL, MANAGEMENT_URL)):
        raise ValueError("Only the official Baseten API hosts are allowed")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
    if session_id:
        headers["x-session-affinity"] = session_id
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirects()).open(request, timeout=timeout_s) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        hints = {400: "request/model parameters rejected", 401: "check the .env API key",
                 402: "account billing/credits required", 403: "model/account access denied",
                 404: "model not available", 408: "request timed out", 429: "rate limit reached",
                 500: "provider internal error", 502: "provider gateway error",
                 503: "provider unavailable", 504: "provider gateway timeout", 529: "provider overloaded"}
        # Deliberately don't echo request headers or arbitrary provider error bodies.
        raise BasetenRequestError(f"Baseten HTTP {exc.code}: {hints.get(exc.code, 'provider request failed')}",
                                  status_code=exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        raise BasetenRequestError("Baseten connection failed or timed out; no automatic retry",
                                  kind="timeout" if timed_out else "connection_error") from None
    except (ValueError, UnicodeError):
        raise BasetenError("Baseten returned invalid JSON") from None
    if not isinstance(result, dict) or result.get("error"):
        raise BasetenError("Baseten returned an error or non-object response")
    return result


class BasetenClient:
    """Native Chat Completions transport, using only a Baseten credential."""

    def __init__(self, *, model: str | None = None, key: str | None = None,
                 effort: str | None = None, timeout_s: float | None = None,
                 max_tokens: int | None = None):
        load_env()
        self.model = model or os.environ.get("BASETEN_MODEL") or DEFAULT_MODEL
        self._key = key or api_key()
        self.effort = effort or os.environ.get("BASETEN_REASONING_EFFORT") or "high"
        efforts = {"none", "low", "high", "max"} if self.model == DEFAULT_MODEL else {
            "none", "minimal", "low", "medium", "high", "xhigh", "max"}
        if self.effort not in efforts:
            raise ValueError(f"Unsupported BASETEN_REASONING_EFFORT for {self.model}; use {sorted(efforts)}")
        self.max_tokens = int(max_tokens if max_tokens is not None else os.environ.get("BASETEN_MAX_TOKENS") or "8192")
        if not 1 <= self.max_tokens <= 32768:
            raise ValueError("BASETEN_MAX_TOKENS must be between 1 and the client's 32768-token cap")
        self.timeout_s = float(timeout_s if timeout_s is not None else os.environ.get("BASETEN_TIMEOUT_S") or "180")
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("BASETEN_TIMEOUT_S must be finite and positive")
        self.session_id = uuid4().hex

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
             response_format: dict | None = None) -> dict:
        payload = {
            "model": self.model, "messages": messages,
            "reasoning_effort": self.effort, "max_tokens": self.max_tokens,
            "stream": False,
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
        if response_format is not None:
            payload["response_format"] = response_format
        return request_json(f"{INFERENCE_URL}/chat/completions", key=self._key,
                            payload=payload, timeout_s=self.timeout_s, session_id=self.session_id)
