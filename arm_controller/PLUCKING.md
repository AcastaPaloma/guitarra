# Plucking tools — design notes and the interference contract

`pluck.py` is the tool layer for the picking arm (IDs 5, 6, 1, 2, 7, 3 on
`/dev/cu.usbmodem5B8E1128501`). It is backend-agnostic: `TOOLS` holds the
function schemas and `dispatch()` is the single call entry point, so wiring it
to the Baseten-hosted model later is a thin loop — **no Baseten code lives here
yet, by design.**

## String convention

- **String 1 = RIGHTMOST string. String 6 = LEFTMOST string.** (Operator-defined,
  2026-09-19. This is the project-wide convention — do not flip it.)
- Each string has exactly two logged keyframes in `keyframes.json`:
  - `pose_<n>a` — stroke **start** (pick on the near side of string n)
  - `pose_<n>b` — stroke **end** (pick pushed through to the far side)
- The pluck IS the a→b sweep. It is driven mostly by wrist_flex (ID 2, ~+150
  counts), with small shoulder/elbow adjustments logged into the b pose.
- `neutral` is the rest pose, retracted clear of all strings.

## Note mapping (standard tuning)

| string (right→left) | open note | |
|---|---|---|
| 1 (rightmost) | **E4** | high E, thinnest |
| 2 | **B3** | |
| 3 | **G3** | |
| 4 | **D3** | |
| 5 | **A2** | |
| 6 (leftmost) | **E2** | low E, thickest |

The operator's right-to-left numbering coincides with universal guitar string
numbering (1 = high E … 6 = low E). **ASSUMPTION to verify by ear:** the
rightmost string really is the thin high E — i.e. the guitar isn't oriented
with the bass side toward the arm. If it's flipped, invert `STRING_NOTES` in
`pluck.py` (single table; nothing else changes). These are OPEN-string notes —
this arm doesn't fret, so pitch beyond the six open notes needs the fretting arm.

## ⚠ INTERFERENCE — integral to the project, read before touching paths

**The problem.** Only start/end poses are logged per string. A naive move from
one string's pose to another's travels *at string depth* and drags the pick
across every string in between — each crossing plays an unintended note. E.g.
going to string 5 by the direct joint-space path can sound string 4 on the way.

**The geometry (measured from the logged keyframes, 2026-09-19):**

| axis | role | evidence |
|---|---|---|
| elbow (ID 1) | **depth / clearance** | all string poses ≥ 2682; neutral retracted at 2474 |
| shoulder (ID 6) | string selection (lateral) | 1504 (string 5) … 1710 (string 1) |
| wrist_flex (ID 2) | the stroke | a→b is ~+150 counts on every string |
| base (ID 5), wrist_roll (ID 7) | near-constant | 1973–1983 / 1369–1381 |

**The rule.** Every transit follows **RETRACT → TRANSLATE → EXTEND**:

1. **RETRACT** — elbow to `SAFE_ELBOW = 2500`, pulling the pick off the string
   plane (≥ 180 counts of clearance from the nearest string pose).
2. **TRANSLATE** — move base/shoulder/wrists to the target string's start pose
   *while retracted*. Lateral motion here can never touch a string.
3. **EXTEND** — elbow back in to the start pose, slowly (`EXTEND_SPEED`), so
   arriving at the string plane doesn't itself make noise.

Then the stroke (a→b at `PLUCK_SPEED`) is the only string contact that ever
happens.

**Non-obvious case: re-plucking the same string.** After a stroke the pick is
on the far side (b). Sliding straight back to a re-crosses the string and
sounds it. Same-string repeats therefore run the full retract loop too.

**Why callers don't handle this.** The safety lives *inside* `pluck()`, so the
model backend can request any string in any order and never reason about
routing. Keep it that way: if paths ever need changing, change them in
`pluck.py` and update this file — never push routing responsibility up to the
model.

**Known future optimizations (deliberately not done yet):**
- Adjacent-string moves could use a shallower retract (faster), since required
  clearance shrinks with lateral distance. Needs per-pair clearance data.
- The retract after a stroke and the retract opening the next pluck are
  currently back-to-back moves; they merge trivially if latency matters.
- Strum = one lateral sweep at string depth on purpose; that's a new tool, not
  a relaxation of this rule.

## Timing knobs (tune BY EAR — audio feedback loop is the next step)

All in `pluck.py`: `TRANSIT_SPEED=500`, `EXTEND_SPEED=350` (slow approach =
quiet), `PLUCK_SPEED=2000` / `PLUCK_ACC=150` (fast stroke = clean attack),
`SETTLE_TOL=25`, `SETTLE_TIMEOUT=3.0`, gap between plucks defaults to 0.3 s.
Expected tweaks once we can hear output: PLUCK_SPEED per-string, shorter gaps,
maybe lighter extend on wound vs plain strings.

## Operational notes

- The serial port is exclusive: **close the arm-controller GUI before running
  pluck tools**, and vice versa.
- `PluckArm.close()` keeps torque ON by default so the arm doesn't collapse
  onto the guitar; pass `torque_off=True` only when the arm is supported.
- The gripper (ID 3) holds the pick. It is always commanded to its logged
  value and never opened by these tools (per `guitar/CONNECT.md` gripper rule).
- CLI smoke test: `uv run --with pyserial python pluck.py --list` (no motion),
  then `... pluck.py 1` with a hand near the arm.
