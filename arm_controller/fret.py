"""Fretting tools for the second arm (IDs 7-12) — press-and-hold at any
(string, fret), built on the repo's existing recorded pose map. Tool layer
only; the model backend (Baseten) gets wired later, same as pluck.py.

Existing mapping used (NOT re-recorded here):
  guitar/robot/poses/fret_arm.json   110 poses: above_s{s}_f{f} / touch_s{s}_f{f}
                                     for strings 1-6 x frets 1-9, plus rest/ready
  guitar/robot/calibration/fret_arm.json  raw-count ranges per joint

Pose values are LeRobot-normalized (body joints -100..100 over the calibrated
range, gripper 0..100). LeRobot wrote each servo's homing offset into EEPROM,
so raw bus counts live in the same offset-adjusted space and conversion is
pure range math (see _to_raw).

String convention matches plucking: 1 = high E (rightmost) ... 6 = low E.
Press depth: press = touch + (mm / 10) * (touch - above), capped at 8 mm
(from guitar/robot/fretmap.py: anchors were recorded hovering 10 mm above).

=== INTERFERENCE / SAFETY CONTRACT (see FRETTING.md) =========================
Never translate while touching the strings — that scrapes/sounds them:
  1. LIFT    from any held fret straight up to its own 'above' pose
  2. TRANSLATE between 'above' poses (10 mm hover surface); long moves
     (>3 frets or >2 strings apart, or from unknown position) route via
     'ready' for extra clearance
  3. PRESS   straight down from 'above' to touch/press, and HOLD
The GRIPPER (ID 12) holds the fingertip tool. These tools NEVER command it —
not position, not torque. See guitar/CONNECT.md gripper rule.
==============================================================================

CLI (close anything holding the port first):
  uv run --with pyserial python fret.py --list
  uv run --with pyserial python fret.py --pose 3 5          # print exact targets, no motion
  uv run --with pyserial python fret.py --hold 3 5 --mm 4
  uv run --with pyserial python fret.py --release --ready
"""
import json
import time
from pathlib import Path

from app import FeetechBus

FRET_PORT = "/dev/cu.usbmodem5AB01811681"  # re-enumerates on replug — check ls /dev/cu.usbmodem*
BAUD = 1_000_000

_REPO = Path(__file__).resolve().parents[1]
POSES_PATH = _REPO / "guitar/robot/poses/fret_arm.json"
CALIB_PATH = _REPO / "guitar/robot/calibration/fret_arm.json"

GRIPPER_JOINT = "gripper"  # ID 12 — never commanded by these tools
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
MAX_FRET = 9
HOVER_MM = 10.0
MAX_PRESS_MM = 8.0
DEFAULT_PRESS_MM = 4.0

# speed knobs — tune once the arm is powered and audible feedback exists
TRANSLATE_SPEED = 400
LIFT_SPEED = 350
PRESS_SPEED = 250     # slow, straight-down press = no scrape
ACC = 30
SETTLE_TOL = 30
SETTLE_TIMEOUT = 3.0


def _load():
    poses = json.loads(POSES_PATH.read_text())["poses"]
    calib = json.loads(CALIB_PATH.read_text())
    return poses, calib


def _to_raw(joint, norm, calib):
    """LeRobot normalized value -> raw servo counts (offset already in EEPROM)."""
    c = calib[joint]
    lo, hi = c["range_min"], c["range_max"]
    if joint == GRIPPER_JOINT:  # RANGE_0_100
        frac = norm / 100.0
    else:                       # RANGE_M100_100
        frac = (norm + 100.0) / 200.0
    return int(round(lo + frac * (hi - lo)))


def pose_to_raw(pose, calib, include_gripper=False):
    return {calib[j]["id"]: _to_raw(j, v, calib)
            for j, v in pose.items()
            if include_gripper or j != GRIPPER_JOINT}


class FretMap:
    """Pose lookup + press extrapolation. No hardware needed."""

    def __init__(self):
        self.poses, self.calib = _load()

    def above(self, string, fret):
        return self.poses[f"above_s{string}_f{fret}"]

    def touch(self, string, fret):
        return self.poses[f"touch_s{string}_f{fret}"]

    def press(self, string, fret, mm=DEFAULT_PRESS_MM):
        mm = max(0.0, min(MAX_PRESS_MM, float(mm)))
        above, touch = self.above(string, fret), self.touch(string, fret)
        return {j: touch[j] + (mm / HOVER_MM) * (touch[j] - above[j])
                for j in touch}

    def exact(self, string, fret, mm=DEFAULT_PRESS_MM):
        """The exact positions for reaching/holding (string, fret) — for tools/logs."""
        if not (1 <= string <= 6 and 1 <= fret <= MAX_FRET):
            raise ValueError(f"string 1-6 and fret 1-{MAX_FRET} required")
        return {
            "string": string, "fret": fret, "note_open": STRING_NOTES[string],
            "press_mm": mm,
            "above": {"normalized": self.above(string, fret),
                      "raw": pose_to_raw(self.above(string, fret), self.calib)},
            "touch": {"normalized": self.touch(string, fret),
                      "raw": pose_to_raw(self.touch(string, fret), self.calib)},
            "press": {"normalized": self.press(string, fret, mm),
                      "raw": pose_to_raw(self.press(string, fret, mm), self.calib)},
        }


class FretArm:
    def __init__(self, port=FRET_PORT, baud=BAUD):
        self.map = FretMap()
        self.calib = self.map.calib
        self.ids = [c["id"] for j, c in self.calib.items() if j != GRIPPER_JOINT]
        self.bus = FeetechBus(port, baud)
        alive = [sid for sid in self.ids if self.bus.ping(sid)]
        if len(alive) < len(self.ids):
            raise RuntimeError(f"fret arm motors responding: {alive} of {self.ids} — check power")
        for sid in alive:
            self.bus.set_torque(sid, True)
        self.state = None  # None=unknown, else ("above"|"hold", string, fret) or "ready"/"rest"

    def close(self, torque_off=False):
        if torque_off:  # only when the arm is physically supported
            for sid in self.ids:
                self.bus.set_torque(sid, False)
        self.bus.close()

    def _move(self, pose, speed, wait=True):
        targets = pose_to_raw(pose, self.calib)  # gripper excluded
        for sid, pos in targets.items():
            self.bus.goto(sid, pos, speed=speed, acc=ACC)
        if wait:
            deadline = time.time() + SETTLE_TIMEOUT
            while time.time() < deadline:
                if all((p := self.bus.read_pos(sid)) is not None and abs(p - t) <= SETTLE_TOL
                       for sid, t in targets.items()):
                    return True
                time.sleep(0.03)
        return False

    def _lift_if_holding(self):
        if isinstance(self.state, tuple) and self.state[0] == "hold":
            _, s, f = self.state
            self._move(self.map.above(s, f), LIFT_SPEED)
            self.state = ("above", s, f)

    def _far(self, s, f):
        if not isinstance(self.state, tuple):
            return True  # unknown / ready / rest -> take the safe route
        _, cs, cf = self.state
        return abs(cs - s) > 2 or abs(cf - f) > 3

    # ---- tools ----------------------------------------------------------

    def hold_fret(self, string, fret, press_mm=DEFAULT_PRESS_MM):
        """Press (string, fret) and HOLD until release_fret/another hold."""
        info = self.map.exact(string, fret, press_mm)
        self._lift_if_holding()                              # 1 LIFT
        if self._far(string, fret):
            self._move(self.map.poses["ready"], TRANSLATE_SPEED)
        self._move(self.map.above(string, fret), TRANSLATE_SPEED)  # 2 TRANSLATE
        self._move(self.map.press(string, fret, press_mm), PRESS_SPEED)  # 3 PRESS
        self.state = ("hold", string, fret)
        return {"status": "holding", "string": string, "fret": fret,
                "press_mm": press_mm, "target_raw": info["press"]["raw"]}

    def release_fret(self):
        """Lift straight up off the current fret to its 'above' hover."""
        if isinstance(self.state, tuple) and self.state[0] == "hold":
            self._lift_if_holding()
            return {"status": "released", "hover": self.state[1:]}
        return {"status": "not holding"}

    def ready(self):
        self._lift_if_holding()
        self._move(self.map.poses["ready"], TRANSLATE_SPEED)
        self.state = "ready"
        return {"status": "ready"}

    def rest(self):
        self._lift_if_holding()
        self._move(self.map.poses["ready"], TRANSLATE_SPEED)
        self._move(self.map.poses["rest"], TRANSLATE_SPEED)
        self.state = "rest"
        return {"status": "rest"}


TOOLS = [
    {
        "name": "hold_fret",
        "description": "Press and HOLD string at fret with the fretting arm. "
                       "String 1 = high E (rightmost) ... 6 = low E (leftmost); "
                       "frets 1-9. Stays pressed until release_fret or another "
                       "hold_fret. Transit is scrape-safe (lift -> hover "
                       "translate -> straight-down press); callers never route. "
                       "Sounding the note is the plucking arm's job.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 9},
                "press_mm": {"type": "number", "default": 4.0, "minimum": 0, "maximum": 8},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "release_fret",
        "description": "Lift the fretting finger straight up off the currently "
                       "held fret (string rings open afterwards).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fret_position",
        "description": "Return the exact joint targets (normalized and raw servo "
                       "counts) for above/touch/press at (string, fret). No motion.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 9},
                "press_mm": {"type": "number", "default": 4.0},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "fret_ready",
        "description": "Fretting arm to its ready hover (clear of the neck).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "fret_rest",
        "description": "Fretting arm to its rest pose (parked).",
        "parameters": {"type": "object", "properties": {}},
    },
]


def dispatch(arm, tool_name, args):
    """Backend entry point. get_fret_position works with arm=None (no hardware)."""
    if tool_name == "get_fret_position":
        fmap = arm.map if arm else FretMap()
        return fmap.exact(int(args["string"]), int(args["fret"]),
                          float(args.get("press_mm", DEFAULT_PRESS_MM)))
    if tool_name == "hold_fret":
        return arm.hold_fret(int(args["string"]), int(args["fret"]),
                             float(args.get("press_mm", DEFAULT_PRESS_MM)))
    if tool_name == "release_fret":
        return arm.release_fret()
    if tool_name == "fret_ready":
        return arm.ready()
    if tool_name == "fret_rest":
        return arm.rest()
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Fretting tool CLI")
    ap.add_argument("--list", action="store_true", help="summarize the fret map")
    ap.add_argument("--pose", nargs=2, type=int, metavar=("STRING", "FRET"),
                    help="print exact targets for (string, fret); no motion")
    ap.add_argument("--hold", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--mm", type=float, default=DEFAULT_PRESS_MM)
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--ready", action="store_true")
    ap.add_argument("--rest", action="store_true")
    a = ap.parse_args()

    if a.list:
        m = FretMap()
        frets = sorted({int(k.split("_f")[1]) for k in m.poses if k.startswith("above_")})
        strs = sorted({int(k.split("_s")[1].split("_")[0]) for k in m.poses if k.startswith("above_")})
        print(f"strings {strs} x frets {frets} + rest/ready ({len(m.poses)} poses)")
        print(f"notes: {STRING_NOTES}")
        raise SystemExit(0)
    if a.pose:
        print(json.dumps(FretMap().exact(a.pose[0], a.pose[1], a.mm), indent=2))
        raise SystemExit(0)

    arm = FretArm()
    try:
        if a.hold:
            print(arm.hold_fret(a.hold[0], a.hold[1], a.mm))
        if a.release:
            print(arm.release_fret())
        if a.ready:
            print(arm.ready())
        if a.rest:
            print(arm.rest())
    finally:
        arm.close()
