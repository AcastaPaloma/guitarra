# Arm Controller

Minimal GUI to drive the arm and capture keyframes. Talks raw Feetech STS
protocol over the Waveshare bus servo adapter — no lerobot install needed.

**Single-arm rig (2026-09-19):** only the tapping/fretting arm (motor IDs
7–12) works; the old pluck arm is out of service and `pluck.py` is retired.
`fret.py` is the complete tool surface — it sounds notes by tapping the
pre-recorded keys in `keyframes_arm2.json`. The returning second **tap** arm is
planned for rows **7–11**, strings **1–6 right-to-left**; it is not enabled.

**Current motion requirement:** [PATHS.md](PATHS.md) documents enforced lift-first
routing with no global-neutral detour between notes. Contact-only rest/row-hub taps
are now refused. The current map has 25 contacts but no per-key hovers/review, so
Play is blocked until an operator-qualified small path subset exists.

Baseline pose, measured geometry, world frame, and the keypoint XYZ layer
are documented in **[CALIBRATION.md](CALIBRATION.md)**.

## Run

```bash
cd arm_controller
uv run --with pyserial python app.py        # GUI (defaults to the working arm)
uv run --with pyserial python fret.py --list          # show recorded keys
uv run --with pyserial python fret.py --preview 1,1 1,2  # NO motion, check the whole route
uv run --with pyserial python fret.py --path-template   # UNQUALIFIED review draft only
# --tap/--seq require reviewed contact/hover paths and separate physical approval.
```

(or `pip install pyserial && python app.py`)

Close the GUI before running `fret.py` — the serial port is exclusive.

### Web console: planning, recording, and reviewed rehearsal

```bash
# From the REPOSITORY ROOT, with the existing web/audio environment:
guitar/.venv/bin/python arm_controller/webapp.py --port 8788
# Console: http://127.0.0.1:8788
# Calibration: http://127.0.0.1:8788/calibrate
```

**[REHEARSAL.md](REHEARSAL.md)** documents Play + Listen: a consented browser
microphone records one short supervised take, the separate Baseten audio model
reviews it, and the planner proposes locally bounded changes for explicit approval.
The main UI stays compact; a separate **Progress** tab retains per-take audio,
reviews, cached tuning versions, and your preferred take across sessions/restarts.
Play Next Take continues from a staged revision or a saved performed tuning without
rebuilding the song; previous outcomes reach the planner as bounded context.
No automatic physical replay, camera, raw-joint model paths, or gripper commands.
The current web player parks through a reviewed final exit and holds body torque on
clean completion; faults release body torque without recovery moves, and force stop
holds frozen goals. Support the body; no independent thermal monitor is supplied.
Runtime dependencies include jsonschema, NumPy, and SciPy as well as FastAPI,
Uvicorn, pyserial, and the existing Python/Tk support.

**Current blockers:** v4 contacts are present, but per-key hover poses and reviewed
lift/translate/lower paths are missing. No backup, arbitrary offset or old kinematic
map is substituted. Inkling live audio quality/ingestion and physical/thermal
qualification remain separate; see [status](../guitar/STATUS.md). Offline tests
qualify neither the endpoint nor physical motion. The old fake console on 8787
is a different app.

### Web calibration (preferred over the GUI)

CONNECT → torque OFF → pose by hand → CAPTURE. Once the kinematic reference
pose is captured (see `kinematics.py` for the measured geometry), every
keypoint stores raw servo counts **plus** per-joint degrees and the
fingertip's world XYZ in cm, so later planners can reason spatially about
positions instead of only in servo counts. The reference lives in
`calibration_arm2.json`; keypoints in `keyframes_arm2.json` (schema is
backward compatible — `fret.py` plays the raw counts and ignores the rest).

## Hardware assumptions

- Port `/dev/cu.wchusbserial5B8E1128501` at 1,000,000 baud (re-enumerates on
  replug — check `ls /dev/cu.*`; edit `PORT` in `app.py` / `FRET_PORT` in `fret.py`)
- Motor IDs bottom → top: **7, 8, 9, 10, 11** (+ gripper **12**, which
  permanently holds the fingertip tool and is **never commanded**)

## Usage

- Torque starts **OFF**: pose the arm by hand, then press **★ Keyframe current pose**
  to save the position of all five joints to `keyframes_arm2.json`.
- **Torque ON** enables the sliders for direct joint control and **Go to** for
  replaying a saved keyframe (moves at a conservative speed).
- Closing the window disables torque — support the arm so it doesn't fall.
