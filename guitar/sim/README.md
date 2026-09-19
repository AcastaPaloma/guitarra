# Legacy guitar simulation — reference only

This directory preserves earlier MuJoCo guitar experiments. It is **not** a runtime,
training-data, or physical-validation dependency of the current guitar build. No simulated
band or simulator-first fine-tuning pipeline is planned.

Start at [the current design](../DESIGN.md), [status](../STATUS.md), and
[pretrained-model rehearsal](../REHEARSAL_LOOP.md). Offline fake-motion tests elsewhere in
the repo are software test doubles, not this physics/visualization environment.

## What these experiments represent

The simulator positions two modeled arms around a guitar. The guitar collision geometry
is visual-only; an analytic string model creates synthetic pitch/quality/audio from chosen
conditions. That is not a calibrated prediction of physical fret contact, buzz, force, or
servo latency.

- `build_scene.py`, `ik.py`, and `rig.py` provide the simulated scene/IK/movement interface.
- `string_model.py` produces synthetic sound and quality labels.
- `scorer.py` grades simulated event data, not real microphone measurements.
- `song.py` and `play.py` are legacy phrase examples, not the physical scheduler.
- `agent_loop.py` records attempts; it is not proof of a qualified real two-arm loop.
- `so101/` contains vendored robot assets with their own unchanged license/documentation.

The former README's reported clean-note scores and FFT results were synthetic experiment
results, not Baseten results or physical guitar validation. Do not transfer their thresholds,
pressure/depth values, or timing into the real controller. The simulator's interface and
string conventions are not assumed identical to the current physical API.

The old simulated playback did not enforce its intended note schedule end to end. That
is historical context, **not a task to add simulation before the real guitar can work**.
Use [PLANNING.md](../PLANNING.md) for current local scheduling and measured timing.

Original descriptions/results remain in Git history. No simulator, asset, or license code
is changed by the documentation consistency pass.
