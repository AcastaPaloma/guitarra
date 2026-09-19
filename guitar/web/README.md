# Guitarra local operator console

A runnable web app for **real Baseten inference with fake tools only**. It reuses the
orchestration runner, existing `Motions`/`FakeArm` implementation, and synthetic pick fixture.
No camera, microphone, audio evaluator, serial port, or real-arm factory is invoked.

## Open / run

Default URL: **http://127.0.0.1:8787**

```bash
# From the repository root:
cd guitar
.venv/bin/python -m web --port 8787
```

It binds only to `127.0.0.1`, not the LAN. There is no `--host` or hardware flag.
Another service was already using 8765; the app uses 8787 and leaves that service alone.
Stop a foreground server with Ctrl-C. Stopping the server is not a hardware emergency stop.

The dashboard dependencies have been installed in the current `guitar/.venv`. For another
configured environment, add the CPU-only web dependencies without recreating the robot env:

```bash
.venv/bin/python -m pip install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' \
  'jsonschema>=4.23,<5' 'numpy>=1.26,<3'
```

The `web` optional dependency group is also declared in `guitar/pyproject.toml`.
No Node build or third-party frontend CDN is required.

## What you can control

- Choose any of the four workflow presets or create a custom string/fret sequence.
- Add an operator prompt. This is sent as user/task context, not as a replacement for the
  fixed safety/tool policy. The explicit note sequence remains the independent grading target.
- Set reasoning effort, tool-call budget, wall-time budget, and output-token cap.
- Start a billed Baseten run only after checking the per-run consent box.
- Watch tool calls/results, fake arm states, simulated plucks, usage, and independent checks.
- Pause, resume, or stop the current fake run.
- Browse prior CLI/web runs and download `events.jsonl`, `summary.json`, and `tools.json`.
- Read the tool contract and unresolved hardware-commissioning blockers.

There is one active run per server process. Requests share the existing six-second pacing
across web runs. Other clients sharing the Baseten account may still consume the quota;
provider errors remain incomplete runs, with no automatic replay/fallback.

### Pause / stop semantics

Controls are **cooperative**, not motor protection:

- Pause gates the next request and tool dispatch; it does not cancel an in-flight API call.
- Stop discards a response that returns after cancellation and prevents future tool dispatch.
- An already-running fake tool can complete. No automatic homing/release is injected to make
  an incomplete run look successful.
- The wall budget keeps running while paused; expiry stops further dispatch.
- An in-flight request may still consume credits. Closing the browser tab does not cancel
  a run; use Stop or let the bounded run finish.
- These controls must not be presented as a physical emergency stop or independent watchdog.

## Keys and local security

`BASETEN_API_KEY` and `BASETEN_MODEL` stay in the ignored server-side `.env` files.
The browser receives a key-present boolean, never the provider key. Restart the server after
changing credentials/model configuration. Do not paste credentials into prompts; the server
rejects prompts containing its configured Baseten key.

The server limits accepted Host/Origin values, requires an ephemeral session token plus JSON
for mutations, caps request size, rejects unknown configuration fields, and allowlists log
files beneath the run root. No generic file browser, shell executor, arbitrary model URL,
CORS wildcard, or hardware-unlock endpoint exists. Model output is rendered as text, not HTML.

This is a **single-user loopback app**, not a multi-user authenticated production deployment.
Do not expose it through a tunnel/proxy or add a LAN bind without a separate access-control review.

## Records

Web runs are written under:

```text
guitar/runs/orchestration/web/<UTC timestamp>-<scenario>-<suffix>/
  events.jsonl   # includes operator prompt, decisions, results, and final summary event
  summary.json  # grading, final state, budgets/usage, provider/model, and prompt
  tools.json    # exact model-callable tool schemas
```

The history also reads existing CLI batches under `guitar/runs/orchestration/`, including
nested demo folders. Reports survive server restarts. Traces without a summary are shown
as unmanaged/incomplete: they may have been interrupted or may still be running in another
CLI/server process. This app cannot control those other processes. A restarted server does
not resume a physical or fake run.

Prompts and observations are local run records and may be private, even though credentials
and private model reasoning are omitted. Logs are Git-ignored; share only intentionally.
The background server started during setup logs to `guitar/runs/web-server.log`, with its
PID recorded in `guitar/runs/web-server.pid`.

## Verification

- Full offline suite: **121 passed** (including local API/security/control checks).
- Desktop/mobile browser check: no JavaScript errors; no mobile horizontal overflow.
- One **real Baseten request sequence through the browser UI** passed. The custom prompt asked
  for a state query first; Kimi returned `where → ready → press → pluck → release → done`.
  The prompt was preserved in the run report and no hardware/media was used.
- Local evidence: `guitar/runs/web-ui-check.json`, `web-ui-desktop.png`, `web-ui-mobile.png`.
- That live run: `guitar/runs/orchestration/web/20260919T172414.172063Z-custom-149d42/`.

Offline checks use scripted models; the separately identified browser run used Baseten.
Neither result qualifies physical motion, acoustic quality, contact force, or safe holding time.

## Why real arms remain locked

The four passing workflow examples do not resolve the physical gates in
[AGENTS.md](../../AGENTS.md) and [STATUS.md](../STATUS.md):

1. The recorded gripper incident reached 75 C. The last operator-selected limit was **110**,
   while the code still defaults to **180**. Reconnect/reassertion and thermal/electrical
   protection behavior need deliberate review. Setting 110 alone is not thermal qualification.
2. Pick motion is still mocked; no calibrated physical picking map or coordinated schedule
   is proven by these workflows.
3. Real execution needs local stop/health monitoring, qualified small paths/profiles, bounded
   holding, and safe states during cloud waits. A browser Stop button cannot supply those.

The next physical milestone is a **separate operator-supervised commissioning session** after
those checks—not a toggle on this dashboard. Normal cleanup must keep the tool grippers
clamped, while genuine thermal/electrical protection must never be defeated to preserve a grip.

## Files

- `app.py`: local API, validation, consent/security boundary, and static assets.
- `manager.py`: one background fake run, live events, controls, and persisted history.
- `static/`: dependency-free browser UI.
- `../orchestration/control.py`: cooperative pause/stop gates reused by the runner.
- `../tests/test_web.py`: offline API/control/security checks.
