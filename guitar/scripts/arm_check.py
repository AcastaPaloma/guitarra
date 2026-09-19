"""Read-only check of one arm through the astra_so101 LeRobot robot. Never enables torque.

    python scripts/arm_check.py --port /dev/cu.usbmodem5B790163191 --id pluck_arm --offset 6
"""
import argparse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot.guards import calibration_problems  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--id", required=True, help="calibration id, e.g. fret_arm / pluck_arm")
ap.add_argument("--offset", type=int, default=0, help="motor ID offset: 0 for IDs 1-6, 6 for 7-12")
args = ap.parse_args()

robot = AstraSO101(AstraSO101Config(port=args.port, id=args.id, motor_id_offset=args.offset))
robot.bus.connect()  # handshake: every expected ID must answer with an STS3215 model number
try:
    print("raw ticks:", robot.bus.sync_read("Present_Position", normalize=False))
    if robot.calibration:
        for p in calibration_problems({j: vars(c) for j, c in robot.calibration.items()}):
            print("CALIBRATION PROBLEM:", p)
    if robot.is_calibrated:
        print("degrees:  ", robot.bus.sync_read("Present_Position"))
    else:
        print(f"not calibrated -- no matching {robot.calibration_fpath}")
finally:
    robot.bus.disconnect(disable_torque=False)
