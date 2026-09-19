"""Which servo ID is which physical joint? Torque off; move one joint at a time by hand.

    python scripts/identify_joints.py                 # fret arm, IDs 7-12

For each named joint you move only that joint back and forth; the script records which ID's
encoder changed most. Prints the mapping and flags any joint whose ID isn't the expected one.
The gripper keeps its clamp (it is never touched here).
"""
import argparse
import json
from pathlib import Path
import threading
import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
HOW = {
    "shoulder_pan": "rotate the WHOLE ARM around its base (left/right, like a turntable)",
    "shoulder_lift": "raise/lower the upper arm at the shoulder",
    "elbow_flex": "bend/straighten the elbow",
    "wrist_flex": "tilt the wrist up/down",
    "wrist_roll": "twist the wrist around its own axis",
}

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--first-id", type=int, default=7)
args = ap.parse_args()

ids = {j: args.first_id + i for i, j in enumerate(JOINTS)}
bus = FeetechMotorsBus(port=args.port, motors={j: Motor(i, "sts3215", MotorNormMode.RANGE_M100_100) for j, i in ids.items()})
bus.connect()
bus.disable_torque(list(JOINTS))


def raw() -> dict:
    return bus.sync_read("Present_Position", normalize=False)


found = {}
travel = {}
try:
    for joint in JOINTS:
        input(f"\n[{joint}] get ready to {HOW[joint]}.\n   Hold every other joint still with your other hand. Enter, then move ONLY this joint ~30 deg... ")
        lo = hi = raw()
        lo, hi = dict(lo), dict(hi)
        stop = threading.Event()
        threading.Thread(target=lambda: (input("   moving... press Enter when done "), stop.set()), daemon=True).start()
        while not stop.is_set():
            r = raw()
            for m, v in r.items():
                lo[m], hi[m] = min(lo[m], v), max(hi[m], v)
            time.sleep(0.03)
        moved = {m: (hi[m] - lo[m]) * 360 / 4095 for m in JOINTS}
        winner = max(moved, key=moved.get)
        found[joint] = winner
        travel[joint] = {m: round(v, 1) for m, v in moved.items()}
        second = sorted(moved.values())[-2]
        if second > 0.5 * moved[winner]:
            print(f"   WARNING: two joints moved a lot ({second:.0f} vs {moved[winner]:.0f} deg) - hold the others still; result may be wrong")
        print("   travel seen (deg):", {m: round(v) for m, v in moved.items()})
        print(f"   -> you moved '{joint}', servo that moved most: ID {ids[winner]} (named '{winner}')")
finally:
    bus.disconnect(disable_torque=False)

print("\n=== mapping ===")
ok = True
for joint, winner in found.items():
    good = joint == winner
    ok &= good
    print(f"  {joint:14s} expected ID {ids[joint]:2d}  measured ID {ids[winner]:2d}  {'ok' if good else '<-- WRONG'}")
out = Path(__file__).resolve().parents[1] / "runs" / f"identify-{time.strftime('%Y%m%d-%H%M%S')}.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"ids": ids, "measured": {j: ids[w] for j, w in found.items()}, "travel_deg": travel}, indent=2))
print(f"saved {out}")
print("all joints match their IDs" if ok and len(found) == len(JOINTS) else
      "MISMATCH: servo IDs don't match the joints - calibration and poses are mixed up")
