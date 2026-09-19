# agent/ — the embodied loop

```
iPad ─► Camo ─► sense/camera_relay.py ─► /astra.jpg ─┐
mic ─► sense/mic.py (ring buffer + pluck scorer) ────┼─► backend (astra | claude)
arm state (nearest named pose) ──────────────────────┘        │ tool calls
                                                              ▼
      agent/tools.py ─► robot/arm.py: poses → interpolate → robot/guards.py ─► AstraSO101 ─► arm
```

The model never sees or sets joint angles. `--role fret` (the connected arm, IDs 7–12) gets
`fret(fret, press_mm, speed)`, `release(speed)`, `move_to`, `look`, `done`; after each press it waits
for the string to be plucked (by you, for now) and scores the pitch against the fretted note.
`--role pluck` gets `pluck(depth_mm, speed)` instead. `fret` always lifts before travelling along
the neck, and `move_to` is refused while a fret is held. Every motion is planned in full, then the
guards check it (calibrated range, the workspace box around the recorded poses, a speed cap, and
"is the arm where we left it"). Anything that fails is rejected and sent back to the model as an
error; nothing is silently clamped.

| file | role |
|---|---|
| `loop.py` | CLI, turn/time budget, run recorder, Ctrl-C → rest → torque off |
| `tools.py` | provider-neutral tool specs + execution |
| `backends/claude.py` | Anthropic Messages API, `claude-opus-5`, adaptive thinking, image tool results |
| `backends/astra.py` | OpenAI Responses API, `gpt-6-astra`. Verified live 2026-09-19 (fake arm, real camera + mic) |
| `backends/scripted.py` | fixed plan, no API. Used for testing |

## The gripper always holds the tool

`AstraSO101(..., clamp_gripper=True)` (used by `robot/arm.py` and every script here) treats the
gripper as a clamp for the fingertip extension or pick. It closes on the tool at connect and keeps
squeezing at 18% torque; that's under the servo's overload trigger, which otherwise eases off or
cuts the grip after about 2 s. It ignores gripper actions and stays clamped through calibration,
pose recording and disconnect; only the five body joints ever go limp. After a power cycle, or to
reseat the tip:

```bash
.venv/bin/python scripts/grip_tool.py --open     # open, insert tip, Enter -> clamps
.venv/bin/python scripts/grip_tool.py --status   # read-only check
```

## Calibration file

LeRobot reads the joint calibration from `~/.cache/huggingface/lerobot/calibration/robots/astra_so101/fret_arm.json`.
A copy that matches `robot/poses/fret_arm.json` is versioned at `robot/calibration/fret_arm.json`. On a new
machine, or after the cache is cleared:

```bash
mkdir -p ~/.cache/huggingface/lerobot/calibration/robots/astra_so101 && cp robot/calibration/fret_arm.json ~/.cache/huggingface/lerobot/calibration/robots/astra_so101/
```
Poses and calibration belong together: recalibrating a joint changes what the stored poses mean
(`scripts/fix_joint_calibration.py` shifts the poses to match).

## Calibration file

LeRobot reads the joint calibration from `~/.cache/huggingface/lerobot/calibration/robots/astra_so101/fret_arm.json`.
The copy matching `robot/poses/fret_arm.json` is at `robot/calibration/fret_arm.json`. To restore it:

```bash
mkdir -p ~/.cache/huggingface/lerobot/calibration/robots/astra_so101 && cp robot/calibration/fret_arm.json ~/.cache/huggingface/lerobot/calibration/robots/astra_so101/
```
Poses and calibration belong together (`scripts/fix_joint_calibration.py` shifts poses when it recalibrates).

## Moving to a string/fret by name

```bash
.venv/bin/python scripts/hover.py          # interactive: type A5, e1, E9, ready, where, release, q
.venv/bin/python scripts/hover.py G3       # one move
```
`e` = low E (6th string), `A D G B`, `E` = high E (1st); frets 1-9. The fret arm's base servo is
faulty (it drives one way whatever it's told), so by default you turn the base by hand from a
live readout and the other joints move by themselves. After replacing the servo, use `--power-base`.

## One-time setup (at the arm)

1. **Calibrate** the fretting arm (CONNECT.md §5b):
   ```bash
   .venv/bin/lerobot-calibrate --robot.type=astra_so101 --robot.port=/dev/cu.usbmodem5B790163191 --robot.id=fret_arm --robot.motor_id_offset=6
   ```
2. **Record poses** (torque off, move by hand, Enter to save): `rest`, then `above_fret_N` and
   `touch_fret_N` for N = 2 3 5 7 10 (the Seven Nation Army riff on the A string):
   ```bash
   .venv/bin/python scripts/record_poses.py --role fret --port /dev/cu.usbmodem5B790163191
   ```
3. **Set the press direction** in `robot/poses/fret_arm.json` → `"depth": {"joint": ..., "deg_per_mm": ...}`.
   This is which joint pushes the tip *into* the string, and how many degrees make one mm
   (use a negative number if the joint moves the other way). The default is `wrist_flex`, `1.0`,
   which is a guess.
4. **API keys** in `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Both verified working 2026-09-19.

## Every session

1. Camera relay in Terminal.app (it holds the camera permission):
   `.venv/bin/python sense/camera_relay.py --index 1`
2. Run the loop. Start with a small budget:
   ```bash
   .venv/bin/python -m agent.loop --role fret --backend astra --port /dev/cu.usbmodem5B790163191 --turns 8
   ```
   Useful flags: `--no-mic`, `--no-camera`, `--target A2`, `--goal "..."`, `--effort low|medium|high`,
   `--fake-arm` (full loop, no hardware).
3. **Ctrl-C** stops it: the arm goes to `rest` slowly, then torque is released. Press Ctrl-C a
   second time to skip the rest move.
4. Review `runs/<timestamp>-<backend>/`: `decisions.jsonl` (model text, thinking summary, tool
   calls, scores, token usage) plus `frame_NNN.jpg` for each observation.

## Astra vs Claude

`--backend astra` (GPT-6 Astra) and `--backend claude` share the same tools, guards, recorder and
prompt. In the Guitarra band harness this loop is the guitar's *rehearsal/tuning* tool: live
performance plays pre-planned phrases locally, with no model call per note.

## Tests (no hardware, no API)

```bash
.venv/bin/python -m pytest tests/ -q
```
