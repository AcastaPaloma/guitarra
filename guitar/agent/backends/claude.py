"""Claude backend (Anthropic Messages API, manual tool-use loop).

Manual rather than the SDK tool runner because every tool call must pass through our guards,
turn budget and run recorder, and the loop has to look the same for the Astra backend.
Needs ANTHROPIC_API_KEY (or an `ant auth login` profile).
"""
import base64

import anthropic

from ..tools import ToolCall, ToolResult
from . import Turn

MODEL = "claude-opus-5"


class ClaudeBackend:
    name = "claude"

    def __init__(self, model: str = MODEL, effort: str = "medium"):
        self.client = anthropic.Anthropic()
        self.model, self.effort = model, effort
        self.messages: list = []
        self.tools: list = []
        self.system = ""

    def begin(self, system: str, tool_specs: list[dict], text: str, image_jpeg: bytes | None) -> Turn:
        self.system = system
        self.tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"], "strict": True}
            for t in tool_specs
        ]
        self.messages = [{"role": "user", "content": _image(image_jpeg) + [{"type": "text", "text": text}]}]
        return self._call()

    def respond(self, results: list[ToolResult], note: str | None = None) -> Turn:
        content = [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": [{"type": "text", "text": r.text}] + _image(r.image_jpeg),
                "is_error": r.is_error,
            }
            for r in results
        ]
        if note:
            content.append({"type": "text", "text": note})
        self.messages.append({"role": "user", "content": content})
        return self._call()

    def _call(self) -> Turn:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},  # history is append-only, so the prefix caches
            # server-side refusal fallback: if Opus 5 declines, the API reruns on a fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        thinking = "\n".join(b.thinking for b in resp.content if b.type == "thinking" and b.thinking)
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        u = resp.usage
        return Turn(
            text=text,
            thinking=thinking,
            calls=calls,
            stop=resp.stop_reason,
            usage={
                "input": u.input_tokens,
                "output": u.output_tokens,
                "cache_read": u.cache_read_input_tokens or 0,
                "cache_write": u.cache_creation_input_tokens or 0,
            },
        )


def _image(jpeg: bytes | None) -> list[dict]:
    if not jpeg:
        return []
    data = base64.standard_b64encode(jpeg).decode()
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]
