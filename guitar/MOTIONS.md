# Callable guitar motions

`motions.py` provides functions as methods on one connected session. **Importing it
never connects or moves hardware. `connect()` defaults to a fake arm.** No model/API
key, camera, or microphone is needed for these motions.

This is the current low-level callable interface, not the complete target rehearsal
controller. [DESIGN.md](DESIGN.md) owns scope and [STATUS.md](STATUS.md) records gaps.
A fake arm is a test double, not a physics simulator or a hardware timing model.

The operator identifies IDs **7–12** as the working arm. IDs are addresses, not a
hardware-health test. Older notes and scripts associate this arm with a base fault;
the new API explicitly selects normal **position** control instead of automatically
using that workaround. This change has software tests, not new physical validation.

## Try the functions without hardware

From the repository root:

```bash
cd guitar
.venv/bin/python
```

```python
from motions import connect

arm = connect()                       # fake=True by default; no serial access
print(arm.available())                # supported spots and all saved pose names
print(arm.where())
arm.ready()
arm.hover("A5")                      # approach above A string, fret 5
arm.touch("A5")                      # lower to saved contact, no extra pressure
arm.press("A5", press_mm=1.0)         # fake example; physical depth must be qualified
arm.release()                        # lift to hover; keep the tool clamped
arm.hover("G3")                      # move to G string, fret 3
arm.rest()                           # return via ready, after lifting if needed
arm.disconnect()
```

## Real hardware

**Operator review required before using the connection example below.** The latest
[operator note](../AGENTS.md) records motor 12 at live grip limit **110** after a 75 C
incident, without sustained thermal qualification. The inspected plugin default is still
**180**, and `connect()` / `RealArm` do not expose/pass a grip-torque override. A reconnect
can therefore restore the wrong setting. Resolve that configuration/protection path with
the operator first; do not treat this example as clearance to reconnect or run a sweep.
No grip-setting or controller-code change is made by these documentation updates.

Install the project's hardware dependencies first (the small test environment alone
is not enough):

```bash
# From the repository root; use your configured Python package index.
uv pip install --python guitar/.venv/bin/python -e 'guitar[dev]'
```

The saved `robot/poses/fret_arm.json` and `robot/calibration/fret_arm.json` must
belong to **this physical arm and guitar placement**. Repositioning the guitar or
changing a joint's calibration invalidates saved spatial poses. These guards are
not a collision model or a force sensor.

LeRobot expects the matching calibration at:
`~/.cache/huggingface/lerobot/calibration/robots/astra_so101/fret_arm.json`
(unless your LeRobot cache configuration overrides that location). After verifying
that the versioned calibration belongs to your arm, install it there if missing.
The new connection path refuses mismatched servo calibration instead of silently
rewriting it. It also checks calibration IDs against the configured motor map.

With the arm secured, the workspace clear, and power cutoff within reach, start a
Python REPL from `guitar/` and call motions **one at a time**:

```python
from motions import connect

arm = connect(
    fake=False,                      # explicit hardware opt-in
    port="/dev/cu.usbmodem5B790163191",
    arm_id="fret_arm",
    motor_id_offset=6,               # IDs 7–12
    base_mode="position",            # normal working base servo
)
print(arm.where())
# Now invoke individual functions from the table below while watching the arm.
```

**Connecting enables body holding torque and clamps the tool.** It is not a
read-only operation. **Disconnecting releases body torque** without moving to
rest; support the arm first so it cannot fall. The gripper stays clamped. Do not
reconnect while pressing a string: contact state belongs to the current session.

### Operator rule: never loosen the hands during normal operation

Keep both grippers clamped during motions, rest, disconnect, and routine shutdown.
Only body-joint torque should be released. `release()` lifts off a string; it must
not open the hand. Opening a gripper requires the operator's explicit request.
Emergency, thermal, or electrical protection is the exception: warn the operator
to support the tool and explain any necessary gripper power removal. Do not bypass
thermal protection. See the persistent instructions in `../AGENTS.md`.

A D1 hold reported 75 C on gripper motor 12. Sustained clamping is not thermally
verified; do not increase torque or start unattended sweeps to work around this.

You may use `with connect(...) as arm:` for automatic disconnect on exit or error.
There is deliberately no automatic return-to-rest motion on an exception.

## Motion functions

| Call | Behavior |
|---|---|
| `arm.available()` | List poses and supported spots; no movement |
| `arm.where()` | Read nearest pose or held fret; no movement |
| `arm.ready(speed=0.3)` | Lift if pressing, then move to saved entry pose |
| `arm.hover("A5", speed=0.3)` | Lift before travel; enter through ready if necessary |
| `arm.touch("A5", speed=0.3)` | Hover, then lower to recorded contact |
| `arm.press("A5", press_mm=1, speed=0.3)` | Hover/contact, then add depth along saved approach |
| `arm.release(speed=0.3)` | Lift off held fret; does not open gripper |
| `arm.rest()` | Lift, exit via ready, then rest at speed 0.3 |
| `arm.move_to("above_s5_f5")` | Recall a saved pose with hover/contact routing |
| `arm.pluck(depth_mm=1, speed=0.3)` | Only for a map with `above_string`, `pluck_start`, `pluck_end` |
| `arm.disconnect()` | Release body torque; retain tool clamp; no return movement |

The bundled map has `rest`, `ready`, and **54 above/touch pairs**, covering six
strings and frets 1–9. These include recorded anchors **and interpolated poses**;
not every point has been physically verified. It has **no plucking poses**, so
`pluck()` intentionally rejects on this map. No new trajectories or song sequences
are presented as learned physical motions.

Spot spelling: `e` = low E, `A`, `D`, `G`, `B`, `E` = high E. For example `e1`,
`A5`, `G3`, `E9`. Only the two E strings are case-sensitive.

Speed is a scale in **0.2–1.0**, not degrees/second. Press depth accepts **0–8 mm**
and is a pose-map estimate, not measured force or guaranteed millimeters at the tip.
These are API bounds, **not a qualified physical exploration range**; the rehearsal agent
must be restricted to the operator-approved subset/profiles. In this wrapper,
invalid/nonfinite depth and speed values are rejected rather than silently clamped. Range,
workspace, segment-swing, speed, drift and tracking guards remain active. A guard
error means stop and inspect the setup, not raise the limit to force the move.

`base_mode="speed"` retains the legacy workaround for a specifically diagnosed
base servo; do not select it just because the motor IDs are 7–12. Older scripts
still have their historical defaults. Use this API for the explicit mode choice.

## Planning and rehearsal proposals

[PLANNING.md](PLANNING.md) documents the state-aware sequence planner. `Arm.fret()` already
lifts and moves between frets without mandatory global rest. Proposed same-fret reuse and
other optimizations must preserve required clearance, pick reset, and bounded holding time.
Fake-arm timing and the current partial timing fields are not real settle-time labels.

[REHEARSAL_LOOP.md](REHEARSAL_LOOP.md) describes optional audio-model feedback into the
planner over a few attempts. That changes plans/context, not model weights.
[FINETUNING.md](FINETUNING.md) explains why weight training is deferred, not a prerequisite.
Neither proposal authorizes unattended hardware attempts or overrides `AGENTS.md`.

## Software validation

From the repository root:

```bash
guitar/.venv/bin/python -m pytest guitar/tests/test_motions.py guitar/tests/test_embodied.py -q
```

Tests cover fake motion sequences, lift-before-travel, contact state, invalid
inputs, missing poses, context cleanup, normal/workaround base routing, calibration
mismatch refusal, and rejection before gripper writes. These tests do not certify
physical clearance or the health of either arm.
