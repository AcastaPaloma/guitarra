"""Fretting tools for the second arm (IDs 7-11) — v2, built on the operator's
re-recorded keypoint grid. Tool layer only; backend (Baseten) wired later.

v2 MAPPING (2026-09-19, supersedes the old 110-pose fret map — the operator
found it inaccurate; do NOT fall back to guitar/robot/poses/fret_arm.json):
  keyframes_arm2.json holds one keypoint per cell, named pose-r{R}-c{C}:
    r = fret row (1..3 supported for now — first rows of the neck only)
    c = string/column, SAME convention as plucking: 1 = high E (rightmost)
        ... 6 = low E (leftmost)
  Values are RAW servo counts for IDs 7-11 (recorded with the keyframe GUI),
  so no unit conversion is involved. 'rest' is the recorded safe park pose.
  The GRIPPER (ID 12) holds the fingertip tool and is NEVER commanded.

=== SAFETY / INTERFERENCE (v2 contract) ======================================
The v2 grid has no above/touch pairs, so there is no hover surface to
translate on. Until hover poses are recorded, EVERY transition routes through
'rest' as the safe hub:  press -> rest -> press.  Slower than hovering, but it
can never scrape the strings or the neck. If a faster path is wanted later,
record per-cell hover keypoints and restore the LIFT->TRANSLATE->PRESS
staging (see git history of this file for that implementation).
==============================================================================

CLI:
  uv run --with pyserial python fret.py --list
  uv run --with pyserial python fret.py --pose 3 2      # string 3, fret 2 (no motion)
  uv run --with pyserial python fret.py --hold 3 2
  uv run --with pyserial python fret.py --release --rest
"""
import json
import re
import time
from pathlib import Path

from app import FeetechBus

FRET_PORT = "/dev/cu.usbmodem5AB01811681"  # re-enumerates on replug — check ls /dev/cu.usbmodem*
BAUD = 1_000_000

KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm2.json"

MOTOR_IDS = [7, 8, 9, 10, 11]  # gripper 12 deliberately absent
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
MAX_FRET = 3  # first rows only, per operator (r4 was partially recorded; ignored)

TRAVEL_SPEED = 400
PRESS_SPEED = 250
ACC = 30
SETTLE_TOL = 30
SETTLE_TIMEOUT = 4.0

_CELL = re.compile(r"pose[-_]?r(\d+)[-_]?c(\d+)$")
_CELL_T = re.compile(r"pose[-_]?c(\d+)[-_]?r(\d+)$")  # transposed name variant


def load_grid(path=KEYFRAMES_PATH, max_fret=MAX_FRET):
    """-> (cells{(string, fret): raw_pose}, rest_pose, warnings[list of str])."""
    cells, rest, warns = {}, None, []
    for k in json.loads(Path(path).read_text()):
        name = k["name"].strip().lower()
        pose = {int(sid): int(v) for sid, v in k["positions"].items() if int(sid) in MOTOR_IDS}
        if name == "rest":
            rest = pose
            continue
        m = _CELL.fullmatch(name) or _CELL_T.fullmatch(name)
        if not m:
            warns.append(f"unrecognized keyframe name skipped: {k['name']}")
            continue
        r, c = (int(m.group(1)), int(m.group(2))) if _CELL.fullmatch(name) else \
               (int(m.group(2)), int(m.group(1)))
        if not (1 <= r <= max_fret and 1 <= c <= 6):
            warns.append(f"out of supported range (fret 1-{max_fret}), skipped: {k['name']}")
            continue
        if (c, r) in cells:  # first recording wins; later dupes are flagged
            warns.append(f"duplicate for string {c} fret {r} ignored: {k['name']}")
            continue
        cells[(c, r)] = pose
    if rest is None:
        raise ValueError("no 'rest' keyframe in the grid — required as the safe hub")
    return cells, rest, warns


class FretArm:
    def __init__(self, port=FRET_PORT, baud=BAUD):
        self.cells, self.rest_pose, self.warnings = load_grid()
        self.bus = FeetechBus(port, baud)
        alive = [sid for sid in MOTOR_IDS if self.bus.ping(sid)]
        if len(alive) < len(MOTOR_IDS):
            raise RuntimeError(f"fret arm motors responding: {alive} of {MOTOR_IDS} — check power")
        for sid in alive:
            self.bus.set_torque(sid, True)
        self.holding = None  # (string, fret) or None

    def close(self, torque_off=False):
        if torque_off:  # only when the arm is physically supported
            for sid in MOTOR_IDS:
                self.bus.set_torque(sid, False)
        self.bus.close()

    def _move(self, pose, speed, wait=True):
        for sid, pos in pose.items():
            self.bus.goto(sid, pos, speed=speed, acc=ACC)
        if wait:
            deadline = time.time() + SETTLE_TIMEOUT
            while time.time() < deadline:
                if all((p := self.bus.read_pos(sid)) is not None and abs(p - t) <= SETTLE_TOL
                       for sid, t in pose.items()):
                    return True
                time.sleep(0.03)
        return False

    def _cell(self, string, fret):
        if (string, fret) not in self.cells:
            have = sorted(self.cells)
            raise ValueError(f"no keypoint for string {string} fret {fret}; "
                             f"recorded cells (string, fret): {have}")
        return self.cells[(string, fret)]

    # ---- tools ----------------------------------------------------------

    def hold_fret(self, string, fret):
        """Press (string, fret) and HOLD. Routes via rest — never slides on the board."""
        pose = self._cell(int(string), int(fret))
        self._move(self.rest_pose, TRAVEL_SPEED)   # safe hub
        self._move(pose, PRESS_SPEED)
        self.holding = (int(string), int(fret))
        return {"status": "holding", "string": int(string), "fret": int(fret),
                "note_open": STRING_NOTES.get(int(string)), "target_raw": pose}

    def release_fret(self):
        """Lift off the current hold back to rest."""
        was = self.holding
        self._move(self.rest_pose, TRAVEL_SPEED)
        self.holding = None
        return {"status": "released", "was_holding": was}

    def rest(self):
        self._move(self.rest_pose, TRAVEL_SPEED)
        self.holding = None
        return {"status": "rest"}


TOOLS = [
    {
        "name": "hold_fret",
        "description": "Press and HOLD a string at a fret with the fretting arm. "
                       "String 1 = high E (rightmost) ... 6 = low E (leftmost). "
                       "ONLY frets 1-3 are mapped for now. Stays pressed until "
                       "release_fret or another hold_fret. Transit is scrape-safe "
                       "(routes via the rest pose); callers never plan paths. "
                       "Sounding the note is the plucking arm's job.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "release_fret",
        "description": "Lift the fretting finger off the currently held fret and "
                       "return to rest (string rings open afterwards).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fret_position",
        "description": "Return the exact raw servo targets for holding (string, "
                       "fret), plus which cells are recorded. No motion.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "fret_rest",
        "description": "Fretting arm to its recorded rest pose (parked, safe).",
        "parameters": {"type": "object", "properties": {}},
    },
]


def dispatch(arm, tool_name, args):
    """Backend entry point. get_fret_position works with arm=None (no hardware)."""
    if tool_name == "get_fret_position":
        cells = arm.cells if arm else load_grid()[0]
        s, f = int(args["string"]), int(args["fret"])
        if (s, f) not in cells:
            return {"error": f"no keypoint for string {s} fret {f}",
                    "recorded_cells": sorted(cells)}
        return {"string": s, "fret": f, "note_open": STRING_NOTES.get(s),
                "target_raw": cells[(s, f)], "recorded_cells": sorted(cells)}
    if tool_name == "hold_fret":
        return arm.hold_fret(args["string"], args["fret"])
    if tool_name == "release_fret":
        return arm.release_fret()
    if tool_name == "fret_rest":
        return arm.rest()
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Fretting tool CLI (v2 grid)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pose", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--hold", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--rest", action="store_true")
    a = ap.parse_args()

    if a.list or a.pose:
        cells, rest, warns = load_grid()
        for w in warns:
            print("WARN:", w)
        if a.list:
            print(f"{len(cells)} cells recorded (string, fret): {sorted(cells)}")
            print(f"rest: {rest}")
        if a.pose:
            print(json.dumps(dispatch(None, "get_fret_position",
                                      {"string": a.pose[0], "fret": a.pose[1]}), indent=2))
        raise SystemExit(0)

    arm = FretArm()
    for w in arm.warnings:
        print("WARN:", w)
    try:
        if a.hold:
            print(arm.hold_fret(a.hold[0], a.hold[1]))
        if a.release:
            print(arm.release_fret())
        if a.rest:
            print(arm.rest())
    finally:
        arm.close()
