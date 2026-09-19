"""GPT-6 Astra backend (OpenAI Responses API), per DESIGN.md section 3.

Not yet run against the live API (no key with Astra access on this machine). Needs
OPENAI_API_KEY. Uses previous_response_id, so only new items are sent each turn.
"""
import base64
import json

from openai import OpenAI

from ..tools import ToolCall, ToolResult
from . import Turn

MODEL = "gpt-6-astra"


class AstraBackend:
    name = "astra"

    def __init__(self, model: str = MODEL, effort: str = "medium"):
        self.client = OpenAI()
        self.model, self.effort = model, effort
        self.prev_id: str | None = None
        self.tools: list = []
        self.instructions = ""

    def begin(self, system: str, tool_specs: list[dict], text: str, image_jpeg: bytes | None) -> Turn:
        self.instructions = system
        self.tools = [
            {"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["parameters"], "strict": True}
            for t in tool_specs
        ]
        return self._call([{"role": "user", "content": _image(image_jpeg) + [{"type": "input_text", "text": text}]}])

    def respond(self, results: list[ToolResult], note: str | None = None) -> Turn:
        items: list = [{"type": "function_call_output", "call_id": r.call_id, "output": r.text} for r in results]
        # frames go in a follow-up user message: the one input shape every Responses model accepts
        images = [c for r in results for c in _image(r.image_jpeg)]
        extra = ([{"type": "input_text", "text": note}] if note else [])
        if images or extra:
            items.append({"role": "user", "content": images + extra})
        return self._call(items)

    def _call(self, items: list) -> Turn:
        resp = self.client.responses.create(
            model=self.model,
            instructions=self.instructions,
            tools=self.tools,
            input=items,
            previous_response_id=self.prev_id,
            reasoning={"effort": self.effort},
        )
        self.prev_id = resp.id
        calls, text = [], []
        for item in resp.output:
            if item.type == "function_call":
                calls.append(ToolCall(item.call_id, item.name, json.loads(item.arguments)))
            elif item.type == "message":
                text += [c.text for c in item.content if getattr(c, "type", "") == "output_text"]
        u = resp.usage
        return Turn(
            text="\n".join(text),
            calls=calls,
            stop="tool_use" if calls else "end_turn",
            usage={"input": u.input_tokens, "output": u.output_tokens} if u else {},
        )


def _image(jpeg: bytes | None) -> list[dict]:
    if not jpeg:
        return []
    return [{"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}]
