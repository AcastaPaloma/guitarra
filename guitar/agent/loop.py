"""Guitar agent: arm state and available audio feedback; camera input is OFF by default.

    python -m agent.loop --role fret --backend scripted --fake-arm --no-mic

Use --camera only to opt into snapshots from a separately started local camera relay.
--no-camera remains an explicit off switch. Neither option starts the relay itself.

Hardware requires separate operator qualification; see SETUP.md and ../AGENTS.md.
The existing loop attempts rest in cleanup, then releases body torque while retaining
its tool clamp. This is not an independent emergency-stop/watchdog implementation.
Run logs contain decisions.jsonl; JPEGs are recorded only when frames are supplied.
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
You control the fretting arm of a robot guitarist: one SO-101 holding a rubber fingertip,
beside an electric guitar in standard tuning (string 6 = E2 ... string 1 = E4).
Someone else plucks after you press; this session controls the fretting arm only.

Your goal: {goal}.

Available observations:
{observations}

How you act:
- Never set joint angles, change calibration/grip settings, or bypass a rejection.
  Use fret(string, fret, press_mm, speed), release(speed), move_to(named pose, only when
  no fret is held), look(), and done(reason). Local guards check configured motion limits;
  those checks do not establish contact force or permission to explore unqualified settings.
- The fret result's "expected" is the intended note, not proof that it sounded. Use actual
  provided measurements only. Missing or ambiguous feedback is unknown, not success or a
  definite mechanical diagnosis. Multiple onsets alone do not prove buzzing or snagging.
- Use only operator-qualified settings. When an adjustment is permitted, change one factor
  at a time and give a concise reason based on the observations actually provided.
- look() reads arm state without moving; its description says whether images are enabled.
- Call done when the goal is met or operator review is needed. Do not invent missing
  observations or claim progress without evidence. You have at most {turns} tool calls.
"""

SYSTEM_PLUCK = """\
You control one SO-101 arm holding a guitar pick beside an electric guitar.
Use the recorded plucking capability for the selected string (target note {target}).

Your goal: produce {goal}.

Available observations:
{observations}

How you act:
- Never set joint angles, change calibration/grip settings, or bypass a rejection.
  Use move_to(named pose), pluck(depth_mm, speed), look(), and done(reason). Local guards
  check configured motion limits; these are not contact-force or acoustic guarantees.
- Use audio estimates only when provided. No clear sound can mean a capture problem,
  not necessarily a missed pick. Onset count alone does not establish clean sound or snagging.
  A commanded pose and target note are not proof of a successful audible performance.
- Use only operator-qualified settings. When an adjustment is permitted, change one factor
  at a time and give a concise reason based on the observations actually provided.
- look() reads arm state without moving; its description says whether images are enabled.
- Call done when the goal is met or operator review is needed. Do not invent missing
  observations or claim progress without evidence. You have at most {turns} tool calls.
"""


def build_system_prompt(role: str, *, goal: str, target: str, turns: int,
                        use_camera: bool = False, use_mic: bool = False) -> str:
    """Describe only the enabled inputs; camera-free runs must not imply visual evidence."""
    if use_camera:
        camera_note = (
            "Camera input is enabled by explicit opt-in. A snapshot may be attached from the "
            "local relay. If it is missing or stale, do not assume visual evidence is available."
        )
    else:
        camera_note = (
            "Camera input is disabled. No images or video are provided. Use the supplied "
            "named-pose/tool state; do not claim to see the guitar or request camera frames."
        )
    if use_mic:
        mic_note = (
            "Microphone input is enabled. Tools may return local pitch/onset/level estimates, "
            "not raw audio or a separate audio-model critique. Treat missing/noisy data as uncertain."
        )
    else:
        mic_note = (
            "Microphone input is disabled. No acoustic measurement is available. Do not infer "
            "sound quality from a commanded pose, the expected note, or an image."
        )
    template = SYSTEM_FRET if role == "fret" else SYSTEM_PLUCK
    return template.format(goal=goal, target=target, turns=turns,
                           observations=f"- {camera_note}\n- {mic_note}")


def load_env(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines) so keys never live in code or shell history."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse configuration without accessing devices, credentials, or model APIs."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="baseten", help="baseten (default) | baseten-custom | claude | astra | scripted")
    ap.add_argument("--model", help="override model (Baseten Model API slug, e.g. moonshotai/Kimi-K3)")
    ap.add_argument("--effort", help="override backend reasoning effort; Baseten uses .env or high")
    ap.add_argument("--port")
    ap.add_argument("--role", choices=["fret", "pluck"], default="fret")
    ap.add_argument("--id", help="calibration/pose id (default: fret_arm or pluck_arm)")
    ap.add_argument("--offset", type=int, help="motor ID offset (default: 6 for fret, 0 for pluck)")
    ap.add_argument("--fake-arm", action="store_true", help="no hardware; motion is simulated")
    ap.add_argument("--no-mic", action="store_true")
    camera_flags = ap.add_mutually_exclusive_group()
    camera_flags.add_argument(
        "--camera", dest="use_camera", action="store_true",
        help="opt into camera snapshots from a separately started relay (default: off)",
    )
    camera_flags.add_argument(
        "--no-camera", dest="use_camera", action="store_false",
        help="keep camera input disabled (default; retained for compatibility)",
    )
    ap.set_defaults(use_camera=False)
    ap.add_argument("--target", default="A2", help="open note of the live string")
    ap.add_argument("--goal", help="override the role's default goal")
    ap.add_argument("--turns", type=int, default=20, help="max tool calls")
    ap.add_argument("--minutes", type=float, default=15, help="wall-clock cap")
    ap.add_argument("--max-deg-per-s", type=float, help="joint speed cap at speed=1.0 (default robot.arm.MAX_DEG_PER_S)")
    return ap.parse_args(argv)


def main() -> None:
    args = parse_args()
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

    kw = {**({"effort": args.effort} if args.effort else {}),
          **({"model": args.model} if args.model else {})}
    backend = backends.make(args.backend, **({"role": args.role} if args.backend == "scripted" else kw))
    rec = Recorder(args.backend)
    mic = None

    arm.connect()
    try:
        if not args.no_mic:
            from sense.mic import Mic
            mic = Mic().start()
            print(f"mic noise floor (arm holding): {mic.measure_floor():.1f} dB")
        tools = Toolbox(arm, mic, args.target, use_camera=args.use_camera)
        pose_names = sorted(arm.poses)
        frets = fretmap.available(arm.poses)
        if args.role == "fret" and not frets:
            sys.exit(f"no fret map for '{args.id}' - run scripts/record_fret_map.py")
        system = build_system_prompt(
            args.role, target=args.target, goal=args.goal, turns=args.turns,
            use_camera=args.use_camera, use_mic=mic is not None,
        )

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
                              "inputs": {"camera": "enabled" if args.use_camera else "disabled",
                                         "microphone": "enabled" if mic is not None else "disabled"},
                              **({"calibrated_frets": {f"string {k}": v for k, v in frets.items()}}
                                 if args.role == "fret" else {}),
                              **({"camera": cam_err} if cam_err else {})})
        rec.log(turn=0, event="start", backend=args.backend, model=getattr(backend, "model", None),
                args=vars(args), observation=opening, frame=rec.frame(img))
        print(f"run -> {rec.dir}\n")

        tool_specs = specs(pose_names, args.role, frets,
                           use_camera=args.use_camera, use_mic=mic is not None)
        turn = backend.begin(system, tool_specs, f"Session start. Current observation: {opening}", img)
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
