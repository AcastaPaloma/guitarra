"""Clamp the gripper on its tool (fret arm: fingertip extension; pluck arm: pick) and leave it held.

    python scripts/grip_tool.py              # clamp now (re-grip after a power cycle)
    python scripts/grip_tool.py --open       # open, insert/reseat the tool, Enter, clamp
    python scripts/grip_tool.py --status     # read-only: is it holding?

Only the gripper moves; the other joints' torque is left as it is. The clamp stays on after
this script exits. Every robot/ and agent/ entry point also re-clamps on connect.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--offset", type=int, default=6)
ap.add_argument("--open", action="store_true")
ap.add_argument("--status", action="store_true")
args = ap.parse_args()

robot = AstraSO101(AstraSO101Config(port=args.port, id=args.id, motor_id_offset=args.offset, clamp_gripper=True))
bus, g = robot.bus, "gripper"
bus.connect()
try:
    if args.status:
        print({k: bus.read(k, g, normalize=False) for k in
               ("Torque_Enable", "Present_Position", "Goal_Position", "Present_Load", "Torque_Limit")})
        sys.exit(0)
    if args.open:
        cal = robot.calibration[g]
        open_to = cal.range_max - 100
        if not bus.read("Torque_Enable", g):
            bus.write("Goal_Position", g, bus.read("Present_Position", g, normalize=False), normalize=False)
            bus.write("Torque_Enable", g, 1)
        bus.write("Torque_Limit", g, robot.config.grip_torque)
        bus.write("Goal_Position", g, open_to, normalize=False)
        time.sleep(1.0)
        input("Jaws open. Insert / reseat the tool, hold it in place, press Enter to clamp... ")
    state = robot.clamp_gripper()
    print("SQUEEZING (check by eye that it is the tool, not jaw on jaw)" if state["squeezing"]
          else "NOT SQUEEZING - tool missing or command not taken", state)
finally:
    bus.disconnect(disable_torque=False)
