"""Inactive custom Truss adapter, selected only with --backend baseten-custom.

The active --backend baseten uses managed Kimi K3 in baseten.py.

The Baseten deployment is intentionally only the model brain. The robot tools still run
locally through agent.tools/robot.guards, so a remote model can propose actions but cannot
bypass the safety layer or directly talk to hardware.

Expected Baseten model output (returned directly or under ``model_output``)::

    {
      "text": "I see ... so I will ...",
      "tool_calls": [
        {"id": "optional", "name": "look", "arguments": {}}
      ],
      "stop": "tool_use"
    }

Configure with either BASETEN_MODEL_URL, or BASETEN_MODEL_ID plus BASETEN_ENV
(development|production). Auth comes from BASETEN_API_KEY.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..protocol import ToolCall, ToolResult
from . import Turn

DEFAULT_ENV = "development"
ROOT = Path(__file__).resolve().parents[2]


def _load_env_file(path: Path) -> None:
    """Load a .env file without adding a dependency; existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        key = key.strip()
        if value and not os.environ.get(key):
            os.environ[key] = value


def _load_env_files() -> None:
    # Prefer the guitar subproject file, but also accept a repo-root .env because
    # operators often keep one secret file at the top of the checkout.
    _load_env_file(ROOT / ".env")
    _load_env_file(ROOT.parent / ".env")


class BasetenBackend:
    name = "baseten-custom"

    def __init__(
        self,
        model: str | None = None,
        *,
        model_id: str | None = None,
        model_url: str | None = None,
        api_key: str | None = None,
        environment: str | None = None,
        effort: str = "medium",
        timeout_s: float | None = None,
    ):
        _load_env_files()
        # In the shared loop, --model maps to the backend's "model" kwarg. For
        # Baseten, treat it as the deployed Baseten model id.
        self.model_id = model_id or model or os.environ.get("BASETEN_MODEL_ID")
        self.model_url = model_url or os.environ.get("BASETEN_MODEL_URL")
        self.environment = environment or os.environ.get("BASETEN_ENV", DEFAULT_ENV)
        self.api_key = api_key or os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")
        self.effort = effort
        self.timeout_s = timeout_s or float(os.environ.get("BASETEN_TIMEOUT_S", "180"))

        if not self.model_url:
            if not self.model_id:
                raise ValueError("set BASETEN_MODEL_ID (or pass --model) or BASETEN_MODEL_URL")
            self.model_url = f"https://model-{self.model_id}.api.baseten.co/{self.environment}/predict"
        if not self.api_key:
            raise ValueError("set BASETEN_API_KEY in guitar/.env or the environment")

        self.session_id = uuid4().hex
        self.system = ""
        self.tools: list[dict] = []
        self.messages: list[dict[str, Any]] = []
        self.call_names: dict[str, str] = {}
        self._fallback_call_i = 0

    def begin(self, system: str, tool_specs: list[dict], text: str, image_jpeg: bytes | None) -> Turn:
        self.system = system
        self.tools = tool_specs
        self.messages = [{"role": "user", "text": text, **_image_field(image_jpeg)}]
        return self._call()

    def respond(self, results: list[ToolResult], note: str | None = None) -> Turn:
        for r in results:
            self.messages.append({
                "role": "tool",
                "tool_call_id": r.call_id,
                "name": self.call_names.get(r.call_id, "unknown"),
                "text": r.text,
                "is_error": r.is_error,
                **_image_field(r.image_jpeg),
            })
        if note:
            self.messages.append({"role": "user", "text": note})
        return self._call()

    def _call(self) -> Turn:
        payload = {
            "session_id": self.session_id,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
            "generation": {"effort": self.effort},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.model_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - operator configured URL
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Baseten HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Baseten request failed: {e}") from e

        parsed = json.loads(raw)
        out = parsed.get("model_output", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(out, dict):
            raise RuntimeError(f"Baseten returned non-object output: {out!r}")

        text = str(out.get("text", ""))
        calls = self._parse_calls(out)
        usage = out.get("usage", {}) if isinstance(out.get("usage", {}), dict) else {}
        stop = str(out.get("stop") or ("tool_use" if calls else "end_turn"))

        assistant_msg = {"role": "assistant", "text": text, "tool_calls": [c.__dict__ for c in calls]}
        self.messages.append(assistant_msg)
        for c in calls:
            self.call_names[c.id] = c.name
        return Turn(text=text, calls=calls, stop=stop, usage=usage)

    def _parse_calls(self, out: dict) -> list[ToolCall]:
        raw_calls = out.get("tool_calls", out.get("calls", []))
        if raw_calls is None:
            return []
        if not isinstance(raw_calls, list):
            raise RuntimeError(f"Baseten tool_calls must be a list, got {type(raw_calls).__name__}")

        calls = []
        for item in raw_calls:
            if not isinstance(item, dict):
                raise RuntimeError(f"Baseten tool call must be an object, got {item!r}")
            name = item.get("name") or item.get("function", {}).get("name")
            args = item.get("arguments", item.get("args", item.get("input", {})))
            if isinstance(args, str):
                args = json.loads(args or "{}")
            if not isinstance(args, dict):
                raise RuntimeError(f"arguments for {name!r} must be an object, got {args!r}")
            if not name:
                raise RuntimeError(f"tool call missing name: {item!r}")
            call_id = item.get("id") or item.get("call_id")
            if not call_id:
                self._fallback_call_i += 1
                call_id = f"bt_call_{self._fallback_call_i}"
            calls.append(ToolCall(str(call_id), str(name), args))
        return calls


def _image_field(jpeg: bytes | None) -> dict[str, str]:
    if not jpeg:
        return {}
    return {"image_jpeg_b64": base64.b64encode(jpeg).decode("ascii")}
