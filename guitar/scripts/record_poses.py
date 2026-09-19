"""Record named poses by hand. Torque stays OFF - move the arm yourself, press Enter to save.

    python scripts/record_poses.py --role fret --port /dev/cu.usbmodem5B790163191   # IDs 7-12, fret_arm

Fret arm (default names), both with the elbow bent THE SAME WAY as in the fret poses:
  rest   folded near the neck, supported, safe to go limp in
  ready  fingertip ~3 cm above the middle of the neck (about string 3-4, fret 5)
Every trip between rest and the frets goes through `ready`. Fret positions: scripts/record_fret_map.py.
Pluck arm: rest, above_string, pluck_start, pluck_end
  rest          folded, supported, safe to go limp in
  above_string  pick ~1 cm above the live string
  pluck_start   pick just touching the string on the near side
  pluck_end     pick just past the string on the far side (the stroke goes start -> end)
Poses are saved to robot/poses/<id>.json after every capture.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot import poses as pose_store  # noqa: E402
from robot.guards import calibration_problems  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--role", choices=["fret", "pluck"], default="fret")
ap.add_argument("--port", required=True)
ap.add_argument("--id", help="default: fret_arm / pluck_arm")
ap.add_argument("--offset", type=int, help="default: 6 for fret (IDs 7-12), 0 for pluck")
ap.add_argument("names", nargs="*", help="poses to record (default: the role's full set)")
args = ap.parse_args()
args.id = args.id or f"{args.role}_arm"
args.offset = (6 if args.role == "fret" else 0) if args.offset is None else args.offset
args.names = args.names or (["rest", "ready"] if args.role == "fret" else list(pose_store.PLUCK_POSES))

robot = AstraSO101(AstraSO101Config(port=args.port, id=args.id, motor_id_offset=args.offset, clamp_gripper=True))
if not robot.calibration:
    sys.exit(f"'{args.id}' is not calibrated yet - run lerobot-calibrate first (CONNECT.md 5b)")
if problems := calibration_problems({j: vars(c) for j, c in robot.calibration.items()}):
    sys.exit("calibration unusable, recalibrate first:\n  " + "\n  ".join(problems))
robot.bus.connect()
body = [m for m in robot.bus.motors if m != "gripper"]
robot.bus.disable_torque(body)          # body limp so you can move it; gripper keeps the tool
if not robot.is_calibrated:
    robot.bus.write_calibration({m: robot.calibration[m] for m in body})
grip = robot.clamp_gripper()
print(f"gripper squeezing: {grip}" if grip["squeezing"]
      else f"WARNING gripper is not squeezing anything - is the tip in the jaws? {grip}")

captured: dict = {}
try:
    for name in args.names:
        while True:
            input(f"\nMove the arm to '{name}' and press Enter (Ctrl-C to quit) ")
            robot.reassert_grip()
            q = robot.bus.sync_read("Present_Position")
            same = [n for n, p in captured.items()
                    if max(abs(p[j] - q[j]) for j in q if j != "gripper") < 3.0]
            if not same:
                break
            print(f"  that is the same pose as '{same[0]}' (< 3 deg apart) - move the arm, then Enter again")
        captured[name] = q
        pose_store.save_pose(args.id, name, q)
        print(f"  saved {name}: " + ", ".join(f"{j}={v:.1f}" for j, v in q.items()))
finally:
    robot.bus.disable_torque(body)
    robot.bus.disconnect(disable_torque=False)   # gripper stays clamped on the tool
print(f"\nposes in {pose_store.path_for(args.id)}")
