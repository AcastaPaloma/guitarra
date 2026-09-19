"""The only path from the agent to the servos: named poses -> interpolation -> guards -> bus.

    arm = RealArm(port, arm_id="fret_arm", motor_id_offset=6)   # or FakeArm("fret_arm")
    arm.connect()
    arm.fret(string=5, fret=7, press_mm=2, speed=0.5)
    arm.release()
    arm.disconnect()
"""
import json
import logging
import time

import numpy as np

from . import fretmap
from . import poses as pose_store
from .guards import (JOINTS, GuardError, Limits, Pose, calibrated_box, calibration_problems, check_at,
                     check_segments, check_trajectory, workspace_box)

log = logging.getLogger(__name__)

CONTROL_HZ = 50
MAX_DEG_PER_S = 120.0     # at speed=1.0; the model can only scale this down
WORKSPACE_MARGIN_DEG = 5.0
AT_TOLERANCE_DEG = 6.0    # how far the arm may be from where we left it before we refuse to move
TRACKING_LIMIT_DEG = 12.0 # a joint lagging its command by more than this = blocked / hit something
TRACK_EVERY = 5           # check tracking every N control steps (10 Hz)
BASE = "shoulder_pan"
BASE_EPS_DEG = 0.3        # base changes smaller than this ride along with the other joints
MAX_DEPTH_MM = 15.0


def interpolate(a: Pose, b: Pose, max_deg_per_s: float, hz: int = CONTROL_HZ) -> list[Pose]:
    """Straight line in joint space, sampled at hz, as fast as the slowest-allowed joint permits."""
    span = max(abs(b[j] - a[j]) for j in JOINTS if j != "gripper")
    n = max(1, int(np.ceil(span / max_deg_per_s * hz)))
    return [{j: a[j] + (b[j] - a[j]) * (i / n) for j in JOINTS} for i in range(1, n + 1)]


class Arm:
    """Pose-table arm. Subclasses provide _read() and _send()."""

    def __init__(self, arm_id: str):
        self._clock = time  # unchanged wall clock for hardware; FakeArm may use a virtual clock
        self.arm_id = arm_id
        data = pose_store.load(arm_id)
        self.poses: dict[str, Pose] = data["poses"]
        self.depth = data["depth"]
        self.limits: Limits | None = None
        self.last_cmd: Pose | None = None
        self.pressing: tuple[int, int] | None = None   # fretting arm: (string, fret) held down

    # -- subclass hooks ---------------------------------------------------------------
    def _read(self) -> Pose: ...
    def _send(self, q: Pose) -> None: ...
    def _hard_box(self) -> dict: ...
    def _before_motion(self) -> None: ...

    def _check_tracking(self, commanded: Pose) -> None:
        """Stop the moment a joint falls far behind its command: that is what a collision looks
        like, and stopping here beats pushing until the servo overloads."""
        now = self._read()
        lag = {j: commanded[j] - now[j] for j in JOINTS if j != "gripper"
               and abs(commanded[j] - now[j]) > TRACKING_LIMIT_DEG}
        if lag:
            self._hold(now)
            self.last_cmd = now
            raise GuardError("motion stopped - blocked or hit something: "
                             + ", ".join(f"{j} {d:+.0f} deg behind" for j, d in lag.items()))

    def _hold(self, q: Pose) -> None:
        self._send(q)

    def _in_fret_region(self) -> bool:
        name, err = pose_store.nearest(self.poses, self._read())
        return err <= AT_TOLERANCE_DEG * 2 and (name.startswith(("above_s", "touch_s")) or name == "ready")

    def connect(self) -> None:
        extra = {self.depth["joint"]: MAX_DEPTH_MM * abs(self.depth["deg_per_mm"])}
        # fretting presses extrapolate past `touch` along the approach; let the box allow the deepest one
        k = fretmap.MAX_PRESS_MM / fretmap.HOVER_MM
        for s, frets in fretmap.available(self.poses).items():
            for f in frets:
                a, t = self.poses[fretmap.name("above", s, f)], self.poses[fretmap.name("touch", s, f)]
                for j in JOINTS:
                    extra[j] = max(extra.get(j, 0.0), k * abs(t[j] - a[j]))
        self.limits = Limits(
            hard=self._hard_box(),
            workspace=workspace_box(self.poses, WORKSPACE_MARGIN_DEG, extra),
            max_deg_per_s=MAX_DEG_PER_S,
        )
        self.last_cmd = self._read()

    # -- state ------------------------------------------------------------------------
    def state(self) -> dict:
        q = self._read()
        name, err = pose_store.nearest(self.poses, q)
        out = {"at": name if err <= AT_TOLERANCE_DEG else f"between poses (nearest {name}, {err:.0f} deg off)",
               "gripper": round(q["gripper"], 1)}
        if self.pressing is not None:
            out["at"] = f"pressing string {self.pressing[0]} fret {self.pressing[1]}"
        return out

    # -- motion -----------------------------------------------------------------------
    def _execute(self, waypoints: list[Pose], speed: float) -> dict:
        """Plan through all waypoints, guard the whole plan, then run it. Returns timing info.

        Each waypoint runs base-first: the base turns on its own (other joints holding), then the
        other joints move (base holding). The fret arm's base can only be driven that way (speed
        mode, robot/base_speed.py), and it keeps travel at the current height: lift, turn, lower.
        """
        speed = float(np.clip(speed, 0.2, 1.0))
        start = self._read()
        check_at(self.last_cmd, start, AT_TOLERANCE_DEG)
        # the gripper is a clamp holding the tool, never part of a motion
        waypoints = [dict(wp, gripper=start["gripper"]) for wp in waypoints]
        segments, cur = [], start
        for wp in waypoints:
            if abs(wp[BASE] - cur[BASE]) > BASE_EPS_DEG:
                turned = dict(cur, **{BASE: wp[BASE]})
                segments.append(("base", cur, turned))
                cur = turned
            segments.append(("joints", cur, wp))
            cur = wp
        check_segments([start] + [seg[2] for seg in segments])
        plans = [(kind, interpolate(a, b, MAX_DEG_PER_S * speed)) for kind, a, b in segments]
        check_trajectory([start] + [q for _, traj in plans for q in traj], self.limits, dt=1 / CONTROL_HZ)
        self._before_motion()  # no servo writes until the complete trajectory passes

        t_cmd = None
        for kind, traj in plans:
            if kind == "base":
                self._move_base(traj, speed)
                self.last_cmd = traj[-1]
                continue
            t_seg = self._clock.monotonic()
            t_cmd = t_seg if t_cmd is None else t_cmd
            next_t = t_seg
            for i, q in enumerate(traj):
                self._send(q)
                if i >= 3 and i % TRACK_EVERY == 0:
                    self._check_tracking(traj[i - 3])   # servos trail the command by a few steps
                next_t += 1 / CONTROL_HZ
                self._clock.sleep(max(0.0, next_t - self._clock.monotonic()))
            self.last_cmd = traj[-1]
        t_cmd = self._clock.monotonic() if t_cmd is None else t_cmd
        self._clock.sleep(0.15)  # let the servos settle before anyone reads position
        steps = sum(len(traj) for _, traj in plans)
        return {"t_cmd": t_cmd, "duration_s": round(self._clock.monotonic() - t_cmd, 2), "steps": steps}

    def _move_base(self, traj: list[Pose], speed: float) -> None:
        """Turn the base along a base-only segment. Default: stream it like any other joint."""
        next_t = self._clock.monotonic()
        for i, q in enumerate(traj):
            self._send(q)
            if i >= 3 and i % TRACK_EVERY == 0:
                self._check_tracking(traj[i - 3])
            next_t += 1 / CONTROL_HZ
            self._clock.sleep(max(0.0, next_t - self._clock.monotonic()))

    def move_to(self, pose: str, speed: float = 0.4) -> dict:
        if self.pressing is not None:
            raise GuardError(f"holding fret {self.pressing} - call release first (never drag along the string)")
        if pose not in self.poses:
            raise GuardError(f"unknown pose '{pose}'. known: {sorted(self.poses)}")
        return self._execute([self.poses[pose]], speed)

    def pluck(self, depth_mm: float, speed: float = 0.5) -> dict:
        """above_string -> pluck_start pushed depth_mm into the string -> pluck_end -> above_string."""
        for p in ("above_string", "pluck_start", "pluck_end"):
            if p not in self.poses:
                raise GuardError(f"pose '{p}' not recorded")
        start = self._offset(self.poses["pluck_start"], depth_mm)
        end = self._offset(self.poses["pluck_end"], depth_mm)
        # approach and retreat slowly; only the stroke itself uses the requested speed
        info = self._execute([self.poses["above_string"], start], speed=0.4)
        stroke = self._execute([end], speed)
        self._execute([self.poses["above_string"]], speed=0.4)
        return {**stroke, "approach_s": info["duration_s"]}

    def _offset(self, pose: Pose, mm: float) -> Pose:
        q = dict(pose)
        q[self.depth["joint"]] += float(np.clip(mm, 0.0, MAX_DEPTH_MM)) * self.depth["deg_per_mm"]
        return q

    def fret(self, string: int, fret: int, press_mm: float, speed: float = 0.4) -> dict:
        """Press `string` just behind `fret`: lift off any held fret, hover, lower, press.

        Travel always happens at hover height, never dragging along the strings. The press
        continues along the recorded above->touch approach (robot/fretmap.py).
        """
        above, touch = fretmap.name("above", string, fret), fretmap.name("touch", string, fret)
        if above not in self.poses or touch not in self.poses:
            raise GuardError(f"string {string} fret {fret} not calibrated. calibrated: {fretmap.available(self.poses)}")
        press_mm = float(np.clip(press_mm, 0.0, fretmap.MAX_PRESS_MM))
        path = []
        if self.pressing is not None:
            path.append(self.poses[fretmap.name("above", *self.pressing)])
        elif not self._in_fret_region():
            if "ready" not in self.poses:   # never swing straight from rest onto the neck
                raise GuardError("not over the fretboard and no 'ready' pose recorded - "
                                 "run scripts/record_poses.py --role fret rest ready")
            path.append(self.poses["ready"])   # coming from rest / elsewhere: enter via the hover pose
        path += [self.poses[above], self.poses[touch],
                 fretmap.press_pose(self.poses[above], self.poses[touch], press_mm)]
        info = self._execute(path, speed)
        self.pressing = (string, fret)
        return info

    def release(self, speed: float = 0.4) -> dict:
        if self.pressing is None:
            return {"steps": 0}
        info = self._execute([self.poses[fretmap.name("above", *self.pressing)]], speed)
        self.pressing = None
        return info

    def rest(self) -> None:
        if self.pressing is not None:
            self.release(speed=0.3)
        if "ready" in self.poses and self._in_fret_region():
            self._execute([self.poses["ready"]], speed=0.3)   # leave the fretboard the way we came
        if "rest" in self.poses:
            self._execute([self.poses["rest"]], speed=0.3)

    def disconnect(self) -> None: ...


class RealArm(Arm):
    def __init__(self, port: str, arm_id: str, motor_id_offset: int = 0, *, base_mode: str = "speed"):
        # Keep the legacy default for existing scripts. New callers should choose explicitly:
        # position for a working servo; speed only for the documented faulty-servo workaround.
        if base_mode not in ("position", "speed"):
            raise ValueError("base_mode must be 'position' or 'speed'")
        self.base_mode = base_mode
        self.base = None
        super().__init__(arm_id)
        from lerobot_robot_astra import AstraSO101, AstraSO101Config

        # max_relative_target: LeRobot's own per-command cap, a second net under our guards
        self.robot = AstraSO101(AstraSO101Config(
            port=port, id=arm_id, motor_id_offset=motor_id_offset, max_relative_target=15.0,
            clamp_gripper=True,   # both arms hold a tool (fingertip / pick) at all times
        ))

    def _hard_box(self) -> dict:
        cal = json.loads(self.robot.calibration_fpath.read_text())
        if problems := calibration_problems(cal):
            raise GuardError("bad calibration: " + "; ".join(problems))
        return calibrated_box(cal)

    def connect(self) -> None:
        r = self.robot
        if not r.calibration:
            raise RuntimeError(f"'{self.arm_id}' is not calibrated - run lerobot-calibrate first (CONNECT.md 5b)")
        self._hard_box()  # reject bad saved calibration before enabling any torque
        for joint, cal in r.calibration.items():
            if cal.id != r.bus.motors[joint].id:
                raise GuardError(f"{joint}: calibration motor ID does not match the configured arm")
        r.bus.connect()
        try:
            if not r.is_calibrated:
                raise GuardError("servo calibration differs from the saved file; verify/calibrate explicitly first")
            # Validate the current pose and workspace before any writes.
            super().connect()
            check_trajectory([self.last_cmd], self.limits, dt=1 / CONTROL_HZ)
        except BaseException:
            r.bus.disconnect(disable_torque=False)
            raise
        try:
            # Hold current position, never a stale goal. The gripper remains a tool clamp.
            present = r.bus.sync_read("Present_Position", normalize=False)
            r.bus.sync_write("Goal_Position", {m: v for m, v in present.items() if m != "gripper"}, normalize=False)
            r.configure()
            if self.base_mode == "speed":
                from .base_speed import SpeedBase
                self.base = SpeedBase(r.bus)
                self.base.enable()
            grip = r.clamp_gripper()
            if not grip["squeezing"]:
                log.warning(f"gripper is not squeezing anything: {grip} - check the fingertip/pick")
            self.last_cmd = self._read()
        except BaseException:
            self.disconnect()
            raise

    def _before_motion(self) -> None:
        self.robot.reassert_grip()

    def _move_base(self, traj: list[Pose], speed: float) -> None:
        if self.base_mode == "position":
            return super()._move_base(traj, speed)
        self.base.vmax = min(25.0, MAX_DEG_PER_S * speed)
        self.base.move_to(traj[-1][BASE])

    def _read(self) -> Pose:
        q = {k.removesuffix(".pos"): v for k, v in self.robot.get_observation().items() if k.endswith(".pos")}
        if getattr(self, "base", None) and self.base.enabled:
            q[BASE] = self.base.pos()   # speed mode reports the base without its homing offset
        return q

    def _send(self, q: Pose) -> None:
        # In speed mode the base must never receive a position goal.
        self.robot.send_action({f"{j}.pos": v for j, v in q.items()
                                if j != BASE or self.base_mode == "position"})

    def disconnect(self) -> None:
        if self.robot.is_connected:
            if getattr(self, "base", None):
                self.base.disable()      # stop, torque off, back in position mode
            self.robot.disconnect()  # body joints go limp; the gripper keeps holding the tool


class FakeArm(Arm):
    """Same interface, no hardware: position follows commands instantly."""

    def __init__(self, arm_id: str, *, clock=None):
        super().__init__(arm_id)
        if clock is not None:
            self._clock = clock
        self.q = dict(self.poses.get("rest", next(iter(self.poses.values()))))

    def _hard_box(self) -> dict:
        return {j: ((0.0, 100.0) if j == "gripper" else (-180.0, 180.0)) for j in JOINTS}

    def _read(self) -> Pose:
        return dict(self.q)

    def _send(self, q: Pose) -> None:
        self.q = dict(q)
