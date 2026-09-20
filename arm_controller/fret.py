"""Tapping/fretting tools for the ONLY working arm (IDs 7-12) — v3 single-arm.

THE PLUCK ARM (IDs 5,6,1,2,7,3) IS OUT OF SERVICE (2026-09-19). This arm is
the whole instrument now: it sounds notes by TAPPING the pre-recorded keys
(hammer-on style — press the string onto the fret fast, then lift). pluck.py
is retired; do not wire its tools into any backend.

v3 MAPPING (2026-09-19, full 18-cell grid re-recorded against the committed
kinematic baseline — see CALIBRATION.md; supersedes v2 and the old 110-pose
fret map; do NOT fall back to guitar/robot/poses/fret_arm.json):
  keyframes_arm2.json holds one keypoint per cell, named pose-r{R}-c{C}:
    r = fret row (1..3 recorded)
    c = string/column, SAME convention as plucking: 1 = high E (rightmost)
        ... 6 = low E (leftmost)
  Values are RAW servo counts for IDs 7-11 (still the played source of
  truth); each keypoint also carries "degrees" (relative to the baseline
  pose) and "xyz_cm" (fingertip world position, kinematics.py) so callers
  can reason spatially. 'rest' is the safe park pose; 'rest-r{R}' are
  per-fret-row lifted hubs. The GRIPPER (ID 12) is NEVER commanded.

=== SAFETY / INTERFERENCE (v3 contract) ======================================
Transitions are staged through lifted hubs, never sliding on the board:
  LIFT to the current row's hub -> travel to the target row's hub (if the
  row changed) -> PRESS. Rows without a recorded 'rest-r{R}' hub fall back
  to the global 'rest' (the web executor's injected snapshot carries no row
  hubs, so it always routes press -> rest -> press). First motion after
  connect always routes via a hub from 'rest'-ward, so the arm can never
  scrape across strings or neck. This is NOT a collision-free guarantee;
  recorded poses and the full swept path still need operator qualification.
  Audio/XYZ estimates cannot establish clearance. Never invent a shortcut
  from a model recommendation.
==============================================================================

XYZ deduction/extrapolation lives in gridfit.py: bilinear fits over the
recorded grid predict fingertip XYZ and approximate servo counts for ANY
(string, fret), including unrecorded frets (estimate_position tool; no
motion — predictions are a planning aid, not directly playable).

CLI:
  uv run --with pyserial python fret.py --list
  uv run --with pyserial python fret.py --pose 3 2      # string 3, fret 2 (no motion)
  uv run --with pyserial python fret.py --estimate 3 5  # extrapolated cell (no motion)
  uv run --with pyserial python fret.py --tap 3 2       # tap one key (sounds the note)
  uv run --with pyserial python fret.py --seq 1,1 2,1 3,2   # tap several keys in order
  uv run --with pyserial python fret.py --hold 3 2
  uv run --with pyserial python fret.py --release --rest
  uv run --with pyserial python fret.py --qualify-row-hubs  # supervised slow walk,
      # then records the operator's row_hub qualification for the web console
"""
import json
import re
import time
from pathlib import Path

from app import FeetechBus

FRET_PORT = "/dev/cu.wchusbserial5B8E1128501"  # re-enumerates on replug — check ls /dev/cu.*
BAUD = 1_000_000

KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm2.json"

MOTOR_IDS = [7, 8, 9, 10, 11]  # gripper 12 deliberately absent
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
MAX_FRET = 3  # first rows only, per operator (r4 was partially recorded; ignored)

TRAVEL_SPEED = 400
PRESS_SPEED = 250
TAP_SPEED = 1200   # tap press is fast — the impact is what sounds the note
TAP_DWELL_S = 0.12  # contact time before lifting; short = staccato tap
ACC = 30
SETTLE_TOL = 30
# Press stages stall AGAINST the string by design (poses are recorded already
# pressed), so the elbow routinely stops tens of counts short of the target —
# observed 45 on r2-c4. That is contact, not a fault; only travel/lift stages
# keep the strict tolerance. v2 ignored settle results entirely, so PRESS_TOL
# is still stricter than everything that played before v3.
PRESS_TOL = 90
SETTLE_TIMEOUT = 4.0

_CELL = re.compile(r"pose[-_]?r(\d+)[-_]?c(\d+)$")
_CELL_T = re.compile(r"pose[-_]?c(\d+)[-_]?r(\d+)$")  # transposed name variant
_ROW_REST = re.compile(r"rest[-_]?r(\d+)$")


def load_map(path=KEYFRAMES_PATH, max_fret=MAX_FRET, *, entries=None):
    """-> {"cells": {(string, fret): raw_pose}, "rest": pose,
           "row_rests": {fret: pose}, "xyz": {(string, fret): xyz_cm dict},
           "degrees": {(string, fret): {sid: deg}}, "warns": [str]}

    entries optionally supplies an already-read local snapshot (never model data).
    """
    cells, xyz, degrees, row_rests, rest, warns = {}, {}, {}, {}, None, []
    for k in entries if entries is not None else json.loads(Path(path).read_text()):
        name = k["name"].strip().lower()
        pose = {int(sid): int(v) for sid, v in k["positions"].items() if int(sid) in MOTOR_IDS}
        if name == "rest":
            rest = pose
            continue
        rr = _ROW_REST.fullmatch(name)
        if rr:
            row_rests[int(rr.group(1))] = pose
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
        if k.get("xyz_cm"):
            xyz[(c, r)] = k["xyz_cm"]
        if k.get("degrees"):
            degrees[(c, r)] = k["degrees"]
    if rest is None:
        raise ValueError("no 'rest' keyframe in the grid — required as the safe hub")
    return {"cells": cells, "rest": rest, "row_rests": row_rests,
            "xyz": xyz, "degrees": degrees, "warns": warns}


def load_grid(path=KEYFRAMES_PATH, max_fret=MAX_FRET, *, entries=None):
    """Back-compat view: -> (cells, rest_pose, warnings)."""
    m = load_map(path, max_fret, entries=entries)
    return m["cells"], m["rest"], m["warns"]


class FretArm:
    def __init__(self, port=FRET_PORT, baud=BAUD, *, grid=None, row_rests=None,
                 path_profile=None):
        """path_profile selects a fixed local staging family (never model data):
        "rest_hub" — every transition via the global rest; "row_hub" — via the
        operator-recorded per-row lifted hubs (requires row_rests). Default:
        row_hub when hubs are available, else rest_hub."""
        if grid is not None:
            # The web executor supplies a validated immutable snapshot, not model
            # poses. Row hubs are only honored when explicitly passed alongside
            # (same operator-recorded provenance as cells/rest).
            self.cells, self.rest_pose, self.warnings = grid
            self.row_rests = dict(row_rests) if row_rests else {}
            self.xyz = {}
        else:
            m = load_map()
            self.cells, self.rest_pose, self.warnings = m["cells"], m["rest"], m["warns"]
            self.row_rests, self.xyz = m["row_rests"], m["xyz"]
        if path_profile is None:
            path_profile = "row_hub" if self.row_rests else "rest_hub"
        if path_profile not in ("rest_hub", "row_hub"):
            raise ValueError(f"unknown path profile: {path_profile}")
        self.path_profile = path_profile
        self.bus = FeetechBus(port, baud)
        try:
            alive = [sid for sid in MOTOR_IDS if self.bus.ping(sid)]
            if len(alive) < len(MOTOR_IDS):
                raise RuntimeError(f"fret arm motors responding: {alive} of {MOTOR_IDS} — check power")
            for sid in alive:
                self.bus.set_torque(sid, True)
        except Exception:
            self.close(torque_off=True)  # BODY motors only, never the tool gripper
            raise
        self.holding = None  # (string, fret) or None
        self.last_row = None  # fret row the arm last worked in (None = unknown)

    def close(self, torque_off=False):
        # Operator supports the body for a normal torque-off disconnect. No homing
        # here, and no all-motors/broadcast torque command (gripper 12 is absent).
        error = None
        try:
            if torque_off:
                for sid in MOTOR_IDS:
                    try:
                        self.bus.set_torque(sid, False)
                    except Exception as exc:
                        error = exc
        finally:
            self.bus.close()
        if error:
            raise error

    def _move(self, pose, speed, wait=True, *, deadline=None, tol=SETTLE_TOL):
        if set(pose) != set(MOTOR_IDS) or any(type(v) is not int or not 0 <= v <= 4095
                                            for v in pose.values()):
            raise ValueError("A complete recorded body-joint pose is required")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Attempt deadline reached before a motion stage")
        for sid, pos in pose.items():
            self.bus.goto(sid, pos, speed=speed, acc=ACC)
        if wait:
            stage_deadline = time.monotonic() + SETTLE_TIMEOUT
            if deadline is not None:
                stage_deadline = min(stage_deadline, deadline)
            while time.monotonic() < stage_deadline:
                if all((p := self.bus.read_pos(sid)) is not None and abs(p - t) <= tol
                       for sid, t in pose.items()):
                    return True  # encoder tolerance only, not string/contact evidence
                time.sleep(0.03)
            # Previously this returned False which every caller ignored, and the
            # next press still ran. A failed stage must stop without recovery moves.
            raise TimeoutError("Encoder arrival timed out; state uncertain")
        return False

    def _cell(self, string, fret):
        if (string, fret) not in self.cells:
            have = sorted(self.cells)
            raise ValueError(f"no keypoint for string {string} fret {fret}; "
                             f"recorded cells (string, fret): {have}")
        return self.cells[(string, fret)]

    def _hub(self, fret):
        """Staging hub for a fret row under the active path profile: the row's
        recorded lifted hub in row_hub mode (rest if that row has none), the
        global rest otherwise."""
        if self.path_profile != "row_hub":
            return self.rest_pose
        return self.row_rests.get(int(fret), self.rest_pose)

    def _lift(self):
        """Rise off the board into the current row's hub (rest if unknown)."""
        hub = self._hub(self.last_row) if self.last_row is not None else self.rest_pose
        self._move(hub, TRAVEL_SPEED)

    def _stage(self, fret):
        """Scrape-safe approach: lift, then cross to the target row's hub."""
        self._lift()
        if self.last_row != fret:
            self._move(self._hub(fret), TRAVEL_SPEED)

    # ---- tools ----------------------------------------------------------

    def tap_key(self, string, fret, *, deadline=None):
        """Existing rest -> tap -> rest path, unchanged speeds/contact dwell.

        The only way this rig makes sound now — the tap impact is the attack.
        Staged via lifted row hubs (scrape-safe); without recorded row hubs
        (e.g. the web executor's injected snapshot) every hub is the global
        rest, giving the press -> rest -> press path in exactly three motion
        stages.

        A cooperative Stop finishes this bounded tap/lift, then blocks the next
        tap. It is NOT a motor emergency stop. A timeout raises immediately with
        no subsequent motion or automatic rest. Timings below are encoder/command
        observations, NOT verified contact or acoustic onsets.
        """
        s, f = int(string), int(fret)
        pose = self._cell(s, f)
        started, stages = time.monotonic(), []

        def stage(name, target, speed, tol=SETTLE_TOL):
            command = time.monotonic() - started
            self._move(target, speed, deadline=deadline, tol=tol)
            stages.append({"stage": name, "command_start_s": round(command, 4),
                           "encoder_ready_s": round(time.monotonic() - started, 4)})

        lift_hub = self._hub(self.last_row) if self.last_row is not None else self.rest_pose
        stage("lift", lift_hub, TRAVEL_SPEED)
        if self.last_row != f and self._hub(f) is not lift_hub:
            stage("travel", self._hub(f), TRAVEL_SPEED)
        stage("tap", pose, TAP_SPEED, tol=PRESS_TOL)  # fast press = the note; stalls on contact
        time.sleep(TAP_DWELL_S)
        stage("lift_clear", self._hub(f), TRAVEL_SPEED)
        self.holding, self.last_row = None, f
        return {"status": "command_completed", "string": s, "fret": f,
                "note_open": STRING_NOTES.get(s), "stages": stages,
                "xyz_cm": self.xyz.get((s, f)), "path_profile": self.path_profile,
                "acoustic_success": "unknown", "contact_verified": False}

    def tap_sequence(self, keys, gap_s=0.3):
        """Tap several (string, fret) keys in order with a fixed gap."""
        results = []
        for s, f in keys:
            results.append(self.tap_key(s, f))
            if gap_s:
                time.sleep(gap_s)
        return results

    def hold_fret(self, string, fret):
        """Press (string, fret) and HOLD. Staged via row hubs — never slides."""
        s, f = int(string), int(fret)
        pose = self._cell(s, f)
        self._stage(f)
        self._move(pose, PRESS_SPEED, tol=PRESS_TOL)
        self.holding, self.last_row = (s, f), f
        return {"status": "holding", "string": s, "fret": f,
                "note_open": STRING_NOTES.get(s), "target_raw": pose,
                "xyz_cm": self.xyz.get((s, f))}

    def release_fret(self):
        """Lift off the current hold into the row's hub."""
        was = self.holding
        self._lift()
        self.holding = None
        return {"status": "released", "was_holding": was}

    def rest(self):
        """Park: lift out of the board first, then settle in the global rest."""
        self._lift()
        self._move(self.rest_pose, TRAVEL_SPEED)
        self.holding, self.last_row = None, None
        return {"status": "rest"}


QUALIFY_SPEED = 180  # deliberately slow: the operator watches every move


def qualify_row_hubs(arm):
    """Supervised slow walk of every motion family the row_hub profile can
    execute: each row hub, every press/lift in that row, and every hub-to-hub
    crossing. The OPERATOR watches for scrapes/interference and then decides;
    this routine records their decision, it does not qualify anything itself."""
    if not arm.row_rests:
        raise ValueError("no rest-r{N} row hubs recorded — record them first")
    arm.path_profile = "row_hub"
    rows = sorted(arm.row_rests)
    print(f"row hubs {rows}; slow speed {QUALIFY_SPEED}. Watch the arm. Ctrl-C aborts.")
    arm._move(arm.rest_pose, QUALIFY_SPEED)
    for r in rows:
        print(f"-- row {r}: hub, then each recorded press")
        arm._move(arm._hub(r), QUALIFY_SPEED)
        for (s, f) in sorted(k for k in arm.cells if k[1] == r):
            arm._move(arm.cells[(s, f)], QUALIFY_SPEED, tol=PRESS_TOL)
            arm._move(arm._hub(r), QUALIFY_SPEED)
    print("-- hub-to-hub crossings")
    for a in rows:
        for b in rows:
            if a != b:
                arm._move(arm._hub(a), QUALIFY_SPEED)
                arm._move(arm._hub(b), QUALIFY_SPEED)
    arm._move(arm.rest_pose, QUALIFY_SPEED)
    print("walk complete.")


def record_row_hub_qualification():
    """Persist the operator's decision, bound to the exact current keyframes."""
    import hashlib

    import kinematics
    cal = json.loads(kinematics.CAL_PATH.read_text())
    cal.setdefault("qualified_profiles", {})["row_hub"] = {
        "keyframes_sha256": hashlib.sha256(KEYFRAMES_PATH.read_bytes()).hexdigest(),
        "qualified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    kinematics.CAL_PATH.write_text(json.dumps(cal, indent=2))
    return cal["qualified_profiles"]["row_hub"]


# The COMPLETE tool surface for the rig — single arm, tap-based. The pluck
# arm's tools (pluck.py) are retired and must not be added to any backend.
TOOLS = [
    {
        "name": "tap_key",
        "description": "Tap one pre-recorded key to SOUND its note (fast press "
                       "onto the fret, brief dwell, lift back to rest). This is "
                       "the only way this rig makes sound. String 1 = high E "
                       "(rightmost) ... 6 = low E (leftmost); ONLY frets 1-3 are "
                       "mapped. Transit uses the existing rest hub; full paths "
                       "still require operator qualification. Callers never plan paths.",
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
        "name": "tap_sequence",
        "description": "Tap several keys in order with a fixed gap between taps. "
                       "Same mapping and rest-hub constraints as tap_key.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "minItems": 2, "maxItems": 2,
                        "description": "[string, fret]",
                    },
                },
                "gap_s": {"type": "number", "default": 0.3,
                          "description": "seconds between taps"},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "hold_fret",
        "description": "Press and HOLD a string at a fret (no tap attack — "
                       "quiet press, e.g. to mute or prep). Stays pressed until "
                       "release_fret or another hold_fret. Same mapping as "
                       "tap_key; transit uses the existing rest hub.",
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
                       "fret), the recorded fingertip xyz_cm (world frame, see "
                       "CALIBRATION.md) and joint degrees, plus which cells are "
                       "recorded. No motion.",
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
        "name": "estimate_position",
        "description": "PREDICT the fingertip xyz_cm and approximate servo "
                       "counts for ANY (string, fret) by fitting the recorded "
                       "grid — works for unrecorded cells too (e.g. fret 4+, "
                       "extrapolated). Leave-one-out RMS error ~2.5 cm on the "
                       "recorded grid; use as a spatial planning aid, NOT as a "
                       "playable target. No motion.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 9},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "fret_rest",
        "description": "Fretting arm to its recorded rest pose; operator-qualified paths required.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def dispatch(arm, tool_name, args):
    """Backend entry point. get_fret_position and estimate_position work with
    arm=None (no hardware)."""
    if tool_name == "get_fret_position":
        m = load_map()
        s, f = int(args["string"]), int(args["fret"])
        if (s, f) not in m["cells"]:
            return {"error": f"no keypoint for string {s} fret {f}",
                    "recorded_cells": sorted(m["cells"])}
        return {"string": s, "fret": f, "note_open": STRING_NOTES.get(s),
                "target_raw": m["cells"][(s, f)], "xyz_cm": m["xyz"].get((s, f)),
                "degrees": m["degrees"].get((s, f)),
                "recorded_cells": sorted(m["cells"])}
    if tool_name == "estimate_position":
        import gridfit
        cells = gridfit.load_cells()
        if len(cells) < 6:
            return {"error": f"only {len(cells)} recorded cells with xyz — "
                             "record more before estimating"}
        s, f = int(args["string"]), int(args["fret"])
        out = gridfit.predict(gridfit.fit_models(cells), s, f)
        out.update(string=s, fret=f, recorded=(s, f) in cells,
                   extrapolated=(s, f) not in cells,
                   note="fitted prediction — planning aid, not a playable target")
        if not out["extrapolated"]:
            out["recorded_xyz"] = cells[(s, f)]["xyz"]
        return out
    if tool_name == "tap_key":
        return arm.tap_key(args["string"], args["fret"])
    if tool_name == "tap_sequence":
        return arm.tap_sequence(args["keys"], float(args.get("gap_s", 0.3)))
    if tool_name == "hold_fret":
        return arm.hold_fret(args["string"], args["fret"])
    if tool_name == "release_fret":
        return arm.release_fret()
    if tool_name == "fret_rest":
        return arm.rest()
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Single-arm tap/fret tool CLI (v2 grid)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pose", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--estimate", nargs=2, type=int, metavar=("STRING", "FRET"),
                    help="predict xyz + counts for any cell (extrapolates; no motion)")
    ap.add_argument("--tap", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--seq", nargs="+", metavar="S,F", help="keys to tap, e.g. 1,1 2,1 3,2")
    ap.add_argument("--gap", type=float, default=0.3, help="seconds between --seq taps")
    ap.add_argument("--hold", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--rest", action="store_true")
    ap.add_argument("--profile", choices=["auto", "rest_hub", "row_hub"], default="auto",
                    help="staging family for --tap/--seq/--hold (auto: row_hub if hubs exist)")
    ap.add_argument("--qualify-row-hubs", action="store_true",
                    help="supervised slow walk of all row_hub motions, then record "
                         "the operator's qualification decision")
    a = ap.parse_args()

    if a.list or a.pose or a.estimate:
        m = load_map()
        for w in m["warns"]:
            print("WARN:", w)
        if a.list:
            print(f"{len(m['cells'])} cells recorded (string, fret): {sorted(m['cells'])}")
            print(f"row hubs: {sorted(m['row_rests'])}   rest: {m['rest']}")
        if a.pose:
            print(json.dumps(dispatch(None, "get_fret_position",
                                      {"string": a.pose[0], "fret": a.pose[1]}), indent=2))
        if a.estimate:
            print(json.dumps(dispatch(None, "estimate_position",
                                      {"string": a.estimate[0], "fret": a.estimate[1]}),
                             indent=2))
        raise SystemExit(0)

    arm = FretArm(path_profile=None if a.profile == "auto" else a.profile)
    for w in arm.warnings:
        print("WARN:", w)
    try:
        if a.qualify_row_hubs:
            qualify_row_hubs(arm)
            answer = input("Did every move stay clear of strings/neck/body? "
                           "Type QUALIFIED to record, anything else to abort: ")
            if answer.strip() == "QUALIFIED":
                print("recorded:", record_row_hub_qualification())
            else:
                print("not recorded — row_hub stays unqualified")
        if a.tap:
            print(arm.tap_key(a.tap[0], a.tap[1]))
        if a.seq:
            keys = [tuple(int(x) for x in k.split(",")) for k in a.seq]
            for r in arm.tap_sequence(keys, a.gap):
                print(r)
        if a.hold:
            print(arm.hold_fret(a.hold[0], a.hold[1]))
        if a.release:
            print(arm.release_fret())
        if a.rest:
            print(arm.rest())
    finally:
        arm.close()
