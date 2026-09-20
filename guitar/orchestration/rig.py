"""Whitelisted model tools over real Motions code with an explicitly constructed FakeArm.

The fretting side uses the saved map and existing trajectory guards. The pick side is
ONLY a stateful fixture: no calibrated picking map is supplied. There is no RealArm
factory, serial port option, microphone, camera, shell tool, or model-controlled cleanup.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from jsonschema import Draft202012Validator, ValidationError

from agent.protocol import ToolCall, ToolResult
from motions import Motions
from robot.arm import FakeArm
from robot import fretmap, poses
from robot.guards import GuardError

PROFILE = "dryrun_default"
SPEED = 0.3
PRESS_MM = 1.0  # sandbox parameter, NOT permission to use this depth on hardware
MOTION_TOOLS = {"ready", "hover", "touch", "press", "release", "rest", "move_to", "pluck"}


class VirtualClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid virtual-clock interval")
        self.now += seconds


class Rejected(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def _spec(name: str, description: str, properties: dict) -> dict:
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}


class FakeRig:
    def __init__(self, *, fail_first_press: bool = False):
        self.clock = VirtualClock()
        # Directly construct the fake, never motions.connect(fake=...) or a configurable factory.
        self.arm = FakeArm("fret_arm", clock=self.clock)
        self.arm.connect()
        self.fret = Motions(self.arm)
        self.targets = fretmap.available(self.arm.poses)
        self.contact = "clear"
        self.pick_at = "rest"
        self.fault: str | None = None
        self.fail_first_press = fail_first_press
        self.finished: dict | None = None
        self.events: list[dict] = []
        self.plucks: list[dict] = []
        self.seen_ids: set[str] = set()
        self.closed = False
        self.tool_specs = self._specs()
        self.validators = {s["name"]: Draft202012Validator(s["parameters"]) for s in self.tool_specs}

    def _specs(self) -> list[dict]:
        target = {
            "string": {"type": "integer", "enum": sorted(self.targets), "description": "6=low E, 5=A, 4=D, 3=G, 2=B, 1=high E"},
            "fret": {"type": "integer", "enum": sorted({f for fs in self.targets.values() for f in fs})},
        }
        profile = {"type": "string", "enum": [PROFILE], "description": "Permitted sandbox profile only; not physical qualification"}
        arm = {"type": "string", "enum": ["fret", "pick"]}
        return [
            _spec("available", "Read both arms' sandbox capabilities, supported targets and profiles; no movement.", {}),
            _spec("where", "Read both fake arms' state and any latched fault; no movement or sensor access.", {}),
            _spec("ready", "Prepare the selected arm. Fret: lift if needed, then saved ready pose; use only before the first fret motion or after completion, not between notes. Pick: synthetic readiness.", {"arm": arm}),
            _spec("hover", "Fret arm: automatically lift before travel, enter via ready only if needed, finish above target. No contact. Useful for inspection, but press already includes the required safe hover path.", target),
            _spec("touch", "Fret arm: hover then recorded contact, with no extra press. Touch alone is NOT ready to pluck in this fixture.", target),
            _spec("press", "Fret arm: safe direct transition to a supported spot. If another fret is held, this FIRST lifts to the old hover, then travels minimally at hover clearance to the new hover, lowers to touch, and presses. No separate release/ready/rest call is needed between different notes. Keep the press for repeat plucks; pressing the same target again repeats the approach and is inefficient.", {**target, "profile": profile}),
            _spec("release", "Lift the fretting fingertip off its string to hover. NEVER opens a gripper. Use after the final pluck or when aborting; do not release between normal sequential notes because press can transition directly.", {}),
            _spec("rest", "Return the selected arm to rest/neutral; fret automatically lifts and exits via ready. Do NOT use between notes. It is only for explicit completion/parking or operator-requested cleanup.", {"arm": arm}),
            _spec("move_to", "Fret arm only: recall a saved pose through Motions routing. A touch pose is not an extra press. Coordinates cannot be supplied.", {
                "pose": {"type": "string", "enum": sorted(self.arm.poses)}}),
            _spec("pluck", "Synthetic pick arm: pluck once and reset to ready. Requires pick at ready AND fret arm successfully pressing the SAME string. Returns a symbolic event, not sound. Repeated plucks can reuse the held fret.", {
                "string": target["string"], "profile": profile}),
            _spec("done", "Finish completed only after required notes and final fret lift, or blocked when unsupported/faulted. Does not execute cleanup/motion.", {
                "outcome": {"type": "string", "enum": ["completed", "blocked"]},
                "reason": {"type": "string", "minLength": 1, "maxLength": 2000}}),
        ]

    def capabilities(self) -> dict:
        return {
            "mode": "fake_only", "hardware_enabled": False,
            "fret": {"implementation": "motions.Motions over robot.arm.FakeArm",
                     "string_to_supported_frets": self.targets,
                     "map_sha256": hashlib.sha256(poses.path_for("fret_arm").read_bytes()).hexdigest(),
                     "recorded_targets_are_not_physical_qualification": True},
            "pick": {"implementation": "synthetic_state_fixture", "supported_strings": sorted(self.targets),
                     "no_calibrated_pick_poses": True, "reset_after_pluck": True},
            "profiles": {PROFILE: {"speed": SPEED, "press_mm": PRESS_MM, "permission": "sandbox_only"}},
            "timing": "virtual command-grid duration + assumed pick durations; NOT measured physical timing",
            "inputs": {"camera": False, "microphone": False, "audio_evaluator": False},
        }

    def state(self) -> dict:
        return {
            "virtual_s": round(self.clock.now, 6),
            "fret": {"at": "unknown_after_fault" if self.fault else self.fret.where()["at"],
                     "target": list(self.arm.pressing) if self.arm.pressing else None,
                     "contact": "unknown" if self.fault else self.contact},
            "pick": {"at": self.pick_at, "source": "synthetic_fixture"},
            "fault": self.fault, "plucks_so_far": len(self.plucks),
            "tool_clamps": "unchanged_simulated", "acoustic_result": "not_evaluated",
        }

    def run(self, call: ToolCall) -> ToolResult:
        if self.closed:
            raise RuntimeError("Fake rig is closed")
        before = self.state()
        error_code = None
        try:
            if self.finished is not None:
                raise Rejected("session_finished", "Session already finished")
            if not isinstance(call.id, str) or not call.id or call.id in self.seen_ids:
                raise Rejected("duplicate_call", "Call IDs must be nonempty and unique; no replay")
            self.seen_ids.add(call.id)
            if call.name not in self.validators:
                raise Rejected("unknown_tool", "Tool is not in the allowlist")
            self.validators[call.name].validate(call.args)
            if self.fault and call.name in MOTION_TOOLS:
                raise Rejected("fault_latched", "Execution state is uncertain; no more motion, finish blocked")
            detail = self._dispatch(call.name, call.args)
            out = {"ok": True, **detail}
        except ValidationError:
            error_code = "invalid_arguments"
            out = {"ok": False, "error": "Arguments failed tool schema validation"}
        except Rejected as exc:
            error_code = exc.code
            out = {"ok": False, "error": str(exc)}
        except (GuardError, ValueError) as exc:
            # Existing motion methods may have done an earlier segment; never assume a replay is safe.
            self.fault = "guard_rejection_requires_review"
            error_code = "motion_guard"
            out = {"ok": False, "error": str(exc)}
        after = self.state()
        if error_code:
            out["error_code"] = error_code
        out.update(mode="fake_only", state=after)
        event = {"index": len(self.events), "call_id": call.id, "tool": call.name,
                 "args": copy.deepcopy(call.args), "before": before, "after": after,
                 "result": copy.deepcopy(out)}
        self.events.append(event)
        return ToolResult(call.id, json.dumps(out, allow_nan=False), is_error=not out["ok"], record=event)

    def _dispatch(self, name: str, args: dict) -> dict:
        if name == "available":
            return {"capabilities": self.capabilities()}
        if name == "where":
            return {}
        if name == "done":
            if args["outcome"] == "completed" and (self.fault or self.arm.pressing is not None):
                raise Rejected("not_finished", "Cannot complete while a fault is latched or a fret remains held")
            self.finished = dict(args)
            return {"session_finished": True}
        if name in {"ready", "rest"}:
            if args["arm"] == "pick":
                self.clock.sleep(0.2)  # explicit synthetic fixture duration
                self.pick_at = name
            else:
                getattr(self.fret, name)()  # name is limited to these two literals
                self.contact = "clear"
        elif name in {"hover", "touch", "press"}:
            string, fret = int(args["string"]), int(args["fret"])
            if fret not in self.targets.get(string, []):
                raise Rejected("unsupported_target", "No saved above/touch pair for this target")
            if name == "press" and self.fail_first_press:
                self.fail_first_press = False
                self.fault = "injected_fret_execution_uncertain"
                raise Rejected("injected_fault", "Synthetic press execution failed; state uncertain. Stop motion; do not retry or home.")
            spot = fretmap.spot_name(string, fret)
            if name == "press":
                self.fret.press(spot, press_mm=PRESS_MM, speed=SPEED)
                self.contact = "pressed"
            elif name == "touch":
                self.fret.touch(spot, speed=SPEED)
                self.contact = "touch"
            else:
                self.fret.hover(spot, speed=SPEED)
                self.contact = "clear"
        elif name == "release":
            self.fret.release(speed=SPEED)
            self.contact = "clear"
        elif name == "move_to":
            self.fret.move_to(args["pose"], speed=SPEED)
            self.contact = "touch" if self.arm.pressing else "clear"
        elif name == "pluck":
            if self.pick_at != "ready":
                raise Rejected("pick_not_ready", "Prepare the pick arm with ready(arm='pick') first")
            if self.contact != "pressed" or self.arm.pressing is None:
                raise Rejected("fret_not_pressed", "A successful press is required before plucking")
            string, fret = self.arm.pressing
            if string != args["string"]:
                raise Rejected("wrong_string", "Pick string must match the currently pressed string")
            pluck = {"string": string, "fret": fret, "virtual_onset_s": round(self.clock.now, 6),
                     "source": "synthetic_pick_event_not_audio"}
            self.clock.sleep(0.25)  # stroke + reset; no real motor/latency assumption
            self.plucks.append(pluck)
            return {"played_event": pluck, "pick_reset": True}
        return {}

    def close(self) -> None:
        if not self.closed:
            # FakeArm.disconnect is a no-op; do not auto-rest and hide an incomplete workflow.
            self.fret.disconnect()
            self.closed = True
