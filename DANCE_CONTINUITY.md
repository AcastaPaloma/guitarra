# Continuous dance: findings and candidate

> **Separate lamp workstream.** These continuity experiments and measurements are not
> guitar trajectory/latency evidence or a guitar implementation prerequisite. The current
> guitar design is [guitar/DESIGN.md](guitar/DESIGN.md); its status is
> [guitar/STATUS.md](guitar/STATUS.md). The original lamp findings remain below.

The post-restart stock idle was recorded for 82 seconds. All five encoders moved,
including a 28.304-unit elbow span. This contradicts treating the elbow as an
immobile/dead axis. It does not establish accurate target tracking, mechanical
health in every pose, or the safety of a different choreography. No new motion
was submitted by the agent during that observation.

## Research and implementation

[ROS joint-trajectory documentation](https://control.ros.org/kilted/doc/ros2_controllers/joint_trajectory_controller/doc/trajectory.html)
distinguishes continuous position from continuous velocity and acceleration.
Matching only pose endpoints does not ensure a flowing join. In our existing
authoring model, zero-derivative endpoints are smooth but can still make every
phrase come to rest. This is an authoring issue, separate from actuator lag.

[Ruckig's official tutorial](https://docs.ruckig.com/tutorial.html) supports offline
trajectory calculation with velocity, acceleration, and jerk constraints. Its
Community intermediate-waypoint path uses a cloud API; no such dependency was
introduced into this robot's control loop. The existing local analytic composer
already supplies bounded curves and compiles the entire clip before playback.

`primitives.py::continuous_dance` and `profiles/continuous.yaml` now define one
40-second five-axis carrier at 96 BPM. Phase continues across the internal
eight-beat markers. Only the beginning and ending fade to rest; no internal
phrase re-entry or whole-body hold is authored. Amplitudes remain within the
existing stage bounds. No calibration, tolerance, or dynamic limit was expanded.

`runner.py::build` emits one 1,201-frame clip, exact phrase markers, and a required
`held` SDK entry mode. `execute.py::load_scene` recomposes it and requires prior
physical stage verification. Execution also checks idle ownership and unchanged
stage alignment. This candidate is not deployed or physically verified.

The companion isolated runtime candidate adds opt-in `clip.play` entry mode
`held`. It reads the goal registers, actual positions, and torque state through
the existing bus owner, requires a stationary hold, preserves the retained first
target, and retains the two-second entry. The live measured baseline still
passes collision and velocity checks, but is not transmitted as a replacement
holding target. Changed goals, active idle, torque/readiness changes, tracking
error outside existing tolerances, and unsafe paths are rejected. Default SDK
entry behavior is unchanged. Hardware behavior of this candidate is unverified.

## Offline replay

```sh
python3 -m band.rehearsal.runner --preset continuous --stage evidence/commission-stage-2026-09-19.json --output /tmp/new-continuous-candidate
python3 -W error::ResourceWarning -m unittest discover -s tests -q
```

The stored device stage remains `hardware_verified: false`. Do not change this
flag, reset its baseline, switch probe kinds, or loosen the held-joint guard to
get around the earlier failed entry. A supported runtime deployment and bounded
physical verification must precede the requested larger, upright demonstration.

Current validation: 45 harness tests; 60 focused runtime/SDK/recording tests in
the isolated robot checkout. Tests cover authored continuity and failure paths;
they are not evidence of a successful physical dance.
