"""Lift-first tapping for the currently working arm (body IDs 7-11).

THE PLUCK ARM (IDs 5,6,1,2,7,3) IS OUT OF SERVICE (2026-09-19). This arm is
the whole instrument now: it sounds notes by TAPPING the pre-recorded keys
(hammer-on style — press the string onto the fret fast, then lift). pluck.py
is retired; do not wire its tools into any backend.

v4 MAPPING (2026-09-19, rig physically re-positioned and fully re-recorded;
supersedes the v3 grid — old data lives in keyframes_arm2.backup-*.json):
  keyframes_arm2.json holds one keypoint per cell. Cell names accept the
  operator's v4 shorthand r{R}_{C} as well as the older pose-r{R}-c{C}:
    r = fret row (r1-r4 fully recorded plus r5_1, 25 current contacts)
    c = string/column, 1 = high E (rightmost) ... 6 = low E (leftmost)
  Values are RAW servo counts for IDs 7-11 — the played source of truth.
  The XYZ/degrees enrichment is dormant until a new kinematic reference is
  captured (the old one predates the move and was removed). 'rest' is the
  recorded entry/park pose. Each used cell also needs 'hover-r{R}-c{C}' and
  a local path review; rest-r{R}/neutral cannot substitute for key hovers.
  Future tap_secondary owns rows 7-11, but has NO connection/poses here.
  GRIPPER 12 NEVER commanded.

=== LIFT-FIRST EXECUTION ====================================================
Contact-only rest/row-hub playback is retired: sending every joint toward a
hub does not ensure that the fingertip lifts before lateral travel. Playback
now requires reviewed contact/hover pairs and directed clearance transitions
(tap_paths.py, PATHS.md). Every tap ends at its OWN hover; the next travels
only after encoder arrival, never through global rest between notes. Missing
hover/qualification/route data blocks before connection, with no guessed
height, old-map fallback, or LLM waypoint generation. Recorded/reviewed paths
still are not a software proof of collision-free physical motion.
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
  uv run --with pyserial python fret.py --preview 1,1 1,2  # whole path, NO motion
  uv run --with pyserial python fret.py --path-template   # UNQUALIFIED draft only
Legacy row-hub sweep and contact-only extra-pose playback are blocked, not fallback paths.
"""
import hashlib
import json
import math
import re
import time
from pathlib import Path

from app import FeetechBus
from tap_arms import PRIMARY, ROW_OWNERS
from tap_paths import (
    ACC, BODY_IDS, CLEARANCE_DWELL_S, PRESS_SPEED, PRESS_TOL, PROFILE,
    SETTLE_TIMEOUT, SETTLE_TOL, TAP_DWELL_S, TAP_SPEED, TRAVEL_SPEED,
    SCHEMA, ClearancePaths, PathUnavailable, calibration_digest, contact_name,
    hover_name, motion_contract,
)

FRET_PORT = "/dev/cu.wchusbserial5B8E1128501"  # re-enumerates on replug — check ls /dev/cu.*
BAUD = 1_000_000

KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm2.json"

MOTOR_IDS = list(BODY_IDS)  # gripper 12 deliberately absent
STRING_NOTES = {1: "E4", 2: "B3", 3: "G3", 4: "D3", 5: "A2", 6: "E2"}
# Primary-arm v4 grid: rows r1-r4 across six strings plus r5_1. Recording
# availability and separate clearance review, not this bound, admit motion.
MAX_FRET = 5

# Existing speeds, tolerances and contact dwell live in tap_paths.py so their
# exact values are bound into the path-review fingerprint. They are unchanged.

_CELL = re.compile(r"pose[-_]?r(\d+)[-_]?c(\d+)$")
_CELL_T = re.compile(r"pose[-_]?c(\d+)[-_]?r(\d+)$")  # transposed name variant
_CELL_SHORT = re.compile(r"r(\d+)[-_](\d+)$")  # v4 operator shorthand: r{fret}_{string}
_ROW_REST = re.compile(r"rest[-_]?r(\d+)$")
_HOVER = re.compile(r"hover[-_]?r(\d+)[-_]?c(\d+)$")


def load_map(path=KEYFRAMES_PATH, max_fret=MAX_FRET, *, entries=None):
    """-> {"cells": {(string, fret): raw_pose}, "hovers": {(string, fret): raw_pose},
           "rest": pose, "row_rests": {fret: pose}, "xyz": {(string, fret): xyz_cm dict},
           "degrees": {(string, fret): {sid: deg}}, "warns": [str]}

    entries optionally supplies an already-read local snapshot (never model data).
    """
    cells, hovers, xyz, degrees, row_rests, extras, rest, warns = {}, {}, {}, {}, {}, {}, None, []
    for k in entries if entries is not None else json.loads(Path(path).read_text()):
        name = k["name"].strip().lower()
        positions = k["positions"]
        if (set(positions) != {str(j) for j in MOTOR_IDS}
                or any(type(v) is not int or not 0 <= v <= 4095 for v in positions.values())):
            raise ValueError("Keyframes must contain complete raw body poses, IDs 7–11 only")
        pose = {int(sid): v for sid, v in positions.items()}
        if name == "rest":
            if rest is not None:
                raise ValueError("duplicate rest keyframe")
            rest = pose
            continue
        rr = _ROW_REST.fullmatch(name)
        if rr:
            row_rests[int(rr.group(1))] = pose
            continue
        hover = _HOVER.fullmatch(name)
        if hover:
            r, c = map(int, hover.groups())
            if not (1 <= r <= max_fret and 1 <= c <= 6) or (c, r) in hovers:
                raise ValueError(f"invalid/duplicate hover key: {k['name']}")
            hovers[(c, r)] = pose
            continue
        m = _CELL.fullmatch(name) or _CELL_T.fullmatch(name) or _CELL_SHORT.fullmatch(name)
        if not m:
            if name.startswith(("pose", "rest", "hover")):  # near-miss of a grid name: flag it
                warns.append(f"unrecognized keyframe name skipped: {k['name']}")
            elif len(pose) == len(MOTOR_IDS):
                # operator-recorded extra pose (e.g. 'neutral' or the SNA frets)
                extras[name] = pose
            continue
        r, c = (int(m.group(2)), int(m.group(1))) if _CELL_T.fullmatch(name) else \
               (int(m.group(1)), int(m.group(2)))
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
        raise ValueError("no 'rest' keyframe in the grid — required as the reviewed entry/exit pose")
    return {"cells": cells, "hovers": hovers, "rest": rest, "row_rests": row_rests,
            "xyz": xyz, "degrees": degrees, "extras": extras, "warns": warns}


def load_grid(path=KEYFRAMES_PATH, max_fret=MAX_FRET, *, entries=None):
    """Back-compat view: -> (cells, rest_pose, warnings)."""
    m = load_map(path, max_fret, entries=entries)
    return m["cells"], m["rest"], m["warns"]


class Halted(RuntimeError):
    """Force stop: motion was frozen at the present position, torque left ON so
    the arm holds instead of dropping. NOT a hardware E-stop — the freeze is
    commanded over the same serial link; if the link/driver is wedged, cut
    servo power physically. Recovery: move to rest from /calibrate or the GUI."""


class FretArm:
    arm_id = PRIMARY
    halt = None
    path_profile = PROFILE
    motion_fault = None

    def __init__(self, port=FRET_PORT, baud=BAUD, *, grid=None, row_rests=None,
                 path_profile=None, paths=None, halt=None):
        """Connect only with a reviewed lift-first path registry, never model poses.

        The arm must already be at its recorded entry/rest pose. Unknown start
        positions are refused, not automatically homed across the strings.
        halt freezes body goals at their current positions; it is not a hardware E-stop.
        """
        self.path_profile = path_profile or PROFILE
        if self.path_profile != PROFILE:
            raise PathUnavailable("Hub-only playback is disabled: it does not enforce lift before lateral travel")
        if grid is None:
            import kinematics
            raw = KEYFRAMES_PATH.read_bytes()
            snapshot = load_map(entries=json.loads(raw))
            grid = (snapshot["cells"], snapshot["rest"], snapshot["warns"])
            paths = ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(),
                                                 json.loads(kinematics.CAL_PATH.read_text()))
        if not isinstance(paths, ClearancePaths):
            raise PathUnavailable("A current operator-reviewed lift-first registry is required before connection")
        self.cells, self.rest_pose, self.warnings = grid
        if (paths.pose("rest") != self.rest_pose
                or any(paths.pose(contact_name(k)) != self.cells.get(k) for k in paths.keys)):
            raise PathUnavailable("Contact snapshot and reviewed lift-first paths disagree")
        self.paths, self.halt = paths, halt
        self.xyz, self.extras, self.row_rests = {}, {}, {}
        self.holding, self.last_row, self.location = None, None, "rest"
        self.motion_fault = None
        self.bus = FeetechBus(port, baud)
        wrote_goals = False
        try:
            alive = [sid for sid in MOTOR_IDS if self.bus.ping(sid)]
            if len(alive) < len(MOTOR_IDS):
                raise RuntimeError(f"fret arm motors responding: {alive} of {MOTOR_IDS} — check power")
            present = self._require_at("rest")  # no goal/torque write on unknown starting state
            self._check_halt()
            # Hold fresh positions, never re-enable torque against stale servo goals.
            wrote_goals = True
            for sid in MOTOR_IDS:
                self.bus.goto(sid, present[sid], speed=TRAVEL_SPEED, acc=ACC)
            for sid in MOTOR_IDS:
                self.bus.set_torque(sid, True)
        except Exception:
            self.close(torque_off=wrote_goals)  # body only; no movement or grip reassertion
            raise

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

    def _freeze(self):
        """Overwrite every goal with the present position: the servo holds where
        it is right now. Best-effort per motor; torque is deliberately left ON."""
        for sid in MOTOR_IDS:
            try:
                pos = self.bus.read_pos(sid)
                if pos is not None:
                    self.bus.goto(sid, pos, speed=TRAVEL_SPEED, acc=ACC)
            except Exception:  # noqa: BLE001 - freeze the remaining motors regardless
                pass

    def _check_halt(self):
        if self.halt is not None and self.halt.is_set():
            self._freeze()
            raise Halted("force stop: arm frozen mid-path, torque held")

    def _move(self, pose, speed, wait=True, *, deadline=None, tol=SETTLE_TOL, settle_s=0):
        if set(pose) != set(MOTOR_IDS) or any(type(v) is not int or not 0 <= v <= 4095
                                            for v in pose.values()):
            raise ValueError("A complete recorded body-joint pose is required")
        if self.motion_fault:
            raise PathUnavailable("Motion fault is latched; inspect rather than retry or home")
        try:
            self._check_halt()
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Attempt deadline reached before a motion stage")
            for sid, pos in pose.items():
                self.bus.goto(sid, pos, speed=speed, acc=ACC)
            if wait:
                stage_deadline = time.monotonic() + SETTLE_TIMEOUT
                if deadline is not None:
                    stage_deadline = min(stage_deadline, deadline)
                settled_since = None
                while time.monotonic() < stage_deadline:
                    self._check_halt()
                    now = time.monotonic()
                    positions = {sid: self.bus.read_pos(sid) for sid in MOTOR_IDS}
                    at_target = all(type(positions[sid]) is int and abs(positions[sid] - t) <= tol
                                    for sid, t in pose.items())
                    settled_since = (now if settled_since is None else settled_since) if at_target else None
                    if settled_since is not None and now - settled_since >= settle_s:
                        return True  # encoder criterion only, NOT proof of string clearance
                    time.sleep(0.03)
                raise TimeoutError("Encoder arrival timed out; state uncertain")
            return False
        except Exception as exc:
            self.motion_fault = type(exc).__name__
            raise

    def _require_at(self, name, tol=SETTLE_TOL):
        if self.motion_fault:
            raise PathUnavailable("Motion fault is latched; no automatic recovery")
        pose = self.paths.pose(name)
        try:
            positions = {sid: self.bus.read_pos(sid) for sid in MOTOR_IDS}
        except Exception:
            self.motion_fault = "position_read_failed"
            raise
        if any(type(positions[sid]) is not int or abs(positions[sid] - t) > tol
               for sid, t in pose.items()):
            self.motion_fault = "unexpected_position"
            raise PathUnavailable(f"Arm is not at the expected {name}; inspect/reposition before a new session")
        return positions

    def _cell(self, string, fret):
        if (string, fret) not in self.cells:
            have = sorted(self.cells)
            raise ValueError(f"no keypoint for string {string} fret {fret}; "
                             f"recorded cells (string, fret): {have}")
        return self.cells[(string, fret)]

    def _lift(self, *, deadline=None, stages=None, started=None):
        """Finish the CURRENT key's reviewed lift before allowing any travel."""
        if self.holding is not None:
            self._require_at(contact_name(self.holding), PRESS_TOL)
            self._named_stage("lift_clear", hover_name(self.holding), TRAVEL_SPEED,
                              deadline=deadline, stages=stages, started=started)
            self.holding = None
        else:
            self._require_at(self.location)

    def _named_stage(self, kind, name, speed, *, deadline=None, stages=None, started=None):
        command = time.monotonic()
        target = self.paths.pose(name)
        staged_lift = False
        if kind == "lift_clear":
            # Staged lift (operator directives 2026-09-20). Raising the shoulder
            # straight from a pressed contact pries the fingertip against the
            # string it is pressing and can stall (observed: s5f2 timeout), so
            # the lift is two-phase: (1) RELEASE the press — elbow/wrist-flex
            # (9, 10) to their hover values, a short vertical un-press — then
            # (2) the shoulder rises with the rest of the pose. Yaw/roll (7, 11)
            # never move during either phase, so there is still no sideways
            # sweep near the strings. Interim goals hold non-lifting joints at
            # their present readings; endpoints remain the reviewed poses only.
            held = {}
            for sid in MOTOR_IDS:
                for _ in range(5):
                    p = self.bus.read_pos(sid)
                    if p is not None:
                        held[sid] = p
                        break
            if set(held) == set(MOTOR_IDS):
                staged_lift = True
                self._move({**held, 9: target[9], 10: target[10]}, speed,
                           deadline=deadline, tol=PRESS_TOL,
                           settle_s=CLEARANCE_DWELL_S)
        self._move(target, speed, deadline=deadline,
                   tol=PRESS_TOL if kind in {"tap", "press"} else SETTLE_TOL,
                   settle_s=0 if kind in {"tap", "press"} else CLEARANCE_DWELL_S)
        self.location = name  # never advance symbolic state on timeout/fault
        if stages is not None:
            stages.append({"stage": kind, "pose": name, "staged_lift": staged_lift,
                           "command_start_s": round(command - started, 4),
                           "encoder_ready_s": round(time.monotonic() - started, 4)})

    def _approach(self, key, *, deadline=None, stages=None, started=None):
        # Validate both this target AND its entry/exit before any release/motion.
        self.paths.compile([key])
        source = hover_name(self.holding) if self.holding else self.location
        route = self.paths.route(source, hover_name(key))
        self._lift(deadline=deadline, stages=stages, started=started)
        for node in route:
            self._named_stage("travel", node, TRAVEL_SPEED, deadline=deadline,
                              stages=stages, started=started)
        self._require_at(hover_name(key))

    # ---- tools ----------------------------------------------------------

    def tap_key(self, string, fret, *, deadline=None):
        """Own hover -> tap -> own hover; next key travels without neutral.

        The next stage cannot begin until the previous lift's continuous encoder
        arrival check completes. This is not a contact/clearance sensor. All
        segments need prior operator review; missing paths never get a fallback.
        """
        if type(string) is not int or type(fret) is not int:
            raise ValueError("Key indices must be integers")
        key = (string, fret)
        self._cell(*key)
        started, stages = time.monotonic(), []
        self._approach(key, deadline=deadline, stages=stages, started=started)
        self._named_stage("tap", contact_name(key), TAP_SPEED, deadline=deadline,
                          stages=stages, started=started)
        self.holding = key
        time.sleep(TAP_DWELL_S)
        self._lift(deadline=deadline, stages=stages, started=started)
        self.last_row = fret
        return {"status": "command_completed", "arm": self.arm_id, "string": string, "fret": fret,
                "note_open": STRING_NOTES.get(string), "stages": stages,
                "path_profile": self.path_profile,
                "acoustic_success": "unknown", "contact_verified": False}

    def tap_sequence(self, keys, gap_s=0.3):
        """Tap several (string, fret) keys in order with a fixed gap."""
        if type(gap_s) not in (int, float) or not math.isfinite(gap_s) or not 0 <= gap_s <= 2:
            raise ValueError("Sequence gap must be finite, 0–2 seconds")
        keys = tuple(keys)
        self.paths.compile(keys)  # all transitions admitted before the first tap
        results = []
        for s, f in keys:
            results.append(self.tap_key(s, f))
            if gap_s:
                time.sleep(gap_s)
        return results

    def tap_pose(self, name, *, deadline=None):
        """Extra contact-only poses cannot bypass the lift-first path contract."""
        raise PathUnavailable("Extra-pose taps have no reviewed contact/hover paths; use qualified grid keys")

    def play_riff(self, riff, default_gap_s=0.25):
        """Tap a riff of (extra_pose_name, gap_after_s) pairs, rest-staged."""
        missing = sorted({str(n).strip().lower() for n, _ in riff} - set(self.extras))
        if missing:
            raise ValueError(f"riff needs extra poses that are not recorded: {missing}")
        results = []
        for name, gap in riff:
            results.append(self.tap_pose(name))
            time.sleep(gap if gap is not None else default_gap_s)
        return results

    def hold_fret(self, string, fret):
        """Operator-only quiet hold; approach via the key's reviewed hover."""
        key = (string, fret)
        self._cell(*key)
        self._approach(key)
        self._named_stage("press", contact_name(key), PRESS_SPEED)
        self.holding, self.last_row = key, fret
        return {"status": "holding", "string": string, "fret": fret,
                "note_open": STRING_NOTES.get(string)}

    def release_fret(self):
        """Lift to this key's own hover, NEVER global neutral or gripper open."""
        was = self.holding
        self._lift()
        return {"status": "released", "was_holding": was}

    def rest(self, *, deadline=None):
        """Explicit end parking via reviewed exits; never a between-note route."""
        source = hover_name(self.holding) if self.holding else self.location
        route = self.paths.route(source, "rest")
        self._lift(deadline=deadline)
        for node in route:
            self._named_stage("exit", node, TRAVEL_SPEED, deadline=deadline)
        self.holding, self.last_row = None, None
        return {"status": "rest"}


# Seven Nation Army, low-E frets, using the operator's recorded extra poses
# named "2","3","5","7","10". (name, gap_after_s); None = the default gap.
SNA_RIFF = [("7", None), ("7", None), ("10", None), ("7", None), ("5", None),
            ("3", None), ("2", 0.6),
            ("7", None), ("7", None), ("10", None), ("7", None), ("5", None),
            ("3", None), ("5", None), ("3", None), ("2", 0.6)]


def qualify_row_hubs(arm):
    """Retired: a hub sweep does not establish a separate per-key lift phase."""
    raise PathUnavailable("Row-hub qualification is retired; review a small contact/hover subset per PATHS.md")


def record_row_hub_qualification():
    raise PathUnavailable("Row-hub approval cannot qualify lift_first; no calibration written")


def path_template():
    """Read-only draft with NO approved keys/edges. Never writes or moves an arm."""
    import kinematics
    calibration = json.loads(kinematics.CAL_PATH.read_text())
    return {PROFILE: {
        "schema_version": SCHEMA,
        "keyframes_sha256": hashlib.sha256(KEYFRAMES_PATH.read_bytes()).hexdigest(),
        "calibration_sha256": calibration_digest(calibration),
        "motion_contract": motion_contract(), "qualified_at": "",
        "keys": [], "transit_edges": [],
    }}


# Model-callable primary tap surface. Quiet holds and global parking are local/
# operator-only, not model choices between notes. Retired pluck tools stay absent.
TOOLS = [
    {
        "name": "tap_key",
        "description": "Tap one pre-recorded key (fast press from its own hover, "
                       "brief dwell, lift back to that key's hover). This is "
                       "the only way this rig makes sound. String 1 = high E "
                       "(rightmost) ... 6 = low E (leftmost); frets 1-4 recorded "
                       "(schema allows 5 for future rows; only RECORDED cells play "
                       "— check get_fret_position). "
                       "Transit finishes the current lift before taking the shortest "
                       "reviewed hover route. No neutral between notes. Missing paths "
                       "are rejected, never generated from coordinates or model output.",
        "parameters": {
            "type": "object",
            "properties": {
                "string": {"type": "integer", "minimum": 1, "maximum": 6},
                "fret": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["string", "fret"],
        },
    },
    {
        "name": "tap_sequence",
        "description": "Tap several keys in order with a fixed gap between taps. "
                       "Whole-sequence lift-first path admission before the first tap.",
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
                "gap_s": {"type": "number", "default": 0.3, "minimum": 0, "maximum": 2,
                          "description": "bounded seconds after each completed tap/lift"},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "release_fret",
        "description": "Lift the fingertip to the current key's recorded hover. "
                       "Does not park at global rest or open the gripper.",
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
                "fret": {"type": "integer", "minimum": 1, "maximum": 5},
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
]


# Models must name an owner even while only one arm is enabled. In particular,
# adding a future tap_secondary enum must not silently dispatch it to this bus.
for _tool in TOOLS:
    _parameters = _tool["parameters"]
    _parameters["properties"]["arm"] = {
        "type": "string", "enum": [PRIMARY],
        "description": "Working tap arm only. Secondary rows 7–11 are unavailable; no reassignment."}
    _parameters["required"] = ["arm", *_parameters.get("required", [])]
    _parameters["additionalProperties"] = False


def dispatch(arm, tool_name, args):
    """Primary-owned tools only; read-only position tools also require ownership."""
    definition = next((t for t in TOOLS if t["name"] == tool_name), None)
    if definition is None:
        raise ValueError(f"unknown tool {tool_name}")
    schema = definition["parameters"]
    if (not isinstance(args, dict) or set(args) - set(schema["properties"])
            or set(schema["required"]) - set(args)):
        raise ValueError("Tool arguments must match the declared fields, including explicit arm ownership")
    if args["arm"] != PRIMARY or (arm is not None and getattr(arm, "arm_id", None) != PRIMARY):
        raise ValueError("Only tap_primary is enabled; never route a secondary-arm task onto this bus")
    if tool_name == "tap_key" and args["fret"] not in ROW_OWNERS[PRIMARY]:
        raise ValueError("tap_primary does not own that fret row")
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
        return arm.tap_sequence(args["keys"], args.get("gap_s", 0.3))
    if tool_name == "release_fret":
        return arm.release_fret()
    raise ValueError(f"unknown tool {tool_name}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Primary tap arm: recorded keys + reviewed lift-first paths")
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
    ap.add_argument("--profile", choices=["auto", "lift_first", "rest_hub", "row_hub"], default="auto",
                    help="auto selects lift_first; legacy hub-only profiles are refused")
    ap.add_argument("--preview", nargs="+", metavar="S,F", help="compile named paths only; NO motion/devices")
    ap.add_argument("--path-template", action="store_true", help="print an UNQUALIFIED review draft; no writes/motion")
    ap.add_argument("--sna", action="store_true",
                    help="play the Seven Nation Army riff on the recorded low-E "
                         "extra poses (2/3/5/7/10)")
    ap.add_argument("--pose-name", metavar="NAME",
                    help="tap one recorded extra pose by name (e.g. 7)")
    ap.add_argument("--qualify-row-hubs", action="store_true",
                    help="supervised slow walk of all row_hub motions, then record "
                         "the operator's qualification decision")
    a = ap.parse_args()

    if a.path_template:
        print(json.dumps(path_template(), indent=2))
        raise SystemExit(0)
    if a.qualify_row_hubs:
        ap.error("Row-hub sweep retired. Record/review a small lift-first subset; see PATHS.md. No motion started.")
    if a.preview:
        import kinematics
        try:
            raw = KEYFRAMES_PATH.read_bytes()
            paths = ClearancePaths.from_snapshot(load_map(entries=json.loads(raw)), hashlib.sha256(raw).hexdigest(),
                                                 json.loads(kinematics.CAL_PATH.read_text()))
            print(json.dumps(paths.compile([tuple(map(int, k.split(","))) for k in a.preview]), indent=2))
        except (ValueError, OSError) as exc:
            ap.error(f"Path blocked (no motion): {exc}")
        raise SystemExit(0)

    if a.list or a.pose or a.estimate:
        m = load_map()
        for w in m["warns"]:
            print("WARN:", w)
        if a.list:
            print(f"{len(m['cells'])} cells recorded (string, fret): {sorted(m['cells'])}")
            print(f"hover pairs: {sorted(m['hovers'])}; legacy row hubs: {sorted(m['row_rests'])}")
            print(f"extra poses: {sorted(m['extras'])}")
        if a.pose:
            print(json.dumps(dispatch(None, "get_fret_position",
                                      {"arm": PRIMARY, "string": a.pose[0], "fret": a.pose[1]}), indent=2))
        if a.estimate:
            print(json.dumps(dispatch(None, "estimate_position",
                                      {"arm": PRIMARY, "string": a.estimate[0], "fret": a.estimate[1]}),
                             indent=2))
        raise SystemExit(0)

    arm = FretArm(path_profile=None if a.profile == "auto" else a.profile)
    for w in arm.warnings:
        print("WARN:", w)
    try:
        if a.sna:
            print(f"Seven Nation Army — {len(SNA_RIFF)} taps on low-E poses "
                  f"{sorted(set(n for n, _ in SNA_RIFF), key=int)}")
            for r in arm.play_riff(SNA_RIFF, default_gap_s=max(a.gap, 0.05)):
                print(r)
        if a.pose_name:
            print(arm.tap_pose(a.pose_name))
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
