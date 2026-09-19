# Performance candidate changes

Current continuation: see [SDK_COMMISSIONING.md](SDK_COMMISSIONING.md) for deployed
SDK/idle repair, supervised physical results, recorder fixes, and 33 regression
checks. The initial implementation record below predates that continuation.

Implementation commit: `f4afc86` (local; not pushed).

- `band/performance/primitives.py`: versioned primitives, explicit joint masks,
  entry/exit offsets, and phase-offset five-axis waves for groove and solo support.
- `band/performance/composer.py`: one continuous authored scene, C3 fades/joins,
  analytic conservative derivative bounds, fixed planned baseline, strict
  envelope validation, and exact musical landmarks to CSV precision.
- `band/performance/profiles/*.yaml`: two provisional styles; physical stage
  identity and bounds are stored separately.
- `band/adapters/lamp/client.py`: authenticated SDK capability/session/resource
  calls, stale-observation rejection, durable idempotency checks, terminal action
  handling and confirmed cancellation without a torque-release fallback.
- `band/rehearsal/runner.py`: reproducible 40-second scene, fixed beat WAV,
  simulated guitar cues, hashes, and phase/support one-factor comparisons.
- `band/rehearsal/execute.py`: guarded supervised execution entry point,
  simulation/unverified-stage and changed-content rejection, event/telemetry logs and camera-liveness
  fault handling. Audio scheduling and exclusive ownership remain unavailable.
- `band/rehearsal/observe.py`: read-only camera/telemetry recording with separate
  timestamp domains and detection of the observed zero-frame failure.
- `tests/`: 23 software regression checks. No test is presented as hardware proof.

No lamp runtime source, calibration, gains, safety limits, or completion
tolerances were changed. New choreography has not been sent to the lamp.
See [visual evidence and outstanding physical work](VISUAL_FINDINGS.md) and
[exact rehearsal commands](REHEARSAL.md).


## SDK commissioning continuation

- `band/rehearsal/commission.py`: bounded one-axis/combined diagnostics, fixed
  baseline, idle-free preflight, SDK completion/cancel and camera watchdog.
- `band/rehearsal/recorded.py`: fresh-camera startup and joined recorder lifecycle.
- `band/rehearsal/observe.py`, `execute.py`: concurrent timestamp race correction;
  video live frame output and optional audio capture support (audio unverified).
- `tests/test_commission.py`, `test_recorded.py`, `test_observe.py`: regression
  coverage for actual diagnostic/capture faults. Total local suite: 33 passing.
- Runtime commit `2fb7457`: `set_idle` maps clear to `none` and waits for the real
  configuration result; five route regressions plus existing SDK tests pass.
- `SDK_COMMISSIONING.md` and `evidence/`: timestamped results and limitations;
  media stays local, the stage remains unverified, and no calibration/gains/
  completion limits were changed.
