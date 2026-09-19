"""Compile one complete scene without inserting per-phrase runtime entries.

Bounds apply to the continuous authoring curve. CSV sampling and the physical
servos are separate systems: these bounds do not prove physical jerk/tracking.
Invalid plans are rejected; no clipping or retiming can move a musical accent.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import io
import math

from .primitives import JOINTS, Primitive, Wave

EASE = (0.0, 0.0, 0.0, 0.0, 35.0, -84.0, 70.0, -20.0)


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def polynomial(coefficients, x):
    result = 0.0
    for value in reversed(coefficients):
        result = result * x + value
    return result


def derivative(coefficients):
    return tuple(i * value for i, value in enumerate(coefficients) if i)


def roots_unit_interval(coefficients):
    """Isolate polynomial roots by derivative extrema, then bisection."""
    if len(coefficients) <= 1:
        return []
    boundaries = [0.0, *roots_unit_interval(derivative(coefficients)), 1.0]
    roots = [x for x in boundaries if abs(polynomial(coefficients, x)) < 1e-10]
    for left, right in zip(boundaries, boundaries[1:]):
        value = polynomial(coefficients, left)
        if value * polynomial(coefficients, right) >= 0:
            continue
        for _ in range(60):
            middle = (left + right) / 2
            if value * polynomial(coefficients, middle) <= 0:
                right = middle
            else:
                left = middle
                value = polynomial(coefficients, left)
        roots.append((left + right) / 2)
    return sorted(set(round(x, 13) for x in roots))


def derivative_maxima():
    coefficients = EASE
    maxima = []
    for _ in range(3):
        coefficients = derivative(coefficients)
        points = [0.0, 1.0, *roots_unit_interval(derivative(coefficients))]
        maxima.append(max(abs(polynomial(coefficients, x)) for x in points))
    return tuple(maxima)


DERIVATIVE_MAXIMA = derivative_maxima()


def wave_bounds(wave, seconds_per_beat):
    """Conservative continuous derivative bounds from the product rule.

    Covers the envelope ramps as well as every interior extremum; no sampled
    finite differences are used to approve a trajectory.
    """
    omega = 2 * math.pi / (wave.period_beats * seconds_per_beat)
    ramp = wave.fade_beats * seconds_per_beat
    envelope = (1.0, *(peak / ramp**order for order, peak
                       in enumerate(DERIVATIVE_MAXIMA, 1)))
    return tuple(abs(wave.amplitude) * sum(math.comb(order, k) * envelope[k]
                                          * omega**(order - k) for k in range(order + 1))
                 for order in range(1, 4))


def wave_value(wave, beat, duration):
    fade = min(1.0, max(0.0, min(beat, duration - beat) / wave.fade_beats))
    return wave.offset + wave.amplitude * polynomial(EASE, fade) * math.sin(
        2 * math.pi * (beat - wave.phase_beats) / wave.period_beats)


@dataclass(frozen=True)
class StageEnvelope:
    envelope_id: str
    robot_id: str
    calibration_id: str
    baseline: dict[str, float]
    offset_limits: dict[str, list[float]]
    dynamics: dict[str, list[float]]
    partner_sign: int
    bow_sign: int
    hardware_verified: bool = False
    verification_runs: tuple[str, ...] = ()

    def validate(self):
        if not all(isinstance(x, str) and x for x in (self.envelope_id, self.robot_id, self.calibration_id)):
            raise ValueError("Stage requires envelope, robot and calibration identities")
        if any(isinstance(x, bool) or x not in (-1, 1) for x in (self.partner_sign, self.bow_sign)):
            raise ValueError("Directions must be established as -1 or +1")
        for mapping in (self.baseline, self.offset_limits, self.dynamics):
            if set(mapping) != set(JOINTS):
                raise ValueError("Stage must declare exactly five calibrated joints")
        for joint in JOINTS:
            base = finite(self.baseline[joint], joint)
            bounds = self.offset_limits[joint]
            dynamics = self.dynamics[joint]
            if len(bounds) != 2 or len(dynamics) != 3:
                raise ValueError("Expected two offset bounds and velocity/acceleration/jerk bounds")
            lo, hi = (finite(x, joint) for x in bounds)
            if not lo <= 0 <= hi or base + lo < -100 or base + hi > 100:
                raise ValueError("Envelope exceeds normalized coordinate limits")
            if any(finite(x, joint) <= 0 for x in dynamics):
                raise ValueError("Dynamic limits must be positive")
        if not isinstance(self.hardware_verified, bool) or not isinstance(self.verification_runs, (tuple, list)):
            raise ValueError("Invalid verification metadata")
        if any(not isinstance(run, str) or not run for run in self.verification_runs):
            raise ValueError("Verification run IDs must be nonempty strings")
        if self.hardware_verified and not self.verification_runs:
            raise ValueError("Hardware verification needs traceable run IDs")


@dataclass(frozen=True)
class CompiledScene:
    frames: tuple[tuple[float, dict[str, float]], ...]
    landmarks: tuple[dict, ...]
    duration_seconds: float
    envelope_id: str

    def csv_bytes(self):
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["timestamp", *(f"{joint}.pos" for joint in JOINTS)])
        for timestamp, pose in self.frames:
            writer.writerow([f"{timestamp:.9f}", *(f"{pose[joint]:.9f}" for joint in JOINTS)])
        return output.getvalue().encode()


def compose(primitives: list[Primitive], stage: StageEnvelope, bpm=96.0, fps=30):
    stage.validate()
    bpm = finite(bpm, "bpm")
    if not 20 <= bpm <= 240 or isinstance(fps, bool) or not isinstance(fps, int) or not 10 <= fps <= 120:
        raise ValueError("Unsupported tempo or control rate")
    if not primitives:
        raise ValueError("Scene must contain primitives")
    seconds_per_beat = 60 / bpm
    tracks = {joint: [] for joint in JOINTS}
    waves = {joint: [] for joint in JOINTS}
    offsets = dict.fromkeys(JOINTS, 0.0)
    beat = 0.0
    landmarks = []
    for primitive in primitives:
        duration = finite(primitive.beats, "primitive duration")
        if (duration <= 0 or type(primitive.version) is not int or primitive.version != 1
                or primitive.envelope_id != stage.envelope_id or not isinstance(primitive.name, str)
                or not primitive.name):
            raise ValueError("Invalid primitive version, duration or envelope")
        if not set(primitive.joint_mask) <= set(JOINTS):
            raise ValueError("Unknown joint ownership")
        landmarks.append({"name": primitive.name, "beat": beat,
                          "seconds": beat * seconds_per_beat, "version": primitive.version})
        for joint in JOINTS:
            knots = primitive.tracks.get(joint, ((0.0, offsets[joint]), (duration, offsets[joint])))
            if isinstance(knots, Wave):
                wave = knots
                for key in ("amplitude", "period_beats", "phase_beats", "offset", "fade_beats"):
                    finite(getattr(wave, key), key)
                if wave.period_beats <= 0 or not 0 < wave.fade_beats <= duration / 2:
                    raise ValueError("Invalid wave period or fade")
                if abs(wave.offset - offsets[joint]) > 1e-9:
                    raise ValueError(f"Discontinuous wave join on {joint}")
                lo, hi = stage.offset_limits[joint]
                if wave.offset - abs(wave.amplitude) < lo or wave.offset + abs(wave.amplitude) > hi:
                    raise ValueError(f"{joint} wave exceeds stage envelope")
                for order, (bound, limit) in enumerate(zip(wave_bounds(wave, seconds_per_beat),
                                                          stage.dynamics[joint]), 1):
                    if bound > limit + 1e-9:
                        raise ValueError(f"{joint} wave exceeds derivative order {order}")
                waves[joint].append((beat * seconds_per_beat, (beat + duration) * seconds_per_beat,
                                     duration, wave))
                # A constant carrier makes adjacent, unowned tracks inherit
                # the planned offset. The wave adds no boundary derivatives.
                knots = ((0.0, wave.offset), (duration, wave.offset))
            if len(knots) < 2:
                raise ValueError("A track requires entry and exit knots")
            knots = [(finite(t, "knot beat"), finite(v, joint)) for t, v in knots]
            if knots[0][0] != 0 or knots[-1][0] != duration:
                raise ValueError("Track must cover the entire primitive")
            if abs(knots[0][1] - offsets[joint]) > 1e-9:
                raise ValueError(f"Discontinuous join on {joint}")
            lo, hi = stage.offset_limits[joint]
            if any(not lo <= value <= hi for _, value in knots):
                raise ValueError(f"{joint} exceeds stage envelope")
            for (t0, p0), (t1, p1) in zip(knots, knots[1:]):
                if t1 <= t0:
                    raise ValueError("Knots must strictly increase")
                seconds = (t1 - t0) * seconds_per_beat
                for order, (peak, limit) in enumerate(zip(DERIVATIVE_MAXIMA, stage.dynamics[joint]), 1):
                    if abs(p1 - p0) * peak / seconds**order > limit + 1e-9:
                        raise ValueError(f"{joint} exceeds derivative order {order}; reduce amplitude or explicitly change tempo")
                tracks[joint].append(((beat + t0) * seconds_per_beat,
                                      (beat + t1) * seconds_per_beat, p0, p1))
            offsets[joint] = knots[-1][1]
        beat += duration
    duration = beat * seconds_per_beat
    if duration > 600 or math.ceil(duration * fps) + 1 > 18000:
        raise ValueError("Scene exceeds existing SDK clip limits")
    # Include exact musical landmarks and every knot as well as control ticks.
    times = {0.0, duration, *(min(i / fps, duration) for i in range(math.ceil(duration * fps) + 1))}
    times.update(t for segments in tracks.values() for t0, t1, _, _ in segments for t in (t0, t1))
    # Serialize exactly one frame per nanosecond. Landmarks retain their exact
    # floating-point time in metadata; CSV precision is explicitly 1 ns.
    times = {round(time, 9) for time in times}
    if len(times) > 18000:
        raise ValueError("Scene exceeds frame limit after adding musical knots")
    frames = []
    indices = dict.fromkeys(JOINTS, 0)
    for time in sorted(times):
        pose = {}
        for joint, segments in tracks.items():
            while indices[joint] + 1 < len(segments) and time > segments[indices[joint]][1]:
                indices[joint] += 1
            left, right, start, finish = segments[indices[joint]]
            phase = max(0.0, min(1.0, (time - left) / (right - left)))
            pose[joint] = stage.baseline[joint] + start + (finish - start) * polynomial(EASE, phase)
            for left, right, beats, wave in waves[joint]:
                if left <= time <= right:
                    pose[joint] = stage.baseline[joint] + wave_value(
                        wave, (time - left) / seconds_per_beat, beats)
                    break
        frames.append((time, pose))
    return CompiledScene(tuple(frames), tuple(landmarks), duration, stage.envelope_id)
