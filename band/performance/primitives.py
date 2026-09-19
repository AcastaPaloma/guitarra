"""Small performance vocabulary expressed in beats and stage-relative units.

Attention knots declare rest states. Dance tracks use continuous oscillation,
with phased reversals and a C3 envelope at phrase boundaries. Physical
direction belongs to the stage record, not these style profiles.
"""

from dataclasses import dataclass
import math

JOINTS = ("base_yaw", "base_pitch", "elbow_pitch", "wrist_roll", "wrist_pitch")


@dataclass(frozen=True)
class Wave:
    """Offset + amplitude * faded sine; beat-domain parameters, not degrees."""
    amplitude: float
    period_beats: float
    phase_beats: float = 0.0
    offset: float = 0.0
    fade_beats: float = 4.0


@dataclass(frozen=True)
class Primitive:
    name: str
    beats: float
    tracks: dict[str, tuple[tuple[float, float], ...] | Wave]
    envelope_id: str
    version: int = 1

    @property
    def joint_mask(self):
        return tuple(self.tracks)

    @property
    def entry(self):
        return {joint: track.offset if isinstance(track, Wave) else track[0][1]
                for joint, track in self.tracks.items()}

    @property
    def exit(self):
        return {joint: track.offset if isinstance(track, Wave) else track[-1][1]
                for joint, track in self.tracks.items()}


def scene(profile: dict, envelope_id: str, partner_sign: int, bow_sign: int):
    """64 beats: 40 seconds at 96 BPM. Style parameters remain provisional."""
    required = ("yaw_amplitude", "roll_amplitude", "head_amplitude", "waist_amplitude",
                "elbow_amplitude", "partner_offset", "groove_period_beats",
                "head_phase_beats", "support_scale")
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("Unsupported style schema")
    for key in required:
        value = profile[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid style parameter: {key}")
    if not 4 <= profile["groove_period_beats"] <= 16:
        raise ValueError("Groove period must be 4–16 beats")
    if profile["head_phase_beats"] > profile["groove_period_beats"] / 4 or profile["support_scale"] > 1:
        raise ValueError("Invalid phase or support scale")
    yaw = profile["yaw_amplitude"]
    roll = profile["roll_amplitude"]
    head = profile["head_amplitude"]
    waist = profile["waist_amplitude"]
    elbow = profile["elbow_amplitude"]
    gaze = partner_sign * profile["partner_offset"]
    period = profile["groove_period_beats"]
    phase = profile["head_phase_beats"]

    def primitive(name, beats, **tracks):
        return Primitive(name, beats, {k: v if isinstance(v, Wave) else tuple(v)
                                     for k, v in tracks.items()}, envelope_id)

    def cycles(amplitude, phase_beats=0.0, scale=1.0, offset=0.0):
        return Wave(amplitude * scale, period, phase_beats, offset)

    return [
        primitive("listen", 4, wrist_roll=[(0, 0), (2, roll / 2), (4, 0)]),
        primitive("address_audience", 4, base_yaw=[(0, 0), (2, yaw / 2), (4, 0)]),
        primitive("prepare_downbeat", 4, wrist_pitch=[(0, 0), (2, -head), (4, 0)]),
        # Human movement intent, not human joint angles: hip turn -> yaw;
        # waist bounce -> lower arm; torso rise/recoil -> elbow; head sway/nod
        # -> wrists. Staggered extrema prevent five simultaneous reversals.
        primitive("groove", 16, base_yaw=cycles(yaw),
                  base_pitch=cycles(waist, phase / 2),
                  elbow_pitch=cycles(-elbow, phase),
                  wrist_roll=cycles(roll, phase),
                  wrist_pitch=cycles(head, phase / 2)),
        primitive("phrase_accent", 4, wrist_pitch=[(0, 0), (2, head), (4, 0)]),
        primitive("yield_spotlight", 4, base_yaw=[(0, 0), (3, gaze), (4, gaze)]),
        primitive("support_solo", 16,
                  base_yaw=cycles(yaw, 0, profile["support_scale"], gaze),
                  base_pitch=cycles(waist, phase / 2, profile["support_scale"]),
                  elbow_pitch=cycles(-elbow, phase, profile["support_scale"]),
                  wrist_roll=cycles(roll, phase, profile["support_scale"]),
                  wrist_pitch=cycles(head, phase / 2, profile["support_scale"])),
        primitive("acknowledge_ending", 4, base_yaw=[(0, gaze), (3, 0), (4, 0)]),
        primitive("bow", 4, wrist_pitch=[(0, 0), (2, bow_sign * head), (4, 0)]),
        primitive("listen", 4, wrist_roll=[(0, 0), (4, 0)]),
    ]
