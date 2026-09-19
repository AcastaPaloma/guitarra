"""Software position control for the fret arm's base, using the servo's speed mode.

The base servo (ID 7) can't hold a position target in its own position mode (it drives one way,
2026-09-19), but in constant-speed mode it turns both ways correctly (runs/base-velocity-*.json).
So here the base runs in speed mode and our loop closes position: speed = gain x error, capped,
with a minimum speed to beat friction and a stop inside the tolerance. Anything unexpected
(wrong way, overshoot, no progress) stops the base and raises GuardError.
"""
import time

from .guards import GuardError

STEPS_PER_DEG = 4096 / 360
TICKS = 4096


class SpeedBase:
    def __init__(self, bus, motor: str = "shoulder_pan", gain: float = 3.0, vmax_deg_s: float = 25.0,
                 vmin_deg_s: float = 2.0, tol_deg: float = 0.8, hz: int = 50):
        self.bus, self.m = bus, motor
        self.gain, self.vmax, self.vmin, self.tol, self.hz = gain, vmax_deg_s, vmin_deg_s, tol_deg, hz
        self.enabled = False
        # Degrees use LeRobot's calibration frame. In speed mode the servo reports its raw encoder
        # WITHOUT the homing offset (measured: 75.0 deg read raw 1008 = (3364 + 1740) % 4096), so
        # pos() re-applies the offset itself while speed mode is on.
        self.offset = bus.read("Homing_Offset", motor, normalize=False)
        cal = bus.calibration[motor]
        self.mid = (cal.range_min + cal.range_max) / 2

    def _v(self, deg_s: float) -> None:
        self.bus.write("Goal_Velocity", self.m, int(round(deg_s * STEPS_PER_DEG)))

    def pos(self) -> float:
        raw = self.bus.read("Present_Position", self.m, normalize=False)
        if self.enabled:
            raw = (raw - self.offset) % TICKS
        return (raw - self.mid) * 360 / (TICKS - 1)

    def enable(self) -> None:
        b, m = self.bus, self.m
        before = self.pos()
        b.write("Torque_Enable", m, 0)
        b.write("Lock", m, 0)
        b.write("Operating_Mode", m, 1)       # constant speed
        b.write("Goal_Velocity", m, 0)
        self.enabled = True
        after = self.pos()
        if abs(after - before) > 2.0:          # the frame conversion must agree across the switch
            self.disable()
            raise GuardError(f"base angle reads {before:.1f} in position mode but {after:.1f} in speed mode "
                             "- frame conversion wrong, not moving")
        b.write("Torque_Enable", m, 1)        # speed 0 = hold still

    def disable(self) -> None:
        """Stop, torque off, and put the servo back in position mode (as other tools expect).
        Never writes Goal_Position: on these servos that switches torque back on - in the broken mode."""
        b, m = self.bus, self.m
        for _ in range(3):
            try:
                b.write("Goal_Velocity", m, 0)
                b.write("Torque_Enable", m, 0)
                b.write("Lock", m, 0)
                b.write("Operating_Mode", m, 0)
                b.write("Lock", m, 1)
                b.write("Torque_Enable", m, 0)
                break
            except RuntimeError:
                time.sleep(0.1)
        self.enabled = False

    def move_to(self, target_deg: float, timeout_s: float = 8.0, bad_deg: float = 3.0) -> float:
        """Drive the base to target_deg. Returns the final error (deg)."""
        if not self.enabled:
            self.enable()
        start = self.pos()
        want = 1 if target_deg > start else -1
        t0, settled, best = time.monotonic(), 0, abs(target_deg - start)
        try:
            while True:
                p = self.pos()
                err = target_deg - p
                if want * (start - p) > bad_deg:
                    raise GuardError(f"base went the wrong way ({p - start:+.1f} deg)")
                if want * (p - target_deg) > bad_deg:
                    raise GuardError(f"base overshot by {abs(p - target_deg):.1f} deg")
                if abs(err) <= self.tol:
                    self._v(0)
                    settled += 1
                    if settled >= 5:              # 0.1 s inside tolerance
                        return round(err, 2)
                else:
                    settled = 0
                    v = max(self.vmin, min(self.vmax, self.gain * abs(err)))
                    self._v(v if err > 0 else -v)
                best = min(best, abs(err))
                if time.monotonic() - t0 > timeout_s:
                    raise GuardError(f"base did not reach {target_deg:.1f} deg in {timeout_s:g} s (at {p:.1f})")
                time.sleep(1 / self.hz)
        except BaseException:
            self._v(0)
            raise
