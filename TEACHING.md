# Hand-guided action library

The installed runtime already records five joint coordinates and timestamps at
a target 30 Hz through its existing motor owner. No second serial process is
needed. The upstream [LeLamp control guide](https://github.com/humancomputerlab/LeLamp/blob/master/docs/5.%20LeLamp%20Control.md)
also documents recording and replay, but its standalone CLI must not be run
alongside this device's live runtime.

This is a teaching protocol, not a completed library. No hand-guided take has
been recorded in this continuation. Existing calibration stays unchanged.

## First takes

Teach small, comfortable movements first. Use the lamp's own left/right; record
that convention in each take. Start and finish discrete gestures at the same
agreed upright pose. For loops, demonstrate two cycles so a moving-to-moving
seam can be chosen from the middle instead of the hand placement at either end.

| Name | Demonstration | Intended use |
|---|---|---|
| `upright_neutral` | A comfortable upright stance, held briefly | Common reference pose |
| `look_left` / `look_right` | Turn attention each way, then return | Audience/partner cues |
| `nod_yes` | One gentle nod and return | Accent/acknowledgment |
| `head_tilt` | Curious side tilt and return | Expression |
| `body_sway` | Two flowing left/right cycles | Continuous dance loop |
| `body_bounce` | Two gentle rise/fall cycles | Beat accents |
| `body_roll` | Two coordinated body/head cycles | Groove variation |
| `dance_signature` | 8–12 seconds of a favorite whole-body groove | Main dance vocabulary |
| `ending_bow` | Controlled ending and return | Finish |

A dozen good takes can support many compositions. Every tempo/amplitude variant
still needs trajectory validation; multiplying amplitude is not automatically safe.

## Capture and replay handoff

1. Coordinate the sole operator, stop idle, inspect the camera, and support the
   head and arms before torque release. Never force powered joints.
2. Confirm release completed before hand guidance. The runtime recorder reads
   the actual five-joint pose while the operator guides it. Keep the raw take
   unchanged and use a unique name.
3. Save without automatically enabling torque or resuming idle. The runtime
   candidate adds `restore_torque: false` to `/api/recording/stop` and advertises
   `supports_save_without_torque_restore: true` in recording status. Verify this
   capability before starting; the old route silently ignores that option.
4. Keep supporting the mechanism after saving. Restoring powered holding is a
   separate supervised handoff; saving alone does not make it safe to let go.
5. Store robot/calibration identity, units, actual timestamps, label, direction
   convention, intended tempo, start/end poses, and whether a loop seam was
   verified. Do not infer timing from frame count alone.
6. Smooth/resample a copy, check ranges, derivative limits and collision geometry,
   and match position plus velocity/acceleration at joins. Compile the complete
   composition before uploading one SDK clip. Verify a short replay on camera.

The installed recorder's old Stop action enables torque and can resume idle.
The candidate fixes capture admission when torque release fails and adds the
explicit save-only option. These changes are tested in an isolated runtime
checkout, **not deployed**. They do not yet establish a physically verified
manual-to-powered handoff. No recording or torque release has been initiated.

Recorded motions solve authoring and direction mapping; they do not by themselves
solve loaded tracking error or make arbitrary clip joins continuous.
