"""Send the fret arm's fingertip to the hover position over any string/fret by name.

    .venv/bin/python scripts/hover.py                # interactive
    .venv/bin/python scripts/hover.py A5             # one move, then keep holding and exit
    .venv/bin/python scripts/hover.py --power-base   # once the base servo is replaced

Names: string letter + fret 1-9. e = low E (6th), A, D, G, B, E = high E (1st).
Only e/E are case-sensitive. Also: ready, rest, release, where, help, q.

Default mode keeps the faulty base servo unpowered: you turn the base by hand (live readout),
the other joints move by themselves. --power-base drives every joint through robot/arm.py
(swing guard, entry via 'ready', collision stop).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robot import fretmap  # noqa: E402
from robot import poses as pose_store  # noqa: E402
from robot.guards import GuardError  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("spot", nargs="?", help="one-shot target, e.g. A5")
ap.add_argument("--port", default="/dev/cu.usbmodem5B790163191")
ap.add_argument("--id", default="fret_arm")
ap.add_argument("--offset", type=int, default=6)
ap.add_argument("--power-base", action="store_true")
ap.add_argument("--speed", type=float, default=0.3, help="--power-base speed (0.2-1.0)")
args = ap.parse_args()

poses = pose_store.load(args.id)["poses"]
avail = fretmap.available(poses)


def resolve(cmd: str) -> tuple[str, str]:
    """-> (pose name, label)"""
    if cmd in ("ready", "rest"):
        if cmd not in poses:
            raise ValueError(f"no '{cmd}' pose recorded")
        return cmd, cmd
    s, f = fretmap.parse_spot(cmd)
    if f not in avail.get(s, []):
        raise ValueError(f"{cmd}: string {s} fret {f} is not calibrated")
    return fretmap.name("above", s, f), f"{fretmap.spot_name(s, f)} (string {s}, fret {f}) hover"


if args.power_base:
    from robot.arm import RealArm
    arm = RealArm(args.port, args.id, args.offset)
    arm.connect()

    def go(name: str) -> str:
        if name.startswith("above_s") and not arm._in_fret_region():
            arm.move_to("ready", args.speed)          # enter the fretboard the safe way
        arm.move_to(name, args.speed)
        return str(arm.state())

    def release():
        arm.disconnect()

    def where() -> str:
        return str(arm.state())
else:
    from robot.manual_base import ManualBaseArm
    arm = ManualBaseArm(args.port, args.id, args.offset)
    arm.connect()

    def go(name: str) -> str:
        err = arm.go(poses[name])
        worst = max(abs(v) for v in err.values())
        return f"arrived (worst joint off by {worst:.1f} deg)" + ("" if worst < 3 else f" {err}")

    def release():
        arm.release()

    def where() -> str:
        name, off = pose_store.nearest(poses, arm.read())
        s = name.removeprefix("above_s").removeprefix("touch_s").split("_f") if name.startswith(("above_s", "touch_s")) else None
        label = f"{name} ({fretmap.spot_name(int(s[0]), int(s[1]))})" if s else name
        return f"nearest pose: {label}, {off:.1f} deg away"


def run(cmd: str) -> bool:
    cmd = cmd.strip()
    if not cmd:
        return True
    if cmd in ("q", "quit", "exit"):
        return False
    if cmd == "help":
        print("  e1..e9 A1..A9 D1..D9 G1..G9 B1..B9 E1..E9  (e = low E, E = high E), ready, rest, where, release, q")
        return True
    if cmd == "where":
        print(" ", where()); return True
    if cmd == "release":
        release(); print("  released (fingertip still clamped)"); return True
    try:
        name, label = resolve(cmd)
        print(f"  -> {label}")
        print(" ", go(name))
    except (ValueError, GuardError) as e:
        print(f"  {e}")
    return True


try:
    if args.spot:
        run(args.spot)
    else:
        print("fret arm hover control. type e.g. A5, e1, E9, ready, where, release, q  (help for all)")
        while run(input("\nspot> ")):
            pass
except (KeyboardInterrupt, EOFError):
    print("\nstopping")
finally:
    if args.power_base:
        arm.disconnect()
    else:
        arm.close(keep_holding=True)
        print("left holding (base loose, tip clamped). release: scripts/hover.py then 'release'")
