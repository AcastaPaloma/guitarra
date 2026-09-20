"""Upper-neck fretting arm (second bus) — tap tools for frets 7-11.

This is the re-commissioned second arm. Operator's joint mapping (2026-09-20):
  base=5, shoulder=4, elbow=6, wrist_flex=1, wrist_roll=2, grip=3.
The GRIP (ID 3) may hold a tool and is NEVER commanded — recorded poses carry
its value but motion filters it out, exactly like gripper 12 on the tap arm.

Grid: keyframes_arm1.json, one keypoint per cell named pose-r{fret}_{string}
(frets 7-11; string 1 = high E ... 6 = low E, same convention as the tap arm)
plus a 'rest' park pose, plus per-key lift hovers named hover-r{fret}-c{string}
(the operator shorthands hover-r{fret}_{string} / hover_r{fret}_{string} are
also accepted). Values are RAW servo counts.

=== LIFT-FIRST EXECUTION (webapp / default CLI) =============================
The webapp and the default CLI taps use ONLY the lift-first executor: the
generalized tap_paths ClearancePaths compiler bound to THIS arm's body IDs
(reviewed in calibration_arm1.json under qualified_profiles.lift_first), and
fret.FretArm semantics — every tap ends at its own hover, travel is only
hover-to-hover over reviewed directed edges, no reviewed paths = refusal.
The legacy rest-staged tap path below is DEPRECATED for the webapp and only
reachable from this CLI behind --unsafe-rest-staging (prints a warning).
==============================================================================

KNOWN HARDWARE CAUTION (2026-09-20): the original bus board overheated and was
replaced; the shoulder (4) measured ~5x slower than its siblings under load
before the failure. Run --detect before trusting motion, and supervise taps
until the shoulder proves healthy.

CLI (no motion unless stated):
  uv run --with pyserial python arm1.py --detect       # ping + temps/voltage
  uv run --with pyserial python arm1.py --list
  uv run --with pyserial python arm1.py --pose 3 9     # string 3, fret 9
  uv run --with pyserial python arm1.py --path-template # UNQUALIFIED draft only
  uv run --with pyserial python arm1.py --preview 3,9 3,10  # whole path, NO motion
  uv run --with pyserial python arm1.py --tap 3 9      # MOTION: lift-first tap
  uv run --with pyserial python arm1.py --seq 1,7 2,8  # MOTION: tap sequence
  uv run --with pyserial python arm1.py --rest         # MOTION: park at rest
  # DEPRECATED legacy motion (never used by the webapp):
  uv run --with pyserial python arm1.py --unsafe-rest-staging --tap 3 9
"""
import hashlib
import json
import re
import time
from pathlib import Path

import fret
import tap_paths
from app import FeetechBus, SAFE_VOLTAGE_RANGE, check_supply_voltage  # noqa: F401
from tap_arms import SECONDARY

ARM1_PORT = "/dev/cu.wchusbserial5B8E1126231"  # replacement board, 2026-09-20
BAUD = 1_000_000

KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm1.json"
CALIBRATION_PATH = Path(__file__).parent / "calibration_arm1.json"

BODY_IDS = [5, 4, 6, 1, 2]  # base, shoulder, elbow, wrist_flex, wrist_roll
GRIP_ID = 3                 # never commanded
JOINT_NAMES = {5: "base", 4: "shoulder", 6: "elbow", 1: "wrist_flex",
               2: "wrist_roll", 3: "grip"}
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
MIN_FRET, MAX_FRET = 7, 11
FRET_ROWS = frozenset(range(MIN_FRET, MAX_FRET + 1))

TRAVEL_SPEED = 400
TAP_SPEED = 1200
TAP_DWELL_S = 0.12
ACC = 30
SETTLE_TOL = 30
PRESS_TOL = 90
SETTLE_TIMEOUT = 4.0

# Supply-voltage gate lives in app.check_supply_voltage (shared by the GUI,
# the tap arm, and this arm): motion is refused outside SAFE_VOLTAGE_RANGE.

_CELL = re.compile(r"pose[-_]?r?[-_]?(\d+)[-_](\d+)$")
# hover-r{R}_{C} / hover_r{R}_{C} / hover-r{R}-c{C}
_HOVER = re.compile(r"hover[-_]r(\d+)[-_]c?(\d+)$")


def load_map(path=KEYFRAMES_PATH, *, entries=None):
    """-> {"cells": {(string, fret): pose}, "hovers": {(string, fret): pose},
           "rest": pose, "warns": [str]}.
    Poses are body joints only (grip filtered out)."""
    cells, hovers, rest, warns = {}, {}, None, []
    for k in entries if entries is not None else json.loads(Path(path).read_text()):
        name = k["name"].strip().lower()
        pose = {int(s): int(v) for s, v in k["positions"].items() if int(s) in BODY_IDS}
        if len(pose) != len(BODY_IDS):
            warns.append(f"incomplete body pose skipped: {k['name']}")
            continue
        if name == "rest":
            rest = pose
            continue
        hover = _HOVER.fullmatch(name)
        if hover:
            fret_no, string = map(int, hover.groups())
            if not (MIN_FRET <= fret_no <= MAX_FRET and 1 <= string <= 6) \
                    or (string, fret_no) in hovers:
                raise ValueError(f"invalid/duplicate arm-1 hover key: {k['name']}")
            hovers[(string, fret_no)] = pose
            continue
        m = _CELL.fullmatch(name)
        if not m:
            warns.append(f"unrecognized keyframe name skipped: {k['name']}")
            continue
        fret_no, string = int(m.group(1)), int(m.group(2))
        if not (MIN_FRET <= fret_no <= MAX_FRET and 1 <= string <= 6):
            warns.append(f"outside frets {MIN_FRET}-{MAX_FRET}, skipped: {k['name']}")
            continue
        if (string, fret_no) in cells:
            warns.append(f"duplicate for string {string} fret {fret_no} ignored: {k['name']}")
            continue
        cells[(string, fret_no)] = pose
    if rest is None:
        raise ValueError("no 'rest' keyframe for arm 1 — required as the safe hub")
    return {"cells": cells, "hovers": hovers, "rest": rest, "warns": warns}


def load_lift_first(keyframes_path=KEYFRAMES_PATH, calibration_path=CALIBRATION_PATH):
    """Load arm 1's reviewed lift-first registry, or refuse with the exact gap.

    -> (grid, ClearancePaths). Device-free; never invents hovers or routes.
    """
    raw = Path(keyframes_path).read_bytes()
    snapshot = load_map(entries=json.loads(raw))
    grid = (snapshot["cells"], snapshot["rest"], snapshot["warns"])
    if not snapshot["hovers"]:
        raise tap_paths.PathUnavailable(
            "no hover poses recorded for arm 1: record a hover-r{fret}-c{string} lift "
            "pose beside each contact (keep the contact's base yaw/wrist roll), then "
            "review lift/lower and hover-to-hover paths in calibration_arm1.json")
    try:
        calibration = json.loads(Path(calibration_path).read_text())
    except OSError:
        raise tap_paths.PathUnavailable(
            "paths not compiled: calibration_arm1.json is missing — record the operator "
            "lift-first path review there (see --path-template and PATHS.md)") from None
    paths = tap_paths.ClearancePaths.from_snapshot(
        snapshot, hashlib.sha256(raw).hexdigest(), calibration,
        body_ids=tuple(BODY_IDS), fret_rows=FRET_ROWS)
    return grid, paths


def path_template():
    """Read-only review draft for THIS arm's IDs. Never writes or moves an arm."""
    try:
        calibration = json.loads(CALIBRATION_PATH.read_text())
    except OSError:
        calibration = {}
    return {tap_paths.PROFILE: {
        "schema_version": tap_paths.SCHEMA,
        "keyframes_sha256": hashlib.sha256(KEYFRAMES_PATH.read_bytes()).hexdigest(),
        "calibration_sha256": tap_paths.calibration_digest(calibration),
        "motion_contract": tap_paths.motion_contract(tuple(BODY_IDS)),
        "qualified_at": "", "keys": [], "transit_edges": [],
    }}


class Arm1LiftFirst(fret.FretArm):
    """Lift-first executor for the upper arm — the ONLY arm-1 path the webapp uses.

    Inherits fret.FretArm's full lift-first semantics (every tap ends at its
    own hover, hover-to-hover travel over reviewed directed edges only, latched
    faults, halt freeze, torque policy) bound to THIS arm's body IDs via the
    generalized tap_paths registry. Grip 3 is absent from motor_ids and is
    never commanded. Refuses to construct without reviewed paths.
    """
    arm_id = SECONDARY

    def __init__(self, port=ARM1_PORT, baud=BAUD, *, grid=None, paths=None,
                 path_profile=None, halt=None):
        if grid is None and paths is None:
            grid, paths = load_lift_first()
        super().__init__(port, baud, grid=grid, paths=paths,
                         path_profile=path_profile, halt=halt)


def detect(port=ARM1_PORT, baud=BAUD):
    """Ping every joint, read temp/voltage. No motion. -> report dict."""
    def read1(bus, sid, addr):
        d = bus._txrx(sid, 0x02, [addr, 1], resp_extra=1)
        return None if d is None else d[0]

    bus = FeetechBus(port, baud)
    report = {}
    try:
        for sid in BODY_IDS + [GRIP_ID]:
            if not bus.ping(sid):
                report[sid] = {"alive": False}
                continue
            volt = read1(bus, sid, 62)
            report[sid] = {"alive": True, "position": bus.read_pos(sid),
                           "temp_c": read1(bus, sid, 63),
                           "voltage": volt / 10 if volt else None,
                           "torque": bus.read_torque(sid)}
    finally:
        bus.close()
    return report


class Arm1:
    """DEPRECATED rest-staged driver (rest -> contact -> rest, all joints at once).

    It does NOT enforce lift-before-lateral-travel and is NEVER used by the
    webapp/rehearsal pipeline. Only the CLI can still reach it, behind the
    explicit --unsafe-rest-staging flag, for supervised bring-up before hover
    poses exist. Default taps use Arm1LiftFirst.
    """
    halt = None

    def __init__(self, port=ARM1_PORT, baud=BAUD, *, halt=None):
        m = load_map()
        self.cells, self.rest_pose, self.warnings = m["cells"], m["rest"], m["warns"]
        self.bus = FeetechBus(port, baud)
        self.halt = halt
        try:
            alive = [sid for sid in BODY_IDS if self.bus.ping(sid)]
            if len(alive) < len(BODY_IDS):
                missing = [s for s in BODY_IDS if s not in alive]
                raise RuntimeError(f"arm-1 motors not responding: {missing} — "
                                   "NEVER tap with a partial arm (pose would be wrong)")
            check_supply_voltage(self.bus, alive)
            for sid in alive:
                self.bus.set_torque(sid, True)
        except Exception:
            self.close(torque_off=True)
            raise

    def close(self, torque_off=False):
        try:
            if torque_off:
                for sid in BODY_IDS:  # grip 3 untouched
                    try:
                        self.bus.set_torque(sid, False)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            self.bus.close()

    def _check_halt(self):
        if self.halt is not None and self.halt.is_set():
            for sid in BODY_IDS:
                try:
                    pos = self.bus.read_pos(sid)
                    if pos is not None:
                        self.bus.goto(sid, pos, speed=TRAVEL_SPEED, acc=ACC)
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError("force stop: arm 1 frozen mid-path, torque held")

    def _move(self, pose, speed, tol=SETTLE_TOL):
        self._check_halt()
        for sid, pos in pose.items():
            self.bus.goto(sid, pos, speed=speed, acc=ACC)
        deadline = time.monotonic() + SETTLE_TIMEOUT
        while time.monotonic() < deadline:
            self._check_halt()
            if all((p := self.bus.read_pos(sid)) is not None and abs(p - t) <= tol
                   for sid, t in pose.items()):
                return True
            time.sleep(0.03)
        raise TimeoutError("arm-1 encoder arrival timed out; state uncertain")

    def _cell(self, string, fret):
        if (string, fret) not in self.cells:
            raise ValueError(f"no arm-1 keypoint for string {string} fret {fret}; "
                             f"recorded: {sorted(self.cells)}")
        return self.cells[(string, fret)]

    def tap_key(self, string, fret):
        """Tap (string, fret 7-11): rest -> fast press -> rest. Scrape-safe."""
        s, f = int(string), int(fret)
        pose = self._cell(s, f)
        self._move(self.rest_pose, TRAVEL_SPEED)
        self._move(pose, TAP_SPEED, tol=PRESS_TOL)
        time.sleep(TAP_DWELL_S)
        self._move(self.rest_pose, TRAVEL_SPEED)
        return {"status": "command_completed", "arm": "upper", "string": s, "fret": f,
                "acoustic_success": "unknown", "contact_verified": False}

    def tap_sequence(self, keys, gap_s=0.3):
        results = []
        for s, f in keys:
            results.append(self.tap_key(s, f))
            if gap_s:
                time.sleep(gap_s)
        return results

    def rest(self):
        self._move(self.rest_pose, TRAVEL_SPEED)
        return {"status": "rest", "arm": "upper"}


# Tool surface for the upper arm — names are arm-scoped so they can coexist
# with fret.py's tools in one backend.
TOOLS = [
    {
        "name": "tap_key_upper",
        "description": "UPPER arm: tap one recorded key on frets 7-11 to sound "
                       "its note. String 1 = high E ... 6 = low E. Default motion "
                       "is lift-first (own hover -> tap -> own hover, reviewed "
                       "hover-to-hover transit); only recorded cells play "
                       "(r11 string 5 is not recorded yet).",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": MIN_FRET, "maximum": MAX_FRET},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "get_upper_fret_position",
        "description": "UPPER arm: raw servo targets for (string, fret 7-11) and "
                       "which upper cells are recorded. No motion.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": MIN_FRET, "maximum": MAX_FRET},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "upper_rest",
        "description": "UPPER arm to its recorded rest pose (parked, safe).",
        "parameters": {"type": "object", "properties": {}},
    },
]


def dispatch(arm, tool_name, args):
    """get_upper_fret_position works with arm=None (no hardware)."""
    if tool_name == "get_upper_fret_position":
        m = load_map()
        s, f = int(args["string"]), int(args["fret"])
        if (s, f) not in m["cells"]:
            return {"error": f"no upper keypoint for string {s} fret {f}",
                    "recorded_cells": sorted(m["cells"])}
        return {"string": s, "fret": f, "target_raw": m["cells"][(s, f)],
                "recorded_cells": sorted(m["cells"])}
    if tool_name == "tap_key_upper":
        return arm.tap_key(args["string"], args["fret"])
    if tool_name == "upper_rest":
        return arm.rest()
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Upper-neck arm (frets 7-11) CLI")
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pose", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--path-template", action="store_true",
                    help="print an UNQUALIFIED lift-first review draft for THIS arm's IDs; no writes/motion")
    ap.add_argument("--preview", nargs="+", metavar="S,F",
                    help="compile a lift-first phrase only; NO motion/devices")
    ap.add_argument("--tap", nargs=2, type=int, metavar=("STRING", "FRET"))
    ap.add_argument("--seq", nargs="+", metavar="S,F")
    ap.add_argument("--gap", type=float, default=0.3)
    ap.add_argument("--rest", action="store_true")
    ap.add_argument("--unsafe-rest-staging", action="store_true",
                    help="DEPRECATED: legacy rest->contact->rest taps that do NOT lift "
                         "before lateral travel. Supervised bring-up only; never the webapp path.")
    a = ap.parse_args()

    if a.detect:
        for sid, info in detect().items():
            print(f"  {sid} ({JOINT_NAMES[sid]}): {info}")
        raise SystemExit(0)
    if a.path_template:
        print(json.dumps(path_template(), indent=2))
        raise SystemExit(0)
    if a.preview:
        try:
            _, preview_paths = load_lift_first()
            print(json.dumps(preview_paths.compile(
                [tuple(int(x) for x in k.split(",")) for k in a.preview]), indent=2))
        except (ValueError, OSError) as exc:
            ap.error(f"Path blocked (no motion): {exc}")
        raise SystemExit(0)
    if a.list or a.pose:
        m = load_map()
        for w in m["warns"]:
            print("WARN:", w)
        if a.list:
            print(f"{len(m['cells'])} upper cells (string, fret): {sorted(m['cells'])}")
            print(f"hover pairs: {sorted(m['hovers'])}")
            print(f"rest: {m['rest']}")
        if a.pose:
            print(json.dumps(dispatch(None, "get_upper_fret_position",
                                      {"string": a.pose[0], "fret": a.pose[1]}), indent=2))
        raise SystemExit(0)

    if a.unsafe_rest_staging:
        print("WARNING: --unsafe-rest-staging uses the DEPRECATED rest-staged tap path. "
              "It does NOT lift before lateral travel and is never used by the webapp. "
              "Supervise closely; record hover poses and review lift-first paths instead.")
        arm = Arm1()
    else:
        try:
            arm1_grid, arm1_paths = load_lift_first()
        except (tap_paths.PathUnavailable, OSError, ValueError) as exc:
            ap.error(f"Lift-first taps unavailable for arm 1 (no motion started): {exc}\n"
                     "Record hover-r{fret}-c{string} poses and the calibration_arm1.json "
                     "review, or use --unsafe-rest-staging for supervised legacy bring-up.")
        arm = Arm1LiftFirst(grid=arm1_grid, paths=arm1_paths)
    for w in arm.warnings:
        print("WARN:", w)
    try:
        if a.tap:
            print(arm.tap_key(a.tap[0], a.tap[1]))
        if a.seq:
            for r in arm.tap_sequence([tuple(int(x) for x in k.split(",")) for k in a.seq], a.gap):
                print(r)
        if a.rest:
            print(arm.rest())
    finally:
        arm.close()
