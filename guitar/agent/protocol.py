"""Provider-neutral tool messages, with no device or controller imports."""
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    call_id: str
    text: str
    image_jpeg: bytes | None = None
    is_error: bool = False
    record: dict = field(default_factory=dict)
