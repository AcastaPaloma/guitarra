"""Callable recorded guitar motions. Importing this module never opens the serial port.

    from motions import connect
    arm = connect(fake=True)             # no hardware; same motion guards
    arm.ready()
    arm.hover("A5")
    arm.touch("A5")
    arm.press("A5", press_mm=1)
    arm.release()
    arm.rest()
    arm.disconnect()

For hardware, explicitly use connect(fake=False, base_mode="position"). Connect
holds the current posture and clamps the tool; disconnect releases body torque.
See MOTIONS.md before using the real arm.
"""
import math
import re

from robot import fretmap
from robot.arm import Arm, FakeArm, RealArm, MAX_DEPTH_MM
from robot.guards import GuardError

DEFAULT_PORT = "/dev/cu.usbmodem5B790163191"


def _bounded(name: str, value: float, low: float, high: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return value


class Motions:
    """One connected session; keep it alive between calls to preserve contact state."""

    def __init__(self, arm: Arm):
        self._arm = arm
        self._closed = False

    def _check_open(self):
        if self._closed:
            raise RuntimeError("session is disconnected; call connect() for a new session")

    def _spot(self, spot: str) -> tuple[int, int]:
        self._check_open()
        string, fret = fretmap.parse_spot(spot)
        if fret not in fretmap.available(self._arm.poses).get(string, []):
            raise GuardError(f"{spot}: no saved above/touch pose pair")
        return string, fret

    def available(self) -> dict:
        """List saved pose names and supported fret spots; does not move the arm."""
        self._check_open()
        return {
            "poses": sorted(self._arm.poses),
            "spots": [fretmap.spot_name(s, f)
                      for s, frets in fretmap.available(self._arm.poses).items() for f in frets],
        }

    def where(self) -> dict:
        """Read the nearest pose / held fret, without commanding motion."""
        self._check_open()
        return self._arm.state()

    def ready(self, speed: float = 0.3) -> dict:
        """Lift off a held fret, then move to the recorded fretboard entry pose."""
        self._check_open()
        speed = _bounded("speed", speed, 0.2, 1.0)
        if "ready" not in self._arm.poses:
            raise GuardError("no 'ready' pose recorded")
        self._arm.release(speed)
        return self._arm.move_to("ready", speed)

    def hover(self, spot: str, speed: float = 0.3) -> dict:
        """Lift before travel; enter through ready when outside the fret region."""
        string, fret = self._spot(spot)
        speed = _bounded("speed", speed, 0.2, 1.0)
        # Plan entry and destination together so a bad target cannot partially execute.
        path = []
        if self._arm.pressing is not None:
            path.append(self._arm.poses[fretmap.name("above", *self._arm.pressing)])
        elif not self._arm._in_fret_region():
            if "ready" not in self._arm.poses:
                raise GuardError("no 'ready' pose recorded for fretboard entry")
            path.append(self._arm.poses["ready"])
        path.append(self._arm.poses[fretmap.name("above", string, fret)])
        result = self._arm._execute(path, speed)
        self._arm.pressing = None
        return result

    def touch(self, spot: str, speed: float = 0.3) -> dict:
        """Approach via hover and lower to saved contact, with no extra pressure."""
        return self.press(spot, press_mm=0.0, speed=speed)

    def press(self, spot: str, press_mm: float = 1.0, speed: float = 0.3) -> dict:
        """Lift/travel/lower, then press along the saved approach direction.

        Depth is a pose-map estimate, not measured force or tip displacement.
        """
        string, fret = self._spot(spot)
        press_mm = _bounded("press_mm", press_mm, 0.0, fretmap.MAX_PRESS_MM)
        speed = _bounded("speed", speed, 0.2, 1.0)
        return self._arm.fret(string, fret, press_mm, speed)

    def release(self, speed: float = 0.3) -> dict:
        """Lift the fingertip to hover. Does NOT open the gripper or drop torque."""
        self._check_open()
        return self._arm.release(_bounded("speed", speed, 0.2, 1.0))

    def rest(self) -> None:
        """Lift off, leave via ready, then go to recorded rest at speed 0.3."""
        self._check_open()
        if "rest" not in self._arm.poses:
            raise GuardError("no 'rest' pose recorded")
        self._arm.rest()

    def move_to(self, pose: str, speed: float = 0.3):
        """Recall a saved pose while preserving hover/contact/exit routing."""
        self._check_open()
        speed = _bounded("speed", speed, 0.2, 1.0)
        if pose not in self._arm.poses:
            raise GuardError(f"unknown recorded pose: {pose}")
        if pose == "ready":
            return self.ready(speed)
        if pose == "rest":
            return self.rest()
        match = re.fullmatch(r"(above|touch)_s([1-6])_f([1-9])", pose)
        if match:
            kind, string, fret = match.groups()
            spot = fretmap.spot_name(int(string), int(fret))
            return self.hover(spot, speed) if kind == "above" else self.touch(spot, speed)
        return self._arm.move_to(pose, speed)

    def pluck(self, depth_mm: float = 1.0, speed: float = 0.3) -> dict:
        """Run a saved pluck stroke, only if this arm has the plucking poses.

        The bundled fret_arm map does not contain these poses and will reject this.
        """
        self._check_open()
        if self._arm.pressing is not None:
            raise GuardError("release the held fret before plucking")
        return self._arm.pluck(_bounded("depth_mm", depth_mm, 0.0, MAX_DEPTH_MM),
                               _bounded("speed", speed, 0.2, 1.0))

    def disconnect(self) -> None:
        """Release body torque, retaining tool clamp; no automatic rest movement.

        Support the arm first: it can sag when torque is released.
        """
        if not self._closed:
            self._arm.disconnect()
            self._closed = True

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()
        return False


def connect(*, fake: bool = True, port: str = DEFAULT_PORT, arm_id: str = "fret_arm",
            motor_id_offset: int = 6, base_mode: str = "position") -> Motions:
    """Open a session. Defaults to simulation; fake=False explicitly enables hardware.

    IDs 7-12 use offset=6. IDs identify addresses, not whether a servo is faulty.
    position = normal working base. speed = legacy faulty-base workaround only.
    Use the calibration AND pose map belonging to the physical arm and guitar setup.
    """
    if base_mode not in ("position", "speed"):
        raise ValueError("base_mode must be 'position' or 'speed'")
    arm = FakeArm(arm_id) if fake else RealArm(port, arm_id, motor_id_offset, base_mode=base_mode)
    arm.connect()
    return Motions(arm)
