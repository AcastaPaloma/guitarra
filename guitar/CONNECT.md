# Same-arm hardware connection and qualification

Use the existing physical guitar rig, not replacement arms or a new bus topology chosen
from an old example. This guide is operator-owned; software documentation is not motion
approval. [../AGENTS.md](../AGENTS.md) is authoritative for clamp/thermal instructions.

**Guitar camera input is off by default.** The normal planner uses known poses/arm telemetry
and available audio feedback. `--camera` is optional diagnostic opt-in, not a replacement
for operator supervision or physical qualification; `--no-camera` keeps the default.

## 1. Recorded configuration versus current verification

| Item | Repository/operator evidence | Still required before a new run |
|---|---|---|
| Fretting role | Notes identify SO-101 follower, IDs **7–12**, `motor_id_offset=6`, `arm_id="fret_arm"` | Confirm the actual connected board/arm and present condition |
| Fretting port | `/dev/cu.usbmodem5B790163191` recorded in current motion defaults | Recheck the device; do not assume a path establishes servo health |
| Picking role | Intended second arm; no complete picking map in the supplied fret profile | Confirm connection, IDs, calibration, and a qualified pick trajectory |
| Calibration | `robot/calibration/fret_arm.json` and the driver's matching cache file | Match to this physical arm, servo settings, units, and guitar placement |
| Poses | `robot/poses/fret_arm.json`, including recorded anchors and interpolations | Qualify the actual subset and transition paths; saved targets are not blanket approval |
| Grip/protection | Operator history in `AGENTS.md` | Resolve sustained thermal behavior and live-setting versus code-default mismatch |

The old “arm B is 7–12” and “both arms definitely share one adapter” instructions are
superseded. Current notes assign 7–12 to the **fretting** arm. Do not renumber, reset,
recalibrate, or reconnect wiring to make an older diagram true.

## 2. The gripper rule

The grippers hold the fingertip and pick. Normal motion/rest/disconnect must not loosen
or open them. `release()` lifts the fingertip from the guitar string—it does not release
the tool. Ordinary disconnect releases body-joint torque; support the arm so it cannot fall.

Thermal/electrical emergencies may require removing gripper power; do not defeat protection
to maintain a grip. Warn the operator to support the tool. Read the full live history in
`AGENTS.md` rather than assuming a brief low-temperature check qualifies continuous holding.

At the inspected source state, the connection path can reapply the plugin's default grip
limit and `_before_motion` can reassert grip torque. Those paths need operator/protection
review **before** autonomous rehearsal or data collection. A small turn budget is not a fix.

## 3. Driver and control interfaces

`lerobot_robot_astra` is the local LeRobot hardware plugin name, not a requirement to use
the Astra model. Its `motor_id_offset` distinguishes address maps. `robot/arm.py` wraps the
plugin; `motions.py` exposes the higher-level callable interface. There is no separate
`robot/so101.py` dual-arm wrapper to invoke.

Important differences:

- `motions.connect()` is fake by default and explicitly selects position base control.
- `RealArm` retains a legacy speed-mode default; the current agent CLI does not expose the
  same base-mode selection. Do not infer a base fault from motor addresses.
- Connection is **not** a read-only operation: it can enable holding torque, configure
  motors, and clamp the tool. Disconnect also has physical consequences.
- Guards/pose math expect particular joint units. Verify the installed driver's normalization,
  calibration, and base mode; do not treat every `.pos` field as interchangeable degrees/ticks.
- One process must own each serial bus. A shared bus needs unique IDs and coordinated
  ownership; two independent controllers must not open the same port.

## 4. Host discovery is not arm qualification

This only lists host serial device names; it does not connect to the servos:

```bash
python3 - <<'PY'
import glob
ports = sorted(glob.glob('/dev/cu.usb*'))
print('\n'.join(ports) if ports else 'No matching USB serial devices')
PY
```

Check cables, power ratings, adapter, and wiring under the operator/manufacturer procedure.
Do not hot-plug servo wiring or power-cycle a loaded/unsupported arm based on a generic
software checklist. LEDs and port enumeration do not establish valid servo communication.

## 5. Qualification progression

1. Review connection/disconnection/clamp side effects and resolve the active thermal/config
   issue before opening a new controller session.
2. Verify current addresses, units, pose/calibration pairing, and allowed working ranges.
3. Establish a reviewed no-motion telemetry procedure; do not assume calling a library
   method named `connect()` is torque-neutral.
4. Qualify independent stop/holding behavior for faults, communication loss, and model waits.
5. Test a small approved motion/transition subset, one at a time with the workspace clear.
6. Qualify a single pluck and fretted note before phrase coordination or repeated trials.
7. Record profile/registry versions, preparation/settling limits, and bounded contact holds.

Do not blindly copy the repository calibration into the live cache, recalibrate the whole
rig as startup, run an unattended 54-target sweep, or use a large step-response probe.
Interpolation and “mm” depth values are pose-map estimates, not a contact-force measurement.

## 6. Scripts are maintenance tools, not startup tests

The ID, calibration, grip, pose-recording, and sweep scripts can have physical side effects.
Some retain historical port/base-mode defaults. Inspect their exact behavior and use them
only for an explicit operator-approved maintenance task. No script is invoked by this guide.

[SETUP.md](SETUP.md) owns software installation. [MOTIONS.md](MOTIONS.md) documents the
current callable interface. [STATUS.md](STATUS.md) records gaps; [PLANNING.md](PLANNING.md)
provides the proposed local scheduler/telemetry design. None overrides the operator rules.
