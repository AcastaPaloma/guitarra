# Tapping/fretting — v4 recorded keys, lift-first execution

**Current working arm:** body IDs **7–11**, tool gripper **12 never commanded**.
The arm sounds notes by tapping; there is no separate functioning pick arm.
`pluck.py` is retired. The current web app is `webapp.py` on **8788**, not the older
fake `guitar/web` console on 8787. [PATHS.md](PATHS.md) owns the current path contract;
[AGENTS.md](../AGENTS.md) owns operator/gripper requirements.

## Current mapping

`keyframes_arm2.json` is the source of truth in **raw servo counts**, without
unit conversion or inferred IK positions. The rig was repositioned and re-recorded:

- Contact names: `r{fret}_{string}` or `pose-r{fret}-c{string}`.
- String **1 = high E/rightmost**, … **6 = low E/leftmost**.
- Current contacts: rows 1–4 across all six strings, plus `r5_1` (**25 keys**).
- `rest` is the recorded entry/final-park pose, not a between-note waypoint.
- Per-key clearance names: `hover-r{fret}-c{string}`. **None are recorded yet.**
- `neutral` and old `rest-r{row}` hubs do not establish per-key lift clearance.
- No current kinematic reference is present. Old XYZ estimates, the v2/v3 backups,
  and `guitar/robot/poses/fret_arm.json` cannot substitute for this map.

## Motion contract and current block

The former `rest → tap → rest` path could command sideways motion while the tip
was still near the strings. It has been retired, not merely discouraged in a prompt.

The new sequence is **current key → own hover → awaited arrival → shortest reviewed
hover route → destination hover → tap → own hover**. Lifts/descents retain the key's
yaw/roll goals. The whole phrase and its exits are admitted locally before connection.
Missing/stale hover pairs, unreviewed crossings, unknown starting state, drift or
failed arrival cannot cause automatic neutral fallback, replays or recovery moves.

This needs **actual recorded/reviewed paths**; endpoint coordinates and encoder
arrival are not proof of string clearance. Current playback is therefore blocked
until a small operator-reviewed subset exists. [PATHS.md](PATHS.md) describes that
process and its read-only preview/template commands. No full-key sweep is needed.
Existing speeds, acceleration and contact dwell are unchanged. No model can change
grip settings, calibration, motor targets, or clearance. Fine-tuning/audio is not a
prerequisite for this deterministic path improvement.

## Tools and cleanup

- `tap_key(string, fret)`: local reviewed approach, tap, own-hover lift. No neutral.
- `tap_sequence(keys, gap_s)`: validates the whole phrase before its first tap.
- `hold_fret`: local/operator-only quiet hold via a reviewed hover; not model-callable.
- `release_fret`: lift to that key's own hover; **never opens the gripper**.
- `rest()` / CLI `--rest`: local/operator-only reviewed final exit. Global parking is
  no longer in the model's tool allowlist; it cannot request neutral between notes.
- Every model-callable tool requires `arm: "tap_primary"`; unknown fields, another
  owner, or primary tasks outside its rows are refused instead of silently rerouted.
- `get_fret_position` / `estimate_position`: read-only views. Estimates are not targets.
- Contact-only extra/SNA poses and the old row-hub qualification sweep cannot bypass
  the new path contract; they remain blocked.

Web completion/cooperative stop follows a reviewed final exit and holds body torque
at rest, as in the pulled player. Faults add no recovery move and release body torque;
force stop holds frozen goals. A failed exit is a fault, not successful completion.
These controls are **not** a hardware E-stop or an independent thermal monitor.

**Gripper 12 is never commanded—not position or torque.** The last operator-selected
limit is **110**, after a reported **75°C** event. Neither 110 nor a short temperature
check establishes sustained qualification. Never restore the legacy 180 default,
raise torque to fix contact, or defeat thermal protection. Support the body/tool as
required by AGENTS.md; no unattended rehearsal or physical qualification sweep.

## Pending second tap arm

The operator's returning arm owns **rows 7–11**, strings **1–6 right-to-left**.
`tap_arms.py` and the symbolic note schema distinguish `tap_primary` and
`tap_secondary`. The second remains unavailable until its own recorded keys/hover
paths, physical mapping and execution are commissioned. No old pick-arm IDs or
poses are reused. Models cannot assign keys to the wrong owner or authorize
simultaneous motion; the shared-guitar ownership contract is sequential initially.
