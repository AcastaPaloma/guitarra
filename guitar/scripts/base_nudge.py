"""Turn the fret arm's base left or right in 5-degree steps.

    .venv/bin/python scripts/base_nudge.py
      l      -> 5 deg left  (counter-clockwise seen from above)
      r      -> 5 deg right (clockwise seen from above)
      l 10   -> 10 deg left      where -> current angle      q -> quit
    --flip swaps left/right if they come out backwards from where you stand.

Uses software position control in speed mode (robot/base_speed.py) because the base servo's
own position mode is broken. Other joints are not touched. On quit the base is released and
put back in position mode.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot.base_speed import SpeedBase  # noqa: E402
from robot.guards import GuardError  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=float, default=5.0)
ap.add_argument("--flip", action="store_true")
args = ap.parse_args()

r = AstraSO101(AstraSO101Config(port="/dev/cu.usbmodem5B790163191", id="fret_arm", motor_id_offset=6))
cal = json.loads(r.calibration_fpath.read_text())["shoulder_pan"]
half = (cal["range_max"] - cal["range_min"]) / 2 * 360 / 4095
lo, hi = -half + 3, half - 3                      # stay 3 deg inside the calibrated range
b = r.bus
b.connect()
base = SpeedBase(b)
right = -1 if args.flip else 1                    # + speed turned clockwise (runs/base-velocity-*)
print(f"base at {base.pos():.1f} deg (allowed {lo:.0f} to {hi:.0f}).  l / r [deg], where, q")
try:
    while True:
        parts = input("> ").split()
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit"):
            break
        if cmd == "where":
            print(f"  {base.pos():.1f} deg"); continue
        if cmd not in ("l", "r"):
            print("  type l or r (optionally a number of degrees), where, or q"); continue
        deg = float(parts[1]) if len(parts) > 1 else args.step
        now = base.pos()
        target = now + (right if cmd == "r" else -right) * deg
        if not lo <= target <= hi:
            print(f"  {target:.1f} deg is outside the allowed range {lo:.0f}..{hi:.0f} - not moving"); continue
        try:
            err = base.move_to(target)
            print(f"  {now:.1f} -> {base.pos():.1f} deg (target {target:.1f}, off by {err:+.2f})")
        except GuardError as e:
            print(f"  STOPPED: {e}")
except (KeyboardInterrupt, EOFError):
    print()
finally:
    base.disable()
    b.disconnect(disable_torque=False)
    print("base released (position mode restored). other joints untouched.")
