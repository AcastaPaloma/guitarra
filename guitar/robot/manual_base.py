"""Move the fret arm between recorded poses WITHOUT powering the base servo.

The fret arm's base servo (ID 7) drives one way whatever it is commanded (2026-09-19), so here
the base stays limp: you rotate it by hand following a live readout, then the other four joints
move slowly on their own. They keep holding between moves; the fingertip stays clamped.
"""
import threading
import time

import numpy as np

from lerobot_robot_astra import AstraSO101, AstraSO101Config

from .guards import GuardError, check_segments

BASE = "shoulder_pan"
MOVE = ("shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
BASE_TOL_DEG = 5.0
LAG_LIMIT_DEG = 12.0
HZ = 50


class ManualBaseArm:
    def __init__(self, port: str, arm_id: str = "fret_arm", offset: int = 6, speed_deg_s: float = 30.0):
        self.robot = AstraSO101(AstraSO101Config(port=port, id=arm_id, motor_id_offset=offset, clamp_gripper=True))
        self.bus = self.robot.bus
        self.speed = speed_deg_s
        self.powered = False

    def connect(self) -> None:
        self.bus.connect()
        self._torque_off([BASE])   # never power the base; joints already holding keep holding
        self.powered = all(self.bus.read("Torque_Enable", m) for m in MOVE)
        if not self.powered:
            self._torque_off(MOVE)
        grip = self.robot.clamp_gripper()
        if not grip["squeezing"]:
            print(f"WARNING gripper not squeezing - check the fingertip: {grip}")

    def _torque_off(self, motors) -> None:
        for m in motors:
            for _ in range(3):
                try:
                    self.bus.write("Torque_Enable", m, 0)
                    break
                except RuntimeError:   # a faulted servo (overload) can refuse once
                    time.sleep(0.05)

    def release(self) -> None:
        self._torque_off([BASE, *MOVE])
        self.powered = False

    def read(self) -> dict:
        return self.bus.sync_read("Present_Position")

    def guide_base(self, target_deg: float) -> bool:
        """Live readout while the user turns the base by hand. True once within tolerance + Enter."""
        if abs(target_deg - self.bus.read("Present_Position", BASE)) <= BASE_TOL_DEG:
            return True
        done = threading.Event()
        threading.Thread(target=lambda: (input(), done.set()), daemon=True).start()
        print(f"  turn the BASE by hand to {target_deg:.1f} deg, then Enter")
        while not done.is_set():
            now = self.bus.read("Present_Position", BASE)
            d = target_deg - now
            hint = "OK - press Enter" if abs(d) <= BASE_TOL_DEG else (
                "turn toward the FRET 1 / nut end" if d < 0 else "turn toward the FRET 9 end")
            print(f"\r    base {now:7.1f}  target {target_deg:7.1f}  off {d:+7.1f}  {hint}        ", end="", flush=True)
            time.sleep(0.1)
        print()
        return abs(target_deg - self.bus.read("Present_Position", BASE)) <= BASE_TOL_DEG

    def go(self, pose: dict) -> dict:
        """Base by hand, then the four powered joints slowly to `pose`. Raises GuardError on trouble."""
        start = self.read()
        check_segments([start, {**start, **{m: pose[m] for m in MOVE}}])   # no big flips
        if not self.guide_base(pose[BASE]):
            raise GuardError(f"base is more than {BASE_TOL_DEG:g} deg from {pose[BASE]:.1f} - not moving")
        start = self.read()
        span = max(abs(pose[m] - start[m]) for m in MOVE)
        n = max(1, int(np.ceil(span / self.speed * HZ)))
        if not self.powered:
            self.bus.sync_write("Goal_Position", {m: start[m] for m in MOVE})
            self.bus.enable_torque(list(MOVE))
            self.powered = True
        for i in range(1, n + 1):
            cmd = {m: start[m] + (pose[m] - start[m]) * i / n for m in MOVE}
            self.bus.sync_write("Goal_Position", cmd)
            if i > 3 and i % 5 == 0:
                now = self.read()
                lag = {m: cmd[m] - now[m] for m in MOVE if abs(cmd[m] - now[m]) > LAG_LIMIT_DEG}
                if lag:
                    self.bus.sync_write("Goal_Position", {m: now[m] for m in MOVE})   # hold here
                    raise GuardError("stopped - joint fell behind (blocked?): "
                                     + ", ".join(f"{m} {d:+.0f} deg" for m, d in lag.items()))
            time.sleep(1 / HZ)
        time.sleep(0.3)
        now = self.read()
        return {m: round(now[m] - pose[m], 1) for m in (BASE, *MOVE)}   # final error per joint

    def close(self, keep_holding: bool = True) -> None:
        if not keep_holding:
            self.release()
        self.bus.disconnect(disable_torque=False)   # fingertip stays clamped
