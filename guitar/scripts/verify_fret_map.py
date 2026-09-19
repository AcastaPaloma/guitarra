"""Check the fret map on the real arm: visit each position slowly and touch (or press) it.

    python scripts/verify_fret_map.py                         # every string, frets 1-9, touch only
    python scripts/verify_fret_map.py --strings 5 --frets 1 2 3 --press 3 --listen
        --listen: after each press, pluck the string; the mic checks the pitch

Moves the arm (torque on). Watch it; Ctrl-C returns to rest and releases the body joints
(the fingertip stays clamped). Results go to runs/verify-<time>.jsonl.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from robot import fretmap  # noqa: E402
from robot.arm import RealArm  # noqa: E402
from robot.guards import GuardError  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--offset", type=int, default=6)
ap.add_argument("--strings", type=int, nargs="+")
ap.add_argument("--frets", type=int, nargs="+")
ap.add_argument("--press", type=float, default=0.0, help="mm past touch (0 = just touch)")
ap.add_argument("--speed", type=float, default=0.3)
ap.add_argument("--listen", action="store_true")
args = ap.parse_args()

arm = RealArm(args.port, args.id, args.offset)
avail = fretmap.available(arm.poses)
targets = [(s, f) for s, frets in avail.items() if not args.strings or s in args.strings
           for f in frets if not args.frets or f in args.frets]
if not targets:
    sys.exit(f"nothing to verify; calibrated: {avail}")

mic = None
if args.listen:
    from sense.mic import Mic, transpose, wait_for_pluck
    mic = Mic().start()

print("will touch: " + ", ".join(f"{fretmap.spot_name(s, f)}" for s, f in targets))
input("Watch the arm, hand near the power. Enter to start (Ctrl-C any time)... ")
log = ROOT / "runs" / f"verify-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
log.parent.mkdir(exist_ok=True)
arm.connect()
try:
    if mic:
        print(f"mic floor {mic.measure_floor():.1f} dB")
    for i, (s, f) in enumerate(targets, 1):
        rec = {"string": s, "fret": f, "press_mm": args.press}
        try:
            arm.fret(s, f, args.press, speed=args.speed)
            rec["arm"] = arm.state()
            if mic:
                expected = transpose(fretmap.STANDARD_TUNING[s], f)
                print(f"   >>> PLUCK string {s} now (expecting {expected})")
                rec["score"] = wait_for_pluck(mic, expected)
            else:
                time.sleep(0.6)
            arm.release(speed=args.speed)
        except GuardError as e:
            rec["rejected"] = str(e)
            print(f"[{i}/{len(targets)}] {fretmap.spot_name(s, f)} (string {s} fret {f}): REJECTED {e}")
            break
        print(f"[{i}/{len(targets)}] {fretmap.spot_name(s, f)} (string {s} fret {f}): ok" + (f"  {rec['score']}" if "score" in rec else ""))
        with log.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
except KeyboardInterrupt:
    print("\nstopping")
finally:
    try:
        arm.rest()
    except Exception as e:  # noqa: BLE001
        print(f"could not return to rest: {e}")
    arm.disconnect()
    if mic:
        mic.stop()
    print(f"log: {log}")
