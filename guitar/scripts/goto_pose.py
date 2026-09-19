"""Move the fret arm to a recorded pose without powering the faulty base servo (ID 7).

    python scripts/goto_pose.py ready
    python scripts/goto_pose.py --release

You turn the base by hand (live readout); the other four joints move slowly and keep holding
after exit (base limp, fingertip clamped). For string/fret hovers use scripts/hover.py.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robot import poses as pose_store  # noqa: E402
from robot.guards import GuardError  # noqa: E402
from robot.manual_base import ManualBaseArm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pose", nargs="?", default="ready")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--release", action="store_true")
args = ap.parse_args()

arm = ManualBaseArm("/dev/cu.usbmodem5B790163191", args.id)
arm.connect()
try:
    if args.release:
        arm.release()
        print("released (fingertip still clamped)")
    else:
        print("at pose, joint error (deg):", arm.go(pose_store.load(args.id)["poses"][args.pose]))
except GuardError as e:
    print(e)
except KeyboardInterrupt:
    arm.release()
    print("\nCtrl-C: released")
finally:
    arm.close(keep_holding=True)
