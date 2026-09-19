# Arm Controller

Minimal GUI to drive the arm and capture keyframes. Talks raw Feetech STS
protocol over the Waveshare bus servo adapter — no lerobot install needed.

**Single-arm rig (2026-09-19):** only the tapping/fretting arm (motor IDs
7–12) works; the old pluck arm is out of service and `pluck.py` is retired.
`fret.py` is the complete tool surface — it sounds notes by tapping the
pre-recorded keys in `keyframes_arm2.json`.

## Run

```bash
cd arm_controller
uv run --with pyserial python app.py        # GUI (defaults to the working arm)
uv run --with pyserial python fret.py --list          # show recorded keys
uv run --with pyserial python fret.py --tap 3 2       # tap string 3, fret 2
uv run --with pyserial python fret.py --seq 1,1 2,2   # tap a sequence
```

(or `pip install pyserial && python app.py`)

Close the GUI before running `fret.py` — the serial port is exclusive.

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
