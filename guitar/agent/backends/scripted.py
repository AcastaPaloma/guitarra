"""No-API backend: replays a fixed plan. For testing the loop, guards and recorder offline."""
from ..tools import ToolCall
from . import Turn

FRET_PLAN = [
    ("look", {}),
    ("fret", {"string": 5, "fret": 7, "press_mm": 2, "speed": 0.5}),
    ("fret", {"string": 3, "fret": 2, "press_mm": 3, "speed": 0.5}),  # lifts off s5f7, hovers, lowers
    ("move_to", {"pose": "rest", "speed": 0.4}),             # must be rejected: still holding a fret
    ("release", {"speed": 0.5}),
    ("fret", {"string": 5, "fret": 5, "press_mm": 12, "speed": 0.5}),  # out of range: must be rejected
    ("move_to", {"pose": "rest", "speed": 0.4}),
    ("done", {"reason": "scripted plan finished"}),
]

PLAN = [
    ("look", {}),
    ("move_to", {"pose": "above_string", "speed": 0.5}),
    ("pluck", {"depth_mm": 2, "speed": 0.5}),
    ("pluck", {"depth_mm": 40, "speed": 0.5}),     # out of range on purpose: must be rejected
    ("pluck", {"depth_mm": 5, "speed": 0.7}),
    ("move_to", {"pose": "rest", "speed": 0.4}),
    ("done", {"reason": "scripted plan finished"}),
]


class ScriptedBackend:
    name = "scripted"

    def __init__(self, role: str = "pluck"):
        self.i = 0
        self.plan = FRET_PLAN if role == "fret" else PLAN

    def _next(self) -> Turn:
        if self.i >= len(self.plan):
            return Turn(text="(plan exhausted)", stop="end_turn")
        name, args = self.plan[self.i]
        self.i += 1
        return Turn(text=f"scripted step {self.i}: {name} {args}", calls=[ToolCall(f"s{self.i}", name, args)], stop="tool_use")

    def begin(self, system, tool_specs, text, image_jpeg) -> Turn:
        return self._next()

    def respond(self, results, note=None) -> Turn:
        return self._next()
