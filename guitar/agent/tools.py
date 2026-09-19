"""Tool registry: provider-neutral specs + the code that runs each tool on the arm.

Specs are plain JSON Schema; each backend wraps them in its own API's tool format. Numeric
ranges live in the descriptions and are enforced here (strict schemas can't carry min/max),
so an out-of-range request comes back to the model as an error instead of being clamped.
"""
import json
from dataclasses import dataclass, field

from robot import fretmap
from robot.arm import MAX_DEPTH_MM, Arm
from robot.guards import GuardError
from sense import camera
from sense.mic import score, transpose, wait_for_pluck


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
    record: dict = field(default_factory=dict)  # full detail for decisions.jsonl


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


MAX_PRESS_MM = fretmap.MAX_PRESS_MM


def specs(pose_names: list[str], role: str = "pluck", fret_map: dict[int, list[int]] | None = None) -> list[dict]:
    speed = {"type": "number", "description": "0.2 (slow) to 1.0 (fastest allowed). Scales a fixed safety speed cap."}
    if role == "fret":
        instrument = [
            {
                "name": "fret",
                "description": (
                    "Press a string just behind a fret: lifts off any held fret, hovers, lowers to touch "
                    "and presses press_mm further. Then waits for the string to be plucked and returns "
                    "the pitch heard vs the expected note, plus a camera frame. Calibrated positions: "
                    + "; ".join(f"string {s}: frets {v[0]}-{v[-1]}" for s, v in (fret_map or {}).items())
                ),
                "parameters": _obj({
                    "string": {"type": "integer", "enum": sorted(fret_map or {}, reverse=True),
                               "description": "6 = low E2 ... 1 = high E4 (standard tuning)"},
                    "fret": {"type": "integer", "enum": sorted({f for v in (fret_map or {}).values() for f in v})},
                    "press_mm": {"type": "number", "description": f"0 to {MAX_PRESS_MM:g}. Extra push past first contact. Too light = open-string pitch or buzz; more is not better."},
                    "speed": speed,
                }),
            },
            {
                "name": "release",
                "description": "Lift off the held fret back to its hover pose.",
                "parameters": _obj({"speed": speed}),
            },
        ]
    else:
        instrument = [{
            "name": "pluck",
            "description": (
                "Pluck the live string once: the arm goes above the string, lowers the pick to "
                "pluck_start pushed depth_mm into the string, strokes to pluck_end at `speed`, and "
                "returns above the string. Returns the audio score and a fresh camera frame."
            ),
            "parameters": _obj({
                "depth_mm": {"type": "number", "description": f"0 to {MAX_DEPTH_MM:g}. How far past the recorded pluck line the pick goes. Too shallow = silent, too deep = snag."},
                "speed": speed,
            }),
        }]
    return instrument + [
        {
            "name": "move_to",
            "description": "Move the arm to a named, hand-recorded pose. Returns arm state and a camera frame.",
            "parameters": _obj({"pose": {"type": "string", "enum": pose_names}, "speed": speed}),
        },
        {
            "name": "look",
            "description": "Take a fresh camera frame without moving.",
            "parameters": _obj({}),
        },
        {
            "name": "done",
            "description": "End the session. Call when the goal is met or you are stuck.",
            "parameters": _obj({"reason": {"type": "string"}}),
        },
    ]


def _range(args: dict, key: str, lo: float, hi: float) -> float:
    v = float(args[key])
    if not lo <= v <= hi:
        raise GuardError(f"{key}={v} outside [{lo}, {hi}]")
    return v


class Toolbox:
    def __init__(self, arm: Arm, mic=None, target_note: str = "A2", use_camera: bool = True,
                 pluck_prompt=None):
        # target_note: pluck arm's live string. The fretting arm derives its note from string + fret.
        self.arm, self.mic, self.target, self.use_camera = arm, mic, target_note, use_camera
        self.pluck_prompt = pluck_prompt or (lambda expected: print(f"     >>> PLUCK THE STRING NOW (expecting {expected})"))
        self.finished: str | None = None

    def _frame(self) -> tuple[bytes | None, str | None]:
        if not self.use_camera:
            return None, None
        try:
            return camera.grab(), None
        except camera.CameraError as e:
            return None, str(e)

    def run(self, call: ToolCall) -> ToolResult:
        rec: dict = {"tool": call.name, "args": call.args}
        try:
            if call.name == "pluck":
                depth = _range(call.args, "depth_mm", 0, MAX_DEPTH_MM)
                speed = _range(call.args, "speed", 0.2, 1.0)
                timing = self.arm.pluck(depth, speed)
                out = {"ok": True}
                if self.mic:
                    out["score"] = score(self.mic, timing["t_cmd"], self.target)
                else:
                    out["score"] = "no microphone this session - judge from the camera"
                rec["timing"] = timing
            elif call.name == "fret":
                string, n = int(call.args["string"]), int(call.args["fret"])
                press = _range(call.args, "press_mm", 0, MAX_PRESS_MM)
                timing = self.arm.fret(string, n, press, _range(call.args, "speed", 0.2, 1.0))
                expected = transpose(fretmap.STANDARD_TUNING[string], n)
                out = {"ok": True, "expected": expected}
                if self.mic:
                    self.pluck_prompt(expected)
                    out["score"] = wait_for_pluck(self.mic, expected)
                else:
                    out["score"] = "no microphone this session - judge from the camera"
                rec["timing"] = timing
            elif call.name == "release":
                rec["timing"] = self.arm.release(_range(call.args, "speed", 0.2, 1.0))
                out = {"ok": True}
            elif call.name == "move_to":
                timing = self.arm.move_to(call.args["pose"], _range(call.args, "speed", 0.2, 1.0))
                out = {"ok": True}
                rec["timing"] = timing
            elif call.name == "look":
                out = {"ok": True}
            elif call.name == "done":
                self.finished = call.args.get("reason", "")
                return ToolResult(call.id, '{"ok": true}', record=rec)
            else:
                raise GuardError(f"unknown tool '{call.name}'")
        except GuardError as e:
            rec["rejected"] = str(e)
            return ToolResult(call.id, json.dumps({"ok": False, "rejected_by_guard": str(e)}), is_error=True, record=rec)

        out["arm"] = self.arm.state()
        img, cam_err = self._frame()
        if cam_err:
            out["camera"] = cam_err
        rec["result"] = out
        return ToolResult(call.id, json.dumps(out), image_jpeg=img, record=rec)
