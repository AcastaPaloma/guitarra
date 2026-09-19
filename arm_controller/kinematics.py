"""Forward kinematics for the tap arm (IDs 7-11) — servo counts -> tip XYZ.

Keypoints stay RAW SERVO COUNTS (the source of truth fret.py plays back).
This module adds two derived views so a model can reason spatially later:
  - per-joint DEGREES relative to a captured reference pose
  - the fingertip's XYZ in a fixed world frame (cm)
Given any joint pose the tip lands at ONE point in that frame, however the
pose was reached — that shared frame is what lets an LLM say "2 cm toward
the nut, same height" instead of guessing servo counts.

Measured geometry (operator, 2026-09-19):
  - motor 8 (shoulder) axis sits 10.0 cm above the ground
  - link1, motor 8 -> motor 9:      14.0 cm
  - link2, motor 9 -> motor 10:     13.0 cm
  - link3, motor 10 -> rubber tip:  18.0 cm
  - guitar strings sit ~13.5 cm above the ground

REFERENCE POSE (all joint angles are zeroed here — capture it once in the
calibrate webapp with "set reference"):
  link1 straight, continuing the base column upward; link2 at 90° to it,
  horizontal toward the guitar; link3 at 90° again, hanging straight down.
  In that pose the tip sits at (x=13.0, y=0.0, z=6.0) cm.

World frame: origin on the base-yaw (motor 7) axis AT GROUND LEVEL.
+x from the base toward the guitar at reference yaw, +y follows positive
yaw, +z up. The shoulder axis is assumed to intersect the yaw axis.

calibration_arm2.json holds the reference counts plus per-joint direction
signs (flip a sign to -1 if a joint's XYZ moves opposite to reality) and
the geometry constants, so everything is tunable without code edits.
"""
import json
import math
from datetime import datetime
from pathlib import Path

CAL_PATH = Path(__file__).parent / "calibration_arm2.json"

COUNTS_PER_REV = 4096
DEG_PER_COUNT = 360.0 / COUNTS_PER_REV

# FK chain joints; 11 (wrist_roll) spins the fingertip about link3's axis, so
# it gets a relative degree readout but does not move the tip point.
FK_IDS = [7, 8, 9, 10]

DEFAULT_GEOMETRY = {
    "shoulder_z_cm": 10.0,   # motor 8 axis height above ground
    "l1_cm": 14.0,           # motor 8 -> motor 9
    "l2_cm": 13.0,           # motor 9 -> motor 10
    "l3_cm": 18.0,           # motor 10 -> rubber tip
    "strings_z_cm": 13.5,    # guitar string height above ground
}
DEFAULT_SIGNS = {"7": 1, "8": 1, "9": 1, "10": 1, "11": 1}


def load_calibration(path=CAL_PATH):
    """-> calibration dict, or None if no reference has been captured yet."""
    if not Path(path).exists():
        return None
    cal = json.loads(Path(path).read_text())
    cal.setdefault("signs", dict(DEFAULT_SIGNS))
    cal.setdefault("geometry", dict(DEFAULT_GEOMETRY))
    return cal


def save_reference(ref_counts, path=CAL_PATH):
    """Capture the reference pose. Keeps previously tuned signs/geometry."""
    cal = load_calibration(path) or {"signs": dict(DEFAULT_SIGNS),
                                     "geometry": dict(DEFAULT_GEOMETRY)}
    cal["ref_counts"] = {str(k): int(v) for k, v in ref_counts.items()}
    cal["captured"] = datetime.now().isoformat(timespec="seconds")
    Path(path).write_text(json.dumps(cal, indent=2))
    return cal


def joint_degrees(counts, cal):
    """Raw counts {sid: pos} -> {sid: degrees from reference} (signed)."""
    if not cal or "ref_counts" not in cal:
        return None
    ref, signs = cal["ref_counts"], cal["signs"]
    out = {}
    for sid, pos in counts.items():
        s = str(sid)
        if s in ref:
            out[s] = round(int(signs.get(s, 1)) * (int(pos) - int(ref[s])) * DEG_PER_COUNT, 2)
    return out


def tip_xyz(counts, cal):
    """Raw counts -> fingertip world XYZ in cm, or None without a reference.

    Planar 3-link chain (joints 8, 9, 10) swung about the base yaw (7).
    Absolute link elevations at reference: link1 +90° (up), link2 0°
    (horizontal), link3 -90° (down); joint deltas accumulate down the chain.
    """
    deg = joint_degrees(counts, cal)
    if deg is None or any(str(i) not in deg for i in FK_IDS):
        return None
    g = cal["geometry"]
    a1 = math.radians(90.0 + deg["8"])
    a2 = a1 + math.radians(-90.0 + deg["9"])
    a3 = a2 + math.radians(-90.0 + deg["10"])
    r = (g["l1_cm"] * math.cos(a1) + g["l2_cm"] * math.cos(a2)
         + g["l3_cm"] * math.cos(a3))
    z = (g["shoulder_z_cm"] + g["l1_cm"] * math.sin(a1)
         + g["l2_cm"] * math.sin(a2) + g["l3_cm"] * math.sin(a3))
    yaw = math.radians(deg["7"])
    return {"x_cm": round(r * math.cos(yaw), 2),
            "y_cm": round(r * math.sin(yaw), 2),
            "z_cm": round(z, 2),
            "above_strings_cm": round(z - g["strings_z_cm"], 2)}


if __name__ == "__main__":
    # sanity: at the reference pose the tip must sit at (l2, 0, z8 + l1 - l3)
    fake_ref = {"7": 2000, "8": 2000, "9": 2000, "10": 2000, "11": 2000}
    cal = {"ref_counts": fake_ref, "signs": dict(DEFAULT_SIGNS),
           "geometry": dict(DEFAULT_GEOMETRY)}
    at_ref = tip_xyz({int(k): v for k, v in fake_ref.items()}, cal)
    assert at_ref == {"x_cm": 13.0, "y_cm": 0.0, "z_cm": 6.0,
                      "above_strings_cm": -7.5}, at_ref
    # 90° shoulder swing forward lays link1 flat: tip at (14+18, 0, 10-13)... no:
    # link2 then points down, link3 points back toward the base.
    quarter = COUNTS_PER_REV // 4
    swung = dict(fake_ref, **{"8": fake_ref["8"] + quarter})
    print("reference pose ->", at_ref)
    print("shoulder +90deg ->", tip_xyz({int(k): v for k, v in swung.items()}, cal))
    print("kinematics self-test OK")
