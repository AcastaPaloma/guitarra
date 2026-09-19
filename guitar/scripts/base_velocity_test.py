"""Can the base (shoulder_pan) turn both ways at all? Speed-mode test, bypassing position control.

The base only ever drives one way in position mode. Here it goes into constant-speed mode
(Operating_Mode 1) and gets a slow push each way (~9 deg/s), each cut off after 5 deg or 1 s.
Afterwards the servo is put back into position mode (verified). You report what you saw.
Log: runs/base-velocity-<time>.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402

P = "shoulder_pan"
SPEED = 100            # steps/s, 4096 steps per turn -> ~8.8 deg/s
STOP_DEG = 5.0
r = AstraSO101(AstraSO101Config(port="/dev/cu.usbmodem5B790163191", id="fret_arm", motor_id_offset=6, clamp_gripper=True))
b = r.bus
b.connect()
results = []


def to_position_mode():
    for _ in range(3):
        try:
            b.write("Goal_Velocity", P, 0)
            b.write("Torque_Enable", P, 0)
            b.write("Lock", P, 0)
            b.write("Operating_Mode", P, 0)
            b.write("Lock", P, 1)
            b.write("Torque_Enable", P, 0)   # (a Goal_Position write would re-enable torque)
            return b.read("Operating_Mode", P)
        except RuntimeError:
            time.sleep(0.1)
    return None


try:
    b.write("Torque_Enable", P, 0)
    b.write("Lock", P, 0)
    b.write("Operating_Mode", P, 1)
    b.write("Goal_Velocity", P, 0)
    b.write("Torque_Enable", P, 1)
    for label, v in (("POSITIVE speed", SPEED), ("NEGATIVE speed", -SPEED)):
        input(f"\nWatch the base. Enter to push it at {label} (~9 deg/s, max 5 deg)... ")
        p0 = b.read("Present_Position", P)
        b.write("Goal_Velocity", P, v)
        trace, t0 = [], time.monotonic()
        while time.monotonic() - t0 < 1.0:
            pos = b.read("Present_Position", P)
            trace.append(round(pos - p0, 1))
            if abs(pos - p0) >= STOP_DEG:
                break
            time.sleep(0.02)
        b.write("Goal_Velocity", P, 0)
        load = b.read("Present_Load", P, normalize=False)
        seen = input("Which way did it turn?  [ccw] counter-clockwise  [cw] clockwise  [0] nothing  (seen from above): ").strip()
        rec = {"command": label, "goal_velocity": v, "encoder_moved_deg": trace[-1], "trace": trace[::5],
               "load_after": load & 0x3FF, "seen": seen}
        results.append(rec)
        print(f"   encoder moved {trace[-1]:+.1f} deg; you saw [{seen}]")
        time.sleep(0.3)
finally:
    mode = to_position_mode()
    b.disconnect(disable_torque=False)
    out = ROOT / "runs" / f"base-velocity-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"results": results, "restored_operating_mode": mode}, indent=2))
    print(f"\nbase back in position mode: {'yes' if mode == 0 else 'NO - check it! mode=' + str(mode)}; torque off. log: {out}")
