# Lift-first tap paths and arm ownership

**Runtime code, offline-tested; NOT physical qualification.** Operator/gripper rules
in [../AGENTS.md](../AGENTS.md) retain priority. No hardware, microphone, camera, live
model call, or automated qualification sweep was used to implement this change.

## Why the neutral trips and string strikes were possible

The active app is **`arm_controller/webapp.py` on 8788**, not the older fake two-arm
console `guitar/web` on 8787. Editing the latter's Kimi prompt cannot change real taps.
The active `tap_key` previously always routed `rest → contact → rest`. `_move` sent
all five joint goals together. Calling that diagonal move a “lift” did not prevent
sideways travel before the fingertip cleared its current string. A per-row rest hub
has the same limitation: it is not a per-key lift point.

The current file has **25 contact keys** (rows 1–4 × six strings, plus `r5_1`), global
`rest`, and extra `neutral`. It has **zero per-key hovers** and no lift-first path
review. Its kinematic reference is absent. The old 54-target guitar map and backups
are **not** replacements for the repositioned rig. No poses/calibration were changed.

## Executable contract

`tap_paths.py` compiles a whole phrase before serial connection or browser capture:

```text
entry rest → reviewed hover route → hover A → tap A → hover A
                                                       │
                                await sampled encoder arrival
                                                       │
                              shortest reviewed hover route
                                                       ↓
                                                hover B → tap B → hover B
                                                                         │
                                               final reviewed exit → rest
```

- The initial state must already match recorded rest; there is no unknown-start homing.
- The current key's complete lift precedes transit. No direct contact→contact move.
- Lifts/descents preserve the contact's yaw/roll goals (IDs 7, 11). Only recorded poses
  are used—no copied “safe height”, IK, guessed clearance, or model joint offsets.
- Hover arrival uses the existing **30-count tolerance** plus **90ms of consecutive
  in-tolerance samples** before travel/descent. This is an encoder condition, **not**
  a string-contact detector or proof of clearance. The recorded approach/lift must
  itself be reviewed with this controller's actual joint motion.
- Travel uses Dijkstra over **directed reviewed hover edges**. Minimize the sum of
  absolute raw body-joint count changes; this is a travel proxy, not time, energy, mm,
  or acoustic quality. The global rest node is excluded between notes, even if it
  would be a cheaper route. Unknown edges cause rejection, not a neutral fallback.
- A repeated key reuses its hover but still taps and lifts again: this is a tap-only
  instrument, so “hold the fret and pluck again” is NOT applicable here.
- The complete phrase and an exit after every note must be reachable before execution.
  Failed lifts, drift, missing feedback, or timeouts latch a fault. No next note,
  automatic retry, or recovery park after uncertain motion.
- Normal final parking is a separate, reviewed exit after the phrase (or cooperative
  stop). It is never inserted between keys. An exit failure is a fault, not completion.
- Speeds/acceleration/contact dwell are unchanged. Grip/motor 12 is never commanded.
  Existing web clean-park/force-stop torque-hold and fault body-torque-off behavior
  remains; it is NOT independent thermal monitoring or a hardware E-stop.

The former `rest_hub`/`row_hub` values remain **readable in old reports** but are no
longer admitted by this real player. Contact-only extra/SNA playback and the old
row-hub sweep cannot bypass the gate. No automatic requalification or map restoration.

## What Kimi does—and what local code enforces

Kimi's arrangement request includes enabled arm/key ownership, reviewed transition
costs when available, and the priority **lift first → minimum reviewed travel → lower**.
It preserves musical event order and may prefer musically equivalent recorded keys.
It cannot output new coordinates, lower clearance, unlock profiles, or alter motor settings.
Native primary tap tools likewise require an explicit owner; global parking and
sustained holds are not on the model-callable allowlist. Those remain local/operator
operations. A secondary-arm request can never be silently dispatched to the primary bus.

The actual route is computed/enforced locally, not trusted to prompt compliance or
an audio assessment. `POST /api/trajectory` previews the same admission/route contract
without devices or inference. The UI shows named stages and arm assignments; Play
remains disabled until the complete route passes. The server independently rechecks
before reservation and execution. Cached legacy/stale tunings do not bypass admission.

**No audio model or fine-tuning is required for this path optimization.** Browser
recording/review remains a separate feature of the existing supervised take flow.

## Minimal operator follow-up: qualify a small subset, not a full-key sweep

Do not physically test until the applicable thermal/protection/support gates in
AGENTS.md are resolved. In particular, the reported 75°C incident is unresolved;
110 is the last operator-selected grip limit, not sustained thermal qualification.

For just a two-key phrase, the missing information is:

1. An actual lifted hover over each contact, recorded as `hover-r{fret}-c{string}`
   alongside the current `r{fret}_{string}` contacts. Keep the contact's recorded
   yaw/roll unchanged. Contact/hover encoder-arrival regions must not overlap;
   this software test alone does **not** certify a sufficient physical lift.
2. Operator review of each contact↔hover lift/descent, every intended directed
   hover→hover crossing, and entry/exit routes. Review the **entire tool/arm swept
   motion at the executable profile**, not just the endpoints or a slower hub walk.
3. A local review record under `qualified_profiles.lift_first` in
   `calibration_arm2.json`, bound to the exact map bytes, calibration digest, and
   motion contract. Do not mark paths reviewed merely because a test/model says so.

The following commands are **read-only; no device/model access**:

```bash
# Repository root. Prints a draft with EMPTY approved keys/edges/date.
guitar/.venv/bin/python arm_controller/fret.py --path-template

# Compile a two-key phrase. Currently refuses with the missing-hover/review reason.
guitar/.venv/bin/python arm_controller/fret.py --preview 1,1 1,2
```

The draft has `schema_version`, `keyframes_sha256`, `calibration_sha256`,
`motion_contract`, `qualified_at`, `keys`, and `transit_edges`. `keys` contains
`[string, fret]` pairs whose **both** lift and descent have been reviewed.
`transit_edges` contains directed named-node pairs such as
`["hover-r1-c1", "hover-r2-c1"]`. Entry/exit edges involve `rest`; an approval for
one direction does not automatically approve its reverse. Contact nodes are never
transit nodes. Do not add unused or untested edges. Any map, calibration, or motion
contract change invalidates the record. The browser and models cannot write it.

There is deliberately no automatic motion script that certifies these paths.
The existing calibration page can capture poses; its manual **Go** button is not
this path compiler and must not be used to drag between contact positions.

## Returning second arm: planned, not enabled

`tap_arms.py` defines two **tap** owners, not the historical fret/pick split:

| Owner | Key responsibility | Current state |
|---|---|---|
| `tap_primary` | Current recorded keys in rows 1–5; strings 1–6 | Existing body IDs 7–11; lift-first data still missing |
| `tap_secondary` | Planned rows **7–11**, strings **1–6 right-to-left** | No active key/hover registry or commissioned connection |

String 1 is high E/rightmost; 6 is low E/leftmost. Row 6 is not assigned.
Notes carry an `arm` field. Assignment validation rejects another arm's rows,
unrecorded keys, disabled arms, unknown owners, and silent reassignment. An older
single-arm note normalizes to `tap_primary`, never the returning arm.

The device-free assignment contract preserves note order and serializes both owners
on the shared guitar workspace. **No overlapping two-arm motion is authorized.**
An offline dual-owner fixture is not a live two-arm scheduler. Enabling the second
arm later still needs its own actual motor/port mapping, recorded contact/hover
poses, path review, stop/health handling, and executor. No old pluck-arm IDs or poses
are borrowed and no second device is connected by this change.
