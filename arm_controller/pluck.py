"""RETIRED (2026-09-19): the pluck arm (IDs 5,6,1,2,7,3) is OUT OF SERVICE.

The rig is single-arm now — fret.py (tap tools, IDs 7-12) is the complete
tool surface. Do NOT wire these TOOLS into any backend. File kept for the
recorded pose data in keyframes.json and for when/if the arm is repaired;
PluckArm refuses to construct until ARM_IN_SERVICE is flipped back.

--- original docstring ---
Plucking tools for the picking arm — the tool layer a model backend
(e.g. the Baseten-hosted brain) will call. No backend wiring lives here.

String convention: 1 = RIGHTMOST string, 6 = LEFTMOST string (operator-defined).
Each string has exactly two logged poses: pose_<n>a = stroke start, pose_<n>b =
stroke end. The pluck is the a->b sweep; everything else is safe transit.

=== INTERFERENCE — READ BEFORE CHANGING PATHS (see PLUCKING.md) ==============
Moving between strings at string depth drags the pick across intermediate
strings and plays unintended notes. The clearance axis is the ELBOW (ID 1):
all string poses sit at elbow >= 2682, while neutral sits retracted at 2474.
Every transit therefore follows RETRACT -> TRANSLATE -> EXTEND:
  1. RETRACT  elbow to SAFE_ELBOW (pick pulled off the string plane)
  2. TRANSLATE base/shoulder/wrists to the target string's start pose
  3. EXTEND   elbow back in to the start pose
Re-plucking the SAME string also needs this loop: after a stroke the pick is
past the string (b side); sliding straight back to a would re-cross it.
==============================================================================

Run directly (close the GUI app first — the serial port is exclusive):
  uv run --with pyserial python pluck.py --list
  uv run --with pyserial python pluck.py --neutral
  uv run --with pyserial python pluck.py 1 3 5 --gap 0.4
"""
import json
import re
import time
from pathlib import Path

from app import FeetechBus, PORT, BAUD, TORQUE_LIMIT_OVERRIDE

KEYFRAMES_PATH = Path(__file__).parent / "keyframes.json"

ARM_IN_SERVICE = False  # pluck arm dead as of 2026-09-19 — see module docstring

# Standard tuning, and the operator's right-to-left numbering matches guitar
# convention: string 1 = high E (thinnest) ... string 6 = low E (thickest).
# ASSUMPTION (verify by ear once): the RIGHTMOST string is the thin high E.
# If the guitar is oriented the other way, flip this table — nothing else.
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
NOTE_TO_STRING = {
    "e4": 1, "high e": 1, "highe": 1,
    "b3": 2, "b": 2,
    "g3": 3, "g": 3,
    "d3": 4, "d": 4,
    "a2": 5, "a": 5,
    "e2": 6, "low e": 6, "lowe": 6,
}

ELBOW = 1          # clearance axis
SAFE_ELBOW = 2500  # retracted: clear of all strings (strings >= 2682, neutral 2474)
GRIPPER = 3        # holds the pick — always commanded to its logged value, never opened

# --- timing / speed knobs: tune these BY EAR once audio feedback is in place ---
TRANSIT_SPEED = 500    # lateral repositioning between strings
TRANSIT_ACC = 30
EXTEND_SPEED = 350     # approaching the string plane (slow = quiet)
PLUCK_SPEED = 2000     # the a->b stroke itself (fast = clean attack)
PLUCK_ACC = 150
SETTLE_TOL = 25        # counts
SETTLE_TIMEOUT = 3.0   # seconds


def load_strings(path=KEYFRAMES_PATH):
    """Return ({string_n: {"start": pose, "end": pose}}, neutral_pose)."""
    frames = {k["name"]: {int(s): p for s, p in k["positions"].items()}
              for k in json.loads(Path(path).read_text())}
    strings = {}
    for name, pose in frames.items():
        m = re.fullmatch(r"pose_(\d)([ab])", name)
        if m:
            n, side = int(m.group(1)), m.group(2)
            strings.setdefault(n, {})["start" if side == "a" else "end"] = pose
    missing = [n for n, s in strings.items() if "start" not in s or "end" not in s]
    if missing:
        raise ValueError(f"strings missing a/b pose: {missing}")
    return strings, frames.get("neutral")


class PluckArm:
    def __init__(self, port=PORT, baud=BAUD):
        if not ARM_IN_SERVICE:
            raise RuntimeError("pluck arm is OUT OF SERVICE — the rig is "
                               "single-arm (fret.py tap tools). See docstring.")
        self.bus = FeetechBus(port, baud)
        self.strings, self.neutral = load_strings()
        alive = [sid for sid in [5, 6, 1, 2, 7, 3] if self.bus.ping(sid)]
        if len(alive) < 6:
            raise RuntimeError(f"motors responding: {alive} — check power/wiring")
        for sid in alive:
            self.bus.set_torque(sid, True)
        for sid, limit in TORQUE_LIMIT_OVERRIDE.items():
            self.bus.set_torque_limit(sid, limit)

    def close(self, torque_off=False):
        # default keeps torque ON so the arm doesn't fall onto the guitar
        if torque_off:
            for sid in [5, 6, 1, 2, 7, 3]:
                self.bus.set_torque(sid, False)
        self.bus.close()

    def _move(self, targets, speed, acc, wait=True):
        for sid, pos in targets.items():
            self.bus.goto(sid, pos, speed=speed, acc=acc)
        if wait:
            self._settle(targets)

    def _settle(self, targets, tol=SETTLE_TOL, timeout=SETTLE_TIMEOUT):
        deadline = time.time() + timeout
        while time.time() < deadline:
            done = all(
                (p := self.bus.read_pos(sid)) is not None and abs(p - tgt) <= tol
                for sid, tgt in targets.items()
            )
            if done:
                return True
            time.sleep(0.03)
        return False  # timed out; caller may proceed — positions are close enough to log

    # ---- tools ----------------------------------------------------------

    def retract(self):
        """Pull the pick off the string plane. SAFE between any operations."""
        self._move({ELBOW: SAFE_ELBOW}, TRANSIT_SPEED, TRANSIT_ACC)

    def goto_neutral(self):
        self.retract()
        rest = {sid: v for sid, v in self.neutral.items() if sid != ELBOW}
        self._move(rest, TRANSIT_SPEED, TRANSIT_ACC)
        self._move({ELBOW: self.neutral[ELBOW]}, TRANSIT_SPEED, TRANSIT_ACC)

    def pluck(self, string):
        """Pluck one string (1 = rightmost .. 6 = leftmost).

        INTERFERENCE-SAFE SEQUENCE — do not reorder (see module docstring):
        retract -> translate at clearance -> extend -> stroke.
        """
        if string not in self.strings:
            raise ValueError(f"unknown string {string}; have {sorted(self.strings)}")
        start = self.strings[string]["start"]
        end = self.strings[string]["end"]
        self.retract()                                              # 1 clear
        lateral = {sid: v for sid, v in start.items() if sid != ELBOW}
        self._move(lateral, TRANSIT_SPEED, TRANSIT_ACC)             # 2 translate
        self._move({ELBOW: start[ELBOW]}, EXTEND_SPEED, TRANSIT_ACC)  # 3 extend
        self._move(end, PLUCK_SPEED, PLUCK_ACC)                     # 4 stroke = sound
        return {"string": string, "note": STRING_NOTES.get(string), "status": "plucked"}

    def pluck_note(self, note):
        """Pluck by note name ('E4', 'B3', 'G3', 'D3', 'A2', 'E2', 'low E', 'high E')."""
        key = str(note).strip().lower()
        if key not in NOTE_TO_STRING:
            raise ValueError(f"unknown note '{note}'; open strings are {list(STRING_NOTES.values())}")
        return self.pluck(NOTE_TO_STRING[key])

    def pluck_sequence(self, strings, gap_s=0.3):
        results = []
        for n in strings:
            results.append(self.pluck(int(n)))
            if gap_s:
                time.sleep(gap_s)
        return results


# ---- tool schemas for the model backend (Baseten wiring comes later) -------
# OpenAI-function format; convert trivially for other protocols.
TOOLS = [
    {
        "name": "pluck_string",
        "description": "Pluck one guitar string. String 1 is the RIGHTMOST string "
                       "(open note E4, high E); string 6 is the LEFTMOST (open note "
                       "E2, low E). Standard tuning: 1=E4 2=B3 3=G3 4=D3 5=A2 6=E2. "
                       "Transit between strings is interference-safe "
                       "(retract->translate->extend) — callers never need to route "
                       "around intermediate strings.",
        "parameters": {
            "type": "object",
            "properties": {"string": {"type": "integer", "minimum": 1, "maximum": 6}},
            "required": ["string"],
        },
    },
    {
        "name": "pluck_note",
        "description": "Pluck the open string for a note name. Valid: E4/high E, "
                       "B3, G3, D3, A2, E2/low E (standard tuning, open strings "
                       "only — no fretting on this arm).",
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
    {
        "name": "pluck_sequence",
        "description": "Pluck several strings in order with a fixed gap between "
                       "plucks. Same safety guarantees as pluck_string.",
        "parameters": {
            "type": "object",
            "properties": {
                "strings": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 6}},
                "gap_s": {"type": "number", "default": 0.3, "description": "seconds between plucks"},
            },
            "required": ["strings"],
        },
    },
    {
        "name": "goto_neutral",
        "description": "Return the arm to its safe neutral pose, clear of all strings.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def dispatch(arm, tool_name, args):
    """Single entry point for any backend: dispatch(arm, name, args) -> result."""
    if tool_name == "pluck_string":
        return arm.pluck(int(args["string"]))
    if tool_name == "pluck_note":
        return arm.pluck_note(args["note"])
    if tool_name == "pluck_sequence":
        return arm.pluck_sequence(args["strings"], float(args.get("gap_s", 0.3)))
    if tool_name == "goto_neutral":
        arm.goto_neutral()
        return {"status": "neutral"}
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Pluck tool CLI (close the GUI app first)")
    ap.add_argument("strings", nargs="*", type=int, help="strings to pluck, e.g. 1 3 5")
    ap.add_argument("--gap", type=float, default=0.3)
    ap.add_argument("--neutral", action="store_true", help="go to neutral pose")
    ap.add_argument("--list", action="store_true", help="show loaded string poses")
    a = ap.parse_args()

    if a.list:
        strings, neutral = load_strings()
        for n in sorted(strings):
            s = strings[n]
            print(f"string {n} ({STRING_NOTES.get(n, '?')}): start={s['start']} end={s['end']}")
        print(f"neutral: {neutral}")
        raise SystemExit(0)

    arm = PluckArm()
    try:
        if a.neutral:
            arm.goto_neutral()
            print("at neutral")
        if a.strings:
            print(arm.pluck_sequence(a.strings, a.gap))
            arm.goto_neutral()
    finally:
        arm.close()
