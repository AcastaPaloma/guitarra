"""Re-centre ONE joint's calibration from its real end stops, without redoing the whole arm.

Torque stays off. Move the joint slowly stop-to-stop while the live readout runs, press Enter.
Positions are unwrapped across the encoder's 0/4095 seam, so a joint whose range straddles the
seam (the fret_arm elbow wrapped twice in lerobot-calibrate) gets a homing offset that puts the
middle of its travel at 2047 and the stops safely inside 0-4095.

    python scripts/fix_joint_calibration.py elbow_flex            # fret_arm, IDs 7-12
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot.guards import MAX_SPAN_DEG  # noqa: E402

TICKS = 4096
HALF = 2047
MARGIN = 20  # ticks (~1.8 deg) kept inside each measured stop

ap = argparse.ArgumentParser()
ap.add_argument("joint")
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--offset", type=int, default=6)
args = ap.parse_args()

robot = AstraSO101(AstraSO101Config(port=args.port, id=args.id, motor_id_offset=args.offset))
if not robot.calibration:
    sys.exit(f"no calibration file for '{args.id}' - run lerobot-calibrate once first")
bus, j = robot.bus, args.joint
bus.connect()
bus.disable_torque(j)  # also clears the EEPROM lock so offsets/limits can be written
old_offset = bus.read("Homing_Offset", j, normalize=False)
# open the servo's own position limits so readings aren't clipped while we measure
bus.write("Min_Position_Limit", j, 0, normalize=False)
bus.write("Max_Position_Limit", j, TICKS - 1, normalize=False)

stop = threading.Event()
threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
print(f"\n{j}: move it SLOWLY all the way one way, then all the way the other way (2x). Enter when done.\n")

prev = bus.read("Present_Position", j, normalize=False)
u = lo = hi = float(prev)
seams = 0
while not stop.is_set():
    p = bus.read("Present_Position", j, normalize=False)
    d = p - prev
    if d > TICKS / 2:
        d -= TICKS; seams += 1
    elif d < -TICKS / 2:
        d += TICKS; seams += 1
    u += d; prev = p
    lo, hi = min(lo, u), max(hi, u)
    span = (hi - lo) * 360 / (TICKS - 1)
    print(f"\r  raw {p:4d}  travel so far {span:5.1f} deg  (seam crossings: {seams})   ", end="", flush=True)
    time.sleep(0.02)

span = (hi - lo) * 360 / (TICKS - 1)
print(f"\n\nmeasured travel {span:.1f} deg, crossed the 0/4095 seam {seams}x")
if span < 30:
    bus.write_calibration(robot.calibration)  # put the old limits back
    bus.disconnect(disable_torque=False)
    sys.exit("joint barely moved - nothing changed. Run again and move it stop to stop.")
if span > MAX_SPAN_DEG:
    bus.write_calibration(robot.calibration)
    bus.disconnect(disable_torque=False)
    sys.exit("travel > 300 deg is not physical for this joint - likely read glitches. Nothing changed.")

mid = (lo + hi) / 2
shift = round(mid - HALF)        # present values are this far from centred
new_offset = old_offset + shift  # Present = Actual - Homing_Offset
while new_offset > HALF:
    new_offset -= TICKS
while new_offset < -HALF:
    new_offset += TICKS
half = (hi - lo) / 2
rmin, rmax = round(HALF - half) + MARGIN, round(HALF + half) - MARGIN

bus.write("Homing_Offset", j, new_offset, normalize=False)
bus.write("Min_Position_Limit", j, rmin, normalize=False)
bus.write("Max_Position_Limit", j, rmax, normalize=False)
now = bus.read("Present_Position", j, normalize=False)
bus.disconnect(disable_torque=False)

path = robot.calibration_fpath
cal = json.loads(path.read_text())
old_mid = (cal[j]["range_min"] + cal[j]["range_max"]) / 2
cal[j].update(homing_offset=int(new_offset), range_min=int(rmin), range_max=int(rmax))
path.write_text(json.dumps(cal, indent=4) + "\n")

# Recorded poses store this joint in the OLD degree frame. A fixed physical position reads
# frame_new = frame_old - shift, and degrees are (frame - mid) scaled, so every stored value
# moves by the same delta. Shift them so each pose still means the same physical position.
delta = (old_mid - shift - (rmin + rmax) / 2) * 360 / (TICKS - 1)
pose_file = Path(__file__).resolve().parents[1] / "robot" / "poses" / f"{args.id}.json"
if pose_file.exists() and abs(delta) > 0.01:
    data = json.loads(pose_file.read_text())
    pose_file.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}").write_text(pose_file.read_text())
    n = 0
    for pose in data.get("poses", {}).values():
        pose[j] = round(pose[j] + delta, 2); n += 1
    for pair in data.get("fret_anchors", {}).values():
        for pose in pair.values():
            pose[j] = round(pose[j] + delta, 2); n += 1
    pose_file.write_text(json.dumps(data, indent=2) + "\n")
    print(f"shifted '{j}' by {delta:+.2f} deg in {n} recorded poses (backup saved next to {pose_file.name})")
print(f"{j}: homing_offset {old_offset} -> {new_offset}, range {rmin}-{rmax} "
      f"({(rmax - rmin) * 360 / (TICKS - 1):.0f} deg), reads {now} right now. Saved {path}")
