"""Model backends. Each one turns tool specs + observations into tool calls.

Interface (duck-typed):
    begin(system, tool_specs, text, image_jpeg) -> Turn
    respond(results: list[ToolResult], note: str | None) -> Turn
"""
from dataclasses import dataclass, field


@dataclass
class Turn:
    text: str
    calls: list = field(default_factory=list)   # list[ToolCall]
    stop: str = ""
    thinking: str = ""
    usage: dict = field(default_factory=dict)


def make(name: str, **kw):
    if name == "claude":
        from .claude import ClaudeBackend
        return ClaudeBackend(**kw)
    if name == "astra":
        from .astra import AstraBackend
        return AstraBackend(**kw)
    if name == "baseten":
        from .baseten import BasetenBackend
        return BasetenBackend(**kw)
    if name == "baseten-custom":
        from .baseten_custom import BasetenBackend
        return BasetenBackend(**kw)
    if name == "scripted":
        from .scripted import ScriptedBackend
        return ScriptedBackend(**kw)
    raise ValueError(f"unknown backend '{name}' (baseten | baseten-custom | claude | astra | scripted)")
