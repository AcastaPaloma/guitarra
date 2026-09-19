"""Base sweep in 5-degree steps using software position control (robot/base_speed.py).

    python scripts/base_sweep_speed.py                 # 6 steps of +5 deg, then back
    python scripts/base_sweep_speed.py --step 5 --steps 6 --first -1   # start the other way

Other joints are left as they are. Aborts on wrong-way / overshoot > 3 deg. The base ends
unpowered and back in position mode. Log: runs/base-sweep-speed-<time>.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402
from robot.base_speed import SpeedBase  # noqa: E402
from robot.guards import GuardError  # noqa: E402

LIMIT_LO, LIMIT_HI = -53.0, 19.0     # base range used by the fret poses

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=float, default=5.0)
ap.add_argument("--steps", type=int, default=6)
ap.add_argument("--first", type=int, choices=[1, -1], help="+1 toward fret 9 first, -1 toward fret 1 first")
args = ap.parse_args()

r = AstraSO101(AstraSO101Config(port="/dev/cu.usbmodem5B790163191", id="fret_arm", motor_id_offset=6, clamp_gripper=True))
b = r.bus
b.connect()
base = SpeedBase(b)
start = base.pos()
d = args.first or (1 if start + args.step * args.steps <= LIMIT_HI else -1)
out_leg = [start + d * args.step * i for i in range(1, args.steps + 1)]
targets = [t for t in out_leg + list(reversed(out_leg[:-1])) + [start] if LIMIT_LO - 1 <= t <= LIMIT_HI + 1]
print(f"base at {start:.1f}. plan: " + " -> ".join(f"{t:.0f}" for t in targets))
input("Watch the base. Enter to start (Ctrl-C stops it)... ")

log, verdict = [], "completed"
try:
    for i, t in enumerate(targets, 1):
        t0 = time.monotonic()
        err = base.move_to(t)
        rec = {"step": i, "target": round(t, 1), "reached": round(base.pos(), 1), "error": err,
               "seconds": round(time.monotonic() - t0, 2)}
        log.append(rec)
        print(f"[{i:2d}] target {t:6.1f}  reached {rec['reached']:6.1f}  error {err:+5.2f}  ({rec['seconds']} s)")
        time.sleep(0.4)
except GuardError as e:
    verdict = f"aborted: {e}"
except KeyboardInterrupt:
    verdict = "stopped by Ctrl-C"
finally:
    base.disable()
    b.disconnect(disable_torque=False)
    out = ROOT / "runs" / f"base-sweep-speed-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"verdict": verdict, "start": start, "steps": log}, indent=2))
    print(f"\n{verdict}. base released (position mode restored). log: {out}")
