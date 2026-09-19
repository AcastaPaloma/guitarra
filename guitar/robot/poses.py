"""Named poses recorded by hand (scripts/record_poses.py), one JSON file per arm id.

File shape:
    {"poses": {"rest": {joint: deg, ...}, ...},
     "depth": {"joint": "wrist_flex", "deg_per_mm": 1.0}}

`depth` says how `pluck(depth_mm)` / `fret(press_mm)` push the tip into the string: that
many degrees per mm on that joint (sign included). Measure it once with the arm, then edit the file.
"""
import json
from pathlib import Path

from .guards import JOINTS, Pose

POSE_DIR = Path(__file__).parent / "poses"
PLUCK_POSES = ("rest", "above_string", "pluck_start", "pluck_end")
DEFAULT_DEPTH = {"joint": "wrist_flex", "deg_per_mm": 1.0}
def path_for(arm_id: str) -> Path:
    return POSE_DIR / f"{arm_id}.json"


def load(arm_id: str) -> dict:
    p = path_for(arm_id)
    if not p.exists():
        raise FileNotFoundError(f"no poses for '{arm_id}' - record them: python scripts/record_poses.py --id {arm_id}")
    data = json.loads(p.read_text())
    data.setdefault("depth", dict(DEFAULT_DEPTH))
    for name, pose in data["poses"].items():
        missing = set(JOINTS) - set(pose)
        if missing:
            raise ValueError(f"pose '{name}' missing joints {sorted(missing)}")
    return data


def save_pose(arm_id: str, name: str, pose: Pose) -> None:
    p = path_for(arm_id)
    data = json.loads(p.read_text()) if p.exists() else {"poses": {}, "depth": dict(DEFAULT_DEPTH)}
    data["poses"][name] = {j: round(float(pose[j]), 2) for j in JOINTS}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def nearest(poses: dict[str, Pose], q: Pose) -> tuple[str, float]:
    """Name of the closest recorded pose and the worst joint error to it (degrees, excl. gripper)."""
    best, best_err = "", float("inf")
    for name, p in poses.items():
        err = max(abs(p[j] - q[j]) for j in JOINTS if j != "gripper")
        if err < best_err:
            best, best_err = name, err
    return best, best_err
