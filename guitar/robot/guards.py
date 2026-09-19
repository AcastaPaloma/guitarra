"""Safety checks between the model and the servo bus. Pure functions, no hardware.

Every trajectory is checked as a whole before the first step is sent. A violation rejects the
whole motion - nothing is silently clamped, so the model always learns that it asked for
something out of bounds.
"""
from dataclasses import dataclass

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
STS3215_TICKS = 4096

Pose = dict[str, float]          # joint -> degrees (gripper: 0-100)
Box = dict[str, tuple[float, float]]


class GuardError(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    hard: Box            # calibrated mechanical range
    workspace: Box       # tighter box around the recorded poses
    max_deg_per_s: float # speed cap, independent of what the model asks for


def calibrated_box(calibration: dict) -> Box:
    """Joint ranges in the units LeRobot reports (DEGREES body, RANGE_0_100 gripper).

    `calibration` is the LeRobot calibration JSON: {joint: {range_min, range_max, ...}}.
    DEGREES normalisation is (ticks - mid) * 360 / 4095, so the range is +-half-span.
    """
    box = {}
    for joint in JOINTS:
        c = calibration[joint]
        if joint == "gripper":
            box[joint] = (0.0, 100.0)
        else:
            half = (c["range_max"] - c["range_min"]) / 2 * 360 / (STS3215_TICKS - 1)
            box[joint] = (-half, half)
    return box


FULL_TURN_JOINTS = ("wrist_roll",)   # LeRobot records these as 0-4095 on purpose
MAX_SPAN_DEG = 300.0                 # anything wider on an SO-101 joint means the encoder wrapped


def calibration_problems(calibration: dict) -> list[str]:
    """Sanity-check a LeRobot calibration file. A joint whose recorded range is ~360 deg crossed
    the encoder's 0/4095 seam during calibration; its positions jump by 360 at that seam and an
    interpolated move between two poses can swing the long way round."""
    out = []
    for joint in JOINTS:
        if joint in FULL_TURN_JOINTS:
            continue
        c = calibration[joint]
        span = (c["range_max"] - c["range_min"]) * 360 / (STS3215_TICKS - 1)
        if span > MAX_SPAN_DEG:
            out.append(f"{joint}: recorded range {span:.0f} deg ({c['range_min']}-{c['range_max']}) - "
                       "encoder wrapped; recalibrate with this joint at the MIDDLE of its travel when you press Enter")
    return out


def workspace_box(poses: dict[str, Pose], margin_deg: float, extra: dict[str, float] | None = None) -> Box:
    """Per-joint [min, max] over all recorded poses, widened by margin (+ per-joint extra)."""
    extra = extra or {}
    box = {}
    for joint in JOINTS:
        vals = [p[joint] for p in poses.values()]
        pad = margin_deg + extra.get(joint, 0.0)
        box[joint] = (min(vals) - pad, max(vals) + pad)
    return box


def check_trajectory(traj: list[Pose], limits: Limits, dt: float) -> None:
    """Raise GuardError if any step leaves either box or moves faster than the cap."""
    problems = []
    for i, step in enumerate(traj):
        for joint, val in step.items():
            for name, box in (("calibrated range", limits.hard), ("workspace", limits.workspace)):
                lo, hi = box[joint]
                if not lo <= val <= hi:
                    problems.append(f"step {i}: {joint}={val:.1f} outside {name} [{lo:.1f}, {hi:.1f}]")
        if i:
            for joint, val in step.items():
                if joint == "gripper":
                    continue
                speed = abs(val - traj[i - 1][joint]) / dt
                if speed > limits.max_deg_per_s + 1e-6:
                    problems.append(f"step {i}: {joint} at {speed:.0f} deg/s > cap {limits.max_deg_per_s:.0f}")
        if len(problems) >= 5:
            break
    if problems:
        raise GuardError("; ".join(problems))


MAX_SEGMENT_DEG = 90.0   # one straight-line move may not swing any joint further than this


def check_segments(points: list[Pose], max_deg: float = MAX_SEGMENT_DEG) -> None:
    """Reject a straight joint-space move that swings a joint too far, e.g. the elbow flipping
    from bent-one-way to bent-the-other: the arm straightens and sweeps a big arc through
    whatever is around it. Such moves must go through recorded intermediate poses."""
    for a, b in zip(points, points[1:]):
        big = {j: b[j] - a[j] for j in JOINTS if j != "gripper" and abs(b[j] - a[j]) > max_deg}
        if big:
            raise GuardError("single move swings " + ", ".join(f"{j} {d:+.0f} deg" for j, d in big.items())
                             + f" (> {max_deg:.0f}); route it through recorded poses (e.g. 'ready')")


def check_at(expected: Pose, actual: Pose, tol_deg: float) -> None:
    """Abort if the arm isn't where the last command left it (collision, stall, pushed by hand)."""
    off = {j: actual[j] - expected[j] for j in JOINTS if j != "gripper" and abs(actual[j] - expected[j]) > tol_deg}
    if off:
        raise GuardError("arm not where expected: " + ", ".join(f"{j} off by {d:+.1f} deg" for j, d in off.items()))
