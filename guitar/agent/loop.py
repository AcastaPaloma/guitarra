"""Embodied loop: the model sees camera + audio score, calls tools, guards run them on the arm.

    python -m agent.loop --role fret --backend astra --port /dev/cu.usbmodem5B790163191
    python -m agent.loop --role fret --backend scripted --fake-arm          # no API, no arm

Roles (current wiring, verified 2026-09-19): fret arm = IDs 7-12 on /dev/cu.usbmodem5B790163191
-> --id fret_arm --offset 6 (the defaults). The pluck arm is not connected yet.

Ctrl-C at any time: the arm goes to `rest` slowly, then torque is released.
Every run is recorded under runs/<timestamp>-<backend>/ (frames + decisions.jsonl).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import backends  # noqa: E402
from agent.tools import Toolbox, ToolResult, specs  # noqa: E402
from robot import fretmap  # noqa: E402
from robot.arm import FakeArm, RealArm  # noqa: E402
from robot.guards import GuardError  # noqa: E402

SYSTEM_FRET = """\
You control the fretting arm of a robot guitarist: one SO-101 arm holding a rubber fingertip, \
beside the neck of an electric guitar lying flat and face up, standard tuning (string 6 = E2 ... \
string 1 = E4). Someone else plucks the string after you press - your job is the left hand. \
A camera (an iPad at string height) shows the neck and your arm. A microphone scores each note.

Your goal: {goal}.

How you act:
- You never set joint angles. You call tools: fret(string, fret, press_mm, speed), release(speed), \
move_to(named pose, only when no fret is held), look(), done(reason). A safety layer checks \
every motion before it runs and rejects anything outside the recorded workspace or too fast; \
a rejection costs you the turn, so read it.
- fret result: "expected" is the note that fret should sound; "score" has rang, pitch, onsets. \
Pitch equal to the open string means you did not hold the string down; extra onsets or a \
wrong nearby pitch suggest buzzing or pressing in the wrong spot. The camera shows where the \
tip landed relative to the fret wire.
- Start light and change one parameter per attempt. Before each tool call, say in one sentence \
what you saw and why you are changing what you change - that sentence is the run's narration.
- Call done when the goal is met, or when you are stuck and a human needs to adjust the rig \
(for example re-record a fret pose). You have at most {turns} tool calls.
"""

SYSTEM_PLUCK = """\
You control one SO-101 robot arm holding a guitar pick, next to an electric guitar lying flat \
and face up. One string is live (target note {target}); the others are muted with foam. A camera \
(an iPad at string height) shows the neck and the arm. A microphone scores every pluck.

Your goal: produce {goal}.

How you act:
- You never set joint angles. You call tools: move_to(named pose), pluck(depth_mm, speed), \
look(), done(reason). A safety layer checks every motion before it runs and rejects anything \
outside the recorded workspace or too fast; a rejection costs you the turn, so read it.
- pluck result "score": rang (did it sound), level_over_floor_db, onsets (1 = clean, more = \
buzz or snag, 0 = silent), pitch vs target.
- Start conservative (shallow, slow) and change one parameter per attempt. Before each tool \
call, say in one sentence what you saw and why you are changing what you change - that \
sentence is the narration of the run.
- Call done when the goal is met, or when you are stuck and a human needs to adjust the rig. \
You have at most {turns} tool calls.
"""


def load_env(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines) so keys never live in code or shell history."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Recorder:
    def __init__(self, backend: str):
        self.dir = ROOT / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{backend}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def frame(self, jpeg: bytes | None) -> str | None:
        if not jpeg:
            return None
        self.n += 1
        name = f"frame_{self.n:03d}.jpg"
        (self.dir / name).write_bytes(jpeg)
        return name

    def log(self, **rec) -> None:
        with (self.dir / "decisions.jsonl").open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="claude", help="claude | astra | scripted")
    ap.add_argument("--model", help="override the backend's default model id")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--port")
    ap.add_argument("--role", choices=["fret", "pluck"], default="fret")
    ap.add_argument("--id", help="calibration/pose id (default: fret_arm or pluck_arm)")
    ap.add_argument("--offset", type=int, help="motor ID offset (default: 6 for fret, 0 for pluck)")
    ap.add_argument("--fake-arm", action="store_true", help="no hardware; motion is simulated")
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--target", default="A2", help="open note of the live string")
    ap.add_argument("--goal", help="override the role's default goal")
    ap.add_argument("--turns", type=int, default=20, help="max tool calls")
    ap.add_argument("--minutes", type=float, default=15, help="wall-clock cap")
    ap.add_argument("--max-deg-per-s", type=float, help="joint speed cap at speed=1.0 (default robot.arm.MAX_DEG_PER_S)")
    args = ap.parse_args()
    args.id = args.id or f"{args.role}_arm"
    args.offset = (6 if args.role == "fret" else 0) if args.offset is None else args.offset
    args.goal = args.goal or (
        "find press settings that make each calibrated string/fret you test sound its expected note "
        "cleanly (correct pitch, one onset), then report the press_mm that works"
        if args.role == "fret" else "three clean plucks in a row (rang, 1 onset, correct pitch)"
    )
    load_env(ROOT / ".env")
    if args.max_deg_per_s:
        import robot.arm
        robot.arm.MAX_DEG_PER_S = min(args.max_deg_per_s, robot.arm.MAX_DEG_PER_S)  # can only lower it

    if args.fake_arm:
        arm = FakeArm(args.id)
    else:
        if not args.port:
            sys.exit("--port is required unless --fake-arm")
        arm = RealArm(args.port, args.id, args.offset)

    kw = {"effort": args.effort, **({"model": args.model} if args.model else {})}
    backend = backends.make(args.backend, **({"role": args.role} if args.backend == "scripted" else kw))
    rec = Recorder(args.backend)
    mic = None

    arm.connect()
    try:
        if not args.no_mic:
            from sense.mic import Mic
            mic = Mic().start()
            print(f"mic noise floor (arm holding): {mic.measure_floor():.1f} dB")
        tools = Toolbox(arm, mic, args.target, use_camera=not args.no_camera)
        pose_names = sorted(arm.poses)
        frets = fretmap.available(arm.poses)
        if args.role == "fret" and not frets:
            sys.exit(f"no fret map for '{args.id}' - run scripts/record_fret_map.py")
        system = (SYSTEM_FRET if args.role == "fret" else SYSTEM_PLUCK).format(
            target=args.target, goal=args.goal, turns=args.turns)

        # Start every run from a known pose, before the model gets control: a far-off start pose
        # otherwise makes every model request fail the swing guard (run 20260919-033700).
        if "ready" in arm.poses:
            try:
                arm.move_to("ready", speed=0.3)
            except GuardError as e:
                print(f"\nNOT STARTING: could not reach 'ready':\n  {e}\n"
                      "If a swing was refused: move the arm by hand near rest/ready and rerun. If a joint fell\n"
                      "behind, it was blocked or faulty - see scripts/verify_fret_map.py / servo checks first.")
                return

        img, cam_err = tools._frame()
        opening = json.dumps({"arm": arm.state(), "poses": pose_names,
                              **({"calibrated_frets": {f"string {k}": v for k, v in frets.items()}}
                                 if args.role == "fret" else {}),
                              **({"camera": cam_err} if cam_err else {})})
        rec.log(turn=0, event="start", backend=args.backend, args=vars(args), observation=opening, frame=rec.frame(img))
        print(f"run -> {rec.dir}\n")

        turn = backend.begin(system, specs(pose_names, args.role, frets), f"Session start. Current observation: {opening}", img)
        deadline = time.monotonic() + args.minutes * 60
        used = 0
        while True:
            if turn.text:
                print(f"[{backend.name}] {turn.text}")
            rec.log(turn=used, event="model", text=turn.text, thinking=turn.thinking,
                    calls=[c.__dict__ for c in turn.calls], stop=turn.stop, usage=turn.usage)
            if turn.stop == "refusal":
                print("model refused - stopping"); break
            if not turn.calls:
                print("model ended its turn without a tool call - stopping"); break

            results = []
            for call in turn.calls:
                used += 1
                print(f"  -> {call.name}({json.dumps(call.args)})")
                r = tools.run(call)
                print(f"     {r.text}")
                rec.log(turn=used, event="tool", frame=rec.frame(r.image_jpeg), **r.record)
                results.append(r)
                if r.is_error:
                    break  # don't run later calls planned on top of a rejected one
            # any calls skipped after a rejection still need a result
            done_ids = {r.call_id for r in results}
            for call in turn.calls:
                if call.id not in done_ids:
                    results.append(ToolResult(call.id, '{"ok": false, "skipped": "an earlier call in this turn was rejected"}', is_error=True))

            if tools.finished is not None:
                print(f"\ndone: {tools.finished}"); break
            left = args.turns - used
            if left <= 0 or time.monotonic() > deadline:
                print("\nbudget exhausted - stopping"); break
            turn = backend.respond(results, note=f"{left} tool calls left.")
    except KeyboardInterrupt:
        print("\nCtrl-C - returning to rest (Ctrl-C again to drop torque immediately)")
    finally:
        try:
            arm.rest()
        except KeyboardInterrupt:
            pass
        except Exception as e:  # noqa: BLE001 - never let cleanup skip disconnect
            print(f"could not return to rest: {e}")
        arm.disconnect()
        if mic:
            mic.stop()
        print(f"arm released. run recorded in {rec.dir}")


if __name__ == "__main__":
    main()
