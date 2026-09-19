"""Step the base (shoulder_pan, lowest pivot) in 5-degree increments and record where it settles.

    python scripts/base_sweep.py                 # 6 steps of +5 deg, then back to the start
    python scripts/base_sweep.py --step 5 --steps 6

Other joints are left as they are (holding if powered). Each step: command the base, watch
~1.2 s. The sweep aborts and releases the base if it goes > 3 deg past a target or > 3 deg the
wrong way. Log: runs/base-sweep-<time>.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lerobot_robot_astra import AstraSO101, AstraSO101Config  # noqa: E402

P = "shoulder_pan"
LIMIT_LO, LIMIT_HI = -53.0, 19.0     # base range used by the fret poses
BAD_DEG = 3.0

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=float, default=5.0)
ap.add_argument("--steps", type=int, default=6)
ap.add_argument("--settle", type=float, default=1.2)
args = ap.parse_args()

r = AstraSO101(AstraSO101Config(port="/dev/cu.usbmodem5B790163191", id="fret_arm", motor_id_offset=6, clamp_gripper=True))
b = r.bus
b.connect()


def base_off():
    for _ in range(3):
        try:
            b.write("Torque_Enable", P, 0)
            return
        except RuntimeError:
            time.sleep(0.05)


start = b.read("Present_Position", P)
direction = 1 if start + args.step * args.steps <= LIMIT_HI else -1
targets = [start + direction * args.step * i for i in range(1, args.steps + 1)]
targets += list(reversed(targets[:-1])) + [start]
targets = [t for t in targets if LIMIT_LO - 1 <= t <= LIMIT_HI + 1]
print(f"base at {start:.1f} deg. plan: " + " -> ".join(f"{t:.0f}" for t in targets))
input("Watch the base. Enter to start (Ctrl-C any time)... ")

log, verdict = [], "completed"
b.write("Goal_Position", P, start)
b.write("Torque_Enable", P, 1)
try:
    prev = start
    for i, tgt in enumerate(targets, 1):
        b.write("Goal_Position", P, tgt)
        want = 1 if tgt > prev else -1
        trace, t0, bad = [], time.monotonic(), None
        while time.monotonic() - t0 < args.settle:
            pos = b.read("Present_Position", P)
            trace.append(round(pos, 1))
            if want * (pos - tgt) > BAD_DEG:
                bad = f"overshot target by {want * (pos - tgt):.1f} deg"
            elif want * (prev - pos) > BAD_DEG:
                bad = f"went the WRONG way by {want * (prev - pos):.1f} deg"
            if bad:
                break
            time.sleep(0.03)
        pos = trace[-1]
        load = b.read("Present_Load", P, normalize=False)
        rec = {"step": i, "from": round(prev, 1), "target": round(tgt, 1), "settled": pos,
               "error": round(pos - tgt, 1), "load": load & 0x3FF, "trace": trace[::5]}
        log.append(rec)
        print(f"[{i:2d}] {prev:6.1f} -> target {tgt:6.1f}   settled {pos:6.1f}   error {pos - tgt:+5.1f}"
              + (f"   ABORT: {bad}" if bad else ""))
        if bad:
            verdict = f"aborted at step {i}: {bad}"
            break
        prev = tgt
except KeyboardInterrupt:
    verdict = "stopped by Ctrl-C"
finally:
    base_off()
    b.disconnect(disable_torque=False)
    out = ROOT / "runs" / f"base-sweep-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"verdict": verdict, "start": start, "steps": log}, indent=2))
    print(f"\n{verdict}. base released. log: {out}")
