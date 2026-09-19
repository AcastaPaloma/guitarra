"""Baseten-managed Kimi K3 planner, native tool calls, no cloud hardware access.

BASETEN_MODEL defaults to moonshotai/Kimi-K3. The older custom Truss /predict
adapter is preserved as baseten_custom.py and is never selected as a fallback.
"""
from __future__ import annotations

import base64
import copy
import json

from jsonschema import Draft202012Validator, ValidationError

from model.baseten import BasetenClient, BasetenError
from ..protocol import ToolCall, ToolResult
from . import Turn
from .baseten_custom import _image_field  # noqa: F401 - compatibility for existing camera-policy checks

POLICY = """You propose bounded guitar-rehearsal decisions; a local controller owns execution.
Use only the provided tools and operator-qualified capabilities. At most ONE tool per response.
Never invent observations, raw joint paths, calibration/grip changes, or safety overrides.
release means lift off a string, NEVER open the gripper. Mechanical state does not prove sound.
Camera is off unless explicitly enabled. Audio summaries are text, not a recording you heard.
After an unsafe/unsupported request or uncertain execution, stop or request operator review;
never silently replay a motion. Prefer a brief reason grounded in the actual observations.
"""


def _content(text: str, jpeg: bytes | None):
    if not jpeg:
        return text
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}]


def _no_constant(value: str):
    raise ValueError("Nonfinite JSON number")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class BasetenBackend:
    name = "baseten"

    def __init__(self, model: str | None = None, effort: str | None = None,
                 api_key: str | None = None, timeout_s: float | None = None,
                 max_tokens: int | None = None):
        self.client = BasetenClient(model=model, effort=effort, key=api_key,
                                    timeout_s=timeout_s, max_tokens=max_tokens)
        self.model = self.client.model
        self.messages: list[dict] = []
        self.tools: list[dict] = []
        self.validators: dict[str, Draft202012Validator] = {}
        self.pending: set[str] = set()
        self.used_ids: set[str] = set()

    def begin(self, system: str, tool_specs: list[dict], text: str, image_jpeg: bytes | None) -> Turn:
        self.tools, self.validators = [], {}
        self.pending, self.used_ids = set(), set()
        for spec in tool_specs:
            name, schema = spec["name"], copy.deepcopy(spec["parameters"])
            if name in self.validators:
                raise ValueError("Duplicate tool name")
            Draft202012Validator.check_schema(schema)
            self.validators[name] = Draft202012Validator(schema)
            self.tools.append({"type": "function", "function": {
                "name": name, "description": spec["description"], "parameters": schema}})
        self.messages = []
        return self._call([
            {"role": "system", "content": POLICY + "\n" + system},
            {"role": "user", "content": _content(text, image_jpeg)},
        ])

    def respond(self, results: list[ToolResult], note: str | None = None) -> Turn:
        ids = [r.call_id for r in results]
        if not self.pending or len(ids) != len(set(ids)) or set(ids) != self.pending:
            raise BasetenError("Tool results must match pending calls exactly once")
        messages = copy.deepcopy(self.messages)
        for result in results:
            messages.append({"role": "tool", "tool_call_id": result.call_id, "content": result.text})
            if result.image_jpeg:
                messages.append({"role": "user", "content": _content(
                    f"Opted-in diagnostic snapshot after {result.call_id}", result.image_jpeg)})
        if note:
            messages.append({"role": "user", "content": note})
        return self._call(messages)

    def _call(self, messages: list[dict]) -> Turn:
        response = self.client.chat(messages, tools=self.tools)
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise BasetenError("Expected exactly one complete Baseten response")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise BasetenError("Invalid assistant response")
        reason = choice.get("finish_reason")
        # No malformed, refused, partial or multi-action response reaches the dispatcher.
        if message.get("refusal") or reason == "content_filter":
            return Turn(text="Model declined the request.", stop="refusal")
        if reason not in {"stop", "tool_calls"}:
            raise BasetenError(f"Incomplete/unsupported model finish reason: {reason!r}")
        text = message.get("content") or ""
        if not isinstance(text, str):
            raise BasetenError("Expected text response content")
        raw_calls = message.get("tool_calls")
        if raw_calls is None:
            raw_calls = []
        if not isinstance(raw_calls, list) or len(raw_calls) > 1:
            raise BasetenError("Expected at most one tool call; rejecting entire response")
        if (reason == "tool_calls") != bool(raw_calls):
            raise BasetenError("Tool calls and finish reason disagree")
        calls = []
        for call in raw_calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                raise BasetenError("Invalid tool-call envelope")
            call_id, fn = call.get("id"), call.get("function")
            if not isinstance(call_id, str) or not call_id or call_id in self.used_ids or not isinstance(fn, dict):
                raise BasetenError("Missing/duplicate call ID or function")
            name, arguments = fn.get("name"), fn.get("arguments")
            if not isinstance(name, str) or name not in self.validators or not isinstance(arguments, str):
                raise BasetenError("Unknown tool or malformed arguments")
            try:
                args = json.loads(arguments, parse_constant=_no_constant, object_pairs_hook=_unique_keys)
                if not isinstance(args, dict):
                    raise ValueError("Arguments are not an object")
                self.validators[name].validate(args)
            except (ValueError, ValidationError):
                raise BasetenError("Tool arguments failed JSON/schema validation; no call dispatched") from None
            calls.append(ToolCall(call_id, name, args))
        # Preserve native call serialization and reasoning_content for provider continuation,
        # but don't print/log private reasoning as narration or execute arbitrary response text.
        assistant = {k: copy.deepcopy(message[k]) for k in
                     ("role", "content", "tool_calls", "reasoning_content") if k in message}
        self.messages = messages + [assistant]
        self.pending = {call.id for call in calls}
        self.used_ids.update(self.pending)
        usage = response.get("usage") or {}
        return Turn(text=text, calls=calls, stop="tool_use" if calls else "end_turn",
                    usage={"input": usage.get("prompt_tokens", 0),
                           "output": usage.get("completion_tokens", 0)})
