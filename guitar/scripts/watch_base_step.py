"""Watched base (shoulder_pan) step test: what the arm physically does vs what its encoder says.

Other joints hold still. The base gets a small goal step; motion is aborted at 8 deg of
encoder travel either way. You report what you SAW; both go to runs/base-step-<time>.json.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402

TICKS_PER_DEG = 4095 / 360
P = "shoulder_pan"
r = AstraSO101(AstraSO101Config(port="/dev/cu.usbmodem5B790163191", id="fret_arm", motor_id_offset=6, clamp_gripper=True))
b = r.bus
b.connect()
body = [m for m in b.motors if m != "gripper"]
results = []


def release():
    for m in body:
        for _ in range(3):
            try:
                b.write("Torque_Enable", m, 0)
                break
            except RuntimeError:
                time.sleep(0.05)


try:
    for label, deg in (("+5 deg (toward the FRET 9 / body end)", 5), ("-5 deg (toward the FRET 1 / nut end)", -5)):
        pres = b.sync_read("Present_Position", normalize=False)
        b.sync_write("Goal_Position", {m: pres[m] for m in body}, normalize=False)
        b.enable_torque(body)
        input(f"\nWatch the BASE. Enter to command {label} ")
        p0 = pres[P]
        b.write("Goal_Position", P, p0 + round(deg * TICKS_PER_DEG), normalize=False)
        trace, t0, aborted = [], time.monotonic(), False
        while time.monotonic() - t0 < 1.5:
            p = b.read("Present_Position", P, normalize=False)
            trace.append(round((p - p0) / TICKS_PER_DEG, 1))
            if abs(p - p0) > 8 * TICKS_PER_DEG:
                aborted = True
                break
            time.sleep(0.03)
        release()
        seen = input("What did the base physically do?  [9] toward fret 9 end  [1] toward fret 1 end  [0] nothing: ").strip()
        stopped = input("Did it stop by itself near 5 deg? [y/n]: ").strip()
        rec = {"command_deg": deg, "encoder_final_deg": trace[-1], "encoder_trace_deg": trace[::3],
               "aborted_at_8deg": aborted, "seen": seen, "stopped_near_target": stopped}
        results.append(rec)
        print(f"   encoder says moved {trace[-1]:+.1f} deg{' (aborted)' if aborted else ''}; you saw [{seen}]")
finally:
    release()
    b.disconnect(disable_torque=False)
    out = Path(__file__).resolve().parents[1] / "runs" / f"base-step-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nsaved {out}")
