"""Calibrate frets 1-9 on every string: record anchors by hand, compute the rest (robot/fretmap.py).

    python scripts/record_fret_map.py                      # all 6 strings at frets 1, 5, 9 (36 poses)
    python scripts/record_fret_map.py --strings 6 1        # outer strings only; 5-2 interpolated
    python scripts/record_fret_map.py --redo s4f5          # re-record one anchor
    python scripts/record_fret_map.py --build-only         # rebuild the map from saved anchors

Body joints are limp (move the arm by hand); the gripper keeps the fingertip clamped. For each
anchor, two captures:
  ABOVE  fingertip ~10 mm above the string, just behind the fret wire (toward the nut)
  TOUCH  lower it straight down until it just touches the string - no pressing
Anchors are saved after every capture, so you can stop (Ctrl-C) and resume later.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot import fretmap  # noqa: E402
from robot import poses as pose_store  # noqa: E402
from robot.guards import JOINTS, calibration_problems  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--offset", type=int, default=6)
ap.add_argument("--strings", type=int, nargs="+", default=list(fretmap.STRINGS))
ap.add_argument("--frets", type=int, nargs="+", default=list(fretmap.ANCHOR_FRETS))
ap.add_argument("--redo", nargs="*", default=[], help="anchor keys to re-record, e.g. s4f5")
ap.add_argument("--build-only", action="store_true")
args = ap.parse_args()

path = pose_store.path_for(args.id)
data = json.loads(path.read_text()) if path.exists() else {"poses": {}, "depth": dict(pose_store.DEFAULT_DEPTH)}
anchors = data.setdefault("fret_anchors", {})


def save() -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def build() -> None:
    generated = fretmap.build(anchors)
    data["poses"] = {k: v for k, v in data["poses"].items() if not k.startswith(("above_s", "touch_s"))}
    data["poses"].update(generated)
    data["fret_map"] = {"hover_mm": fretmap.HOVER_MM, "max_fret": fretmap.MAX_FRET,
                        "anchors": sorted(anchors)}
    save()
    avail = fretmap.available(data["poses"])
    print(f"\nfret map: {len(generated) // 2} positions -> {path}")
    for s, frets in avail.items():
        src = "recorded" if any(k.startswith(f"s{s}f") for k in anchors) else "interpolated from neighbours"
        print(f"  string {s}: frets {frets[0]}-{frets[-1]}  ({src})")
    warnings = fretmap.anchor_warnings(anchors)
    for w in warnings:
        print(f"  REDO {w}")
    if warnings:
        keys = " ".join(w.split(":")[0] for w in warnings)
        print(f"  -> .venv/bin/python scripts/record_fret_map.py --redo {keys}")
    # sanity: the joint-space step between neighbouring frets should shrink up the neck
    for s, frets in avail.items():
        steps = [max(abs(data["poses"][fretmap.name("touch", s, f + 1)][j] - data["poses"][fretmap.name("touch", s, f)][j])
                     for j in JOINTS if j != "gripper") for f in frets[:-1]]
        if steps and max(steps) > 3 * (sum(steps) / len(steps)):
            print(f"  CHECK string {s}: uneven fret steps {[round(x, 1) for x in steps]} deg - an anchor may be off")


if args.build_only:
    try:
        build()
    except ValueError as e:
        sys.exit(f"map not built: {e}")
    sys.exit(0)

robot = AstraSO101(AstraSO101Config(port=args.port, id=args.id, motor_id_offset=args.offset, clamp_gripper=True))
if not robot.calibration:
    sys.exit(f"'{args.id}' is not calibrated yet")
if problems := calibration_problems({j: vars(c) for j, c in robot.calibration.items()}):
    sys.exit("calibration unusable:\n  " + "\n  ".join(problems))
bus = robot.bus
bus.connect()
body = [m for m in bus.motors if m != "gripper"]
bus.disable_torque(body)
if not robot.is_calibrated:
    bus.write_calibration({m: robot.calibration[m] for m in body})
grip = robot.clamp_gripper()
print("gripper:", "squeezing the fingertip" if grip["squeezing"] else f"NOT squeezing - check the tip! {grip}")

todo = [(s, f) for s in args.strings for f in args.frets
        if fretmap.anchor_key(s, f) not in anchors or fretmap.anchor_key(s, f) in args.redo]
print(f"\n{len(todo)} anchors to record ({2 * len(todo)} captures). Already saved: {len(anchors)}.")
try:
    for i, (s, f) in enumerate(todo, 1):
        note = fretmap.STANDARD_TUNING[s]
        print(f"\n[{i}/{len(todo)}] STRING {s} ({note} string), FRET {f}")
        pair = {}
        for kind, how in (("above", "fingertip ~10 mm ABOVE the string, just behind the fret wire"),
                          ("touch", "lower it STRAIGHT DOWN until it just touches the string (no press)")):
            input(f"   {kind.upper():5s}: {how}, then Enter ")
            robot.reassert_grip()
            pair[kind] = {j: round(float(v), 2) for j, v in bus.sync_read("Present_Position").items()}
        anchors[fretmap.anchor_key(s, f)] = pair
        save()
        print("   saved")
except KeyboardInterrupt:
    print("\nstopped - anchors so far are saved; run again to continue")
finally:
    bus.disable_torque(body)
    bus.disconnect(disable_torque=False)  # fingertip stays clamped

try:
    build()
except ValueError as e:
    print(f"\nmap not built yet: {e}")
