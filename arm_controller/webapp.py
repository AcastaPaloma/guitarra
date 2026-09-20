"""Single-arm tap console: plan -> supervised play/record -> review -> approve.

Loopback only. Startup/page loads open no devices and make no model requests.
Play requires an already-running browser microphone and per-take consent. No
camera, pluck arm, unrestricted model paths, or automatic physical repetitions.

Run from the repository root:
  guitar/.venv/bin/python arm_controller/webapp.py --port 8788
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "guitar"))

import calibration
import fret
from model.audio import AUDIO_MODELS, DEFAULT_AUDIO_MODEL
from model.baseten import DEFAULT_MODEL, BasetenError, load_env
from rehearsal import (
    MAX_WAV_BYTES,
    CaptureComplete,
    CaptureStart,
    PartialCapture,
    RehearsalError,
    RehearsalManager,
)
from tap_plans import (
    MAX_ATTEMPTS,
    MAX_CAPTURE_SECONDS,
    MAX_NOTES,
    MAX_PLAY_SECONDS,
    MAX_TAKE_NOTES,
    Consent,
    StrictModel,
    TapPlan,
    arrange,
    key_context,
)

SESSION_TOKEN = secrets.token_urlsafe(32)
STATIC = HERE / "static"
RUN_ROOT = HERE.parent / "guitar" / "runs" / "tap_rehearsal"
_plan_lock = threading.Lock()


def read_registry():
    """Read a current local snapshot; no old-map fallback, guessed poses, or device I/O."""
    try:
        raw = fret.KEYFRAMES_PATH.read_bytes()
        calibration_bytes = (HERE / "calibration_arm2.json").read_bytes()
        entries = json.loads(raw)
        # Reject coercion/incomplete poses BEFORE the historical loader converts counts.
        if not isinstance(entries, list):
            raise TypeError("Keypoints must be a list")
        for entry in entries:
            positions = entry["positions"]
            if (set(positions) != {str(s) for s in fret.MOTOR_IDS}
                    or any(type(v) is not int or not 0 <= v <= 4095 for v in positions.values())):
                raise ValueError("Keypoints must contain complete raw body-joint poses only")
        snapshot = fret.load_map(entries=entries)
        cells, rest, warnings = snapshot["cells"], snapshot["rest"], snapshot["warns"]
        grid = (cells, rest, warnings)
        if not cells or set(rest) != set(fret.MOTOR_IDS):
            raise ValueError("Record a rest pose and the needed keys first")
        # row_hub is executable only when the OPERATOR qualified it against these
        # exact keyframe bytes (fret.py --qualify-row-hubs) and every recorded
        # row still has its hub. Any keypoint edit invalidates it automatically.
        row_rests = snapshot["row_rests"]
        profiles = ["rest_hub"]
        row_hub = json.loads(calibration_bytes).get("qualified_profiles", {}).get("row_hub", {})
        if (isinstance(row_hub, dict)
                and row_hub.get("keyframes_sha256") == hashlib.sha256(raw).hexdigest()
                and row_rests and {f for _, f in cells} <= set(row_rests)):
            profiles.append("row_hub")
        signature = (b"rest_hub-v2:400:1200:0.12:30:90:4.0:profiles="
                     + ",".join(sorted(profiles)).encode())
        fingerprint = hashlib.sha256(raw + b"\0" + calibration_bytes + signature).hexdigest()
        return {"keys": set(cells), "grid": grid, "row_rests": row_rests,
                "path_profiles": tuple(profiles), "fingerprint": fingerprint,
                "warnings": warnings}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise RehearsalError("No valid current keypoint grid/rest pose. Calibrate first; "
                             "the backup/old fret map is not used automatically.") from None


# Force stop: the executor publishes its halt event here so /api/force-stop can
# freeze motion mid-stage. Only ever holds the CURRENT take's event, under lock.
_halt_lock = threading.Lock()
_active_halt = {"event": None}


def execute_take(plan, registry, stop_event, emit):
    """Local execution only. No cloud call, arbitrary path, or model timing in the servo loop."""
    if stop_event.is_set():
        return False
    if read_registry()["fingerprint"] != registry["fingerprint"]:
        raise RehearsalError("Calibration changed before connection")
    if plan.path_profile not in registry.get("path_profiles", ("rest_hub",)):
        raise RehearsalError("Plan's path profile is no longer qualified on this rig")
    deadline = time.monotonic() + MAX_PLAY_SECONDS
    halt = threading.Event()
    arm = fret.FretArm(grid=registry["grid"],
                       row_rests=registry["row_rests"] if plan.path_profile == "row_hub" else None,
                       path_profile=plan.path_profile, halt=halt)
    with _halt_lock:
        _active_halt["event"] = halt

    def run_notes():
        # Every exit from this loop leaves the arm settled at a staging hub.
        for index, note in enumerate(plan.notes):
            if stop_event.is_set():
                return False
            emit({"event": "note_start", "index": index, "string": note.string, "fret": note.fret})
            result = arm.tap_key(note.string, note.fret, deadline=deadline)
            emit({"event": "note_end", "index": index, "result": result})
            if index < len(plan.notes) - 1 and stop_event.wait(note.pause_ms / 1000):
                return False
        return not stop_event.is_set()

    clean = False
    try:
        completed = run_notes()
        clean = True
        return completed
    finally:
        with _halt_lock:
            _active_halt["event"] = None
        # Completed/stopped takes end settled at a hub (with row_hub that hub is
        # OVER the guitar), so PARK at the recorded global rest before releasing
        # torque — never drop the arm onto the strings. On a FAULT: no recovery
        # motion and body torque off (a stalled servo must not keep driving into
        # whatever blocked it) — the operator supports the body, as before. On a
        # FORCE STOP: goals were frozen at present positions, so torque is held
        # and the arm stays put; recover via /calibrate or the GUI. Motor 12 is
        # never touched either way.
        if clean and not halt.is_set():
            try:
                arm.rest()
            except Exception:  # noqa: BLE001 - failed park = uncertain state: release, no retry
                pass
        arm.close(torque_off=not halt.is_set())


manager = RehearsalManager(RUN_ROOT, registry=read_registry, execute=execute_take,
                           lock=calibration.ownership_lock,
                           calibration_active=calibration.session_active)
calibration.set_play_guard(lambda: manager.busy)

app = FastAPI(docs_url=None, redoc_url=None)
app.include_router(calibration.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    """Single-user loopback boundary, including calibration and binary WAV mutations."""
    try:
        host = urlsplit("http://" + request.headers.get("host", ""))
        valid_host = (host.hostname in {"127.0.0.1", "localhost"}
                      and not (host.username or host.password or host.path or host.query or host.fragment)
                      and (host.port is None or 1 <= host.port <= 65535))
    except ValueError:
        valid_host = False
    if not valid_host:
        return JSONResponse({"detail": "Loopback Host required"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        return JSONResponse({"detail": "Same-origin requests only"}, status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        token = request.headers.get("x-session-token", "")
        if not token.isascii() or not secrets.compare_digest(token, SESSION_TOKEN):
            return JSONResponse({"detail": "Reload this local console for its session token"}, status_code=403)
        is_audio = request.url.path.endswith(("/audio", "/partial-audio"))
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type != ("audio/wav" if is_audio else "application/json"):
            return JSONResponse({"detail": "Expected WAV audio or JSON mutation"}, status_code=415)
        limit = MAX_WAV_BYTES if is_audio else 65536
        try:
            length = int(request.headers.get("content-length", "0"))
            if length < 0:
                raise ValueError("Negative length")
            if length > limit:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        # Bound chunked requests as well as Content-Length. Starlette caches this
        # body for the downstream parser; it is never logged or put in model text.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
            body.extend(chunk)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; media-src 'self' blob:; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    return response


@app.exception_handler(RehearsalError)
async def admission_error(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


class PlanReq(StrictModel):
    prompt: str = Field(min_length=1, max_length=8000)
    allow_inference: Consent


class PrepareReq(StrictModel):
    plan: TapPlan
    parent_attempt_id: str | None = Field(default=None, min_length=36, max_length=36)
    source_attempt_id: str | None = Field(default=None, min_length=36, max_length=36)
    session_id: str | None = Field(default=None, min_length=36, max_length=36)
    title: str = Field(default="Rehearsal", min_length=1, max_length=80)
    allow_audio_upload: Consent
    allow_revision_inference: Consent
    supervised_and_supported: Consent


class PlayReq(CaptureStart):
    attempt_id: str = Field(min_length=36, max_length=36)


class AttemptReq(StrictModel):
    attempt_id: str = Field(min_length=36, max_length=36)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/calibrate")
def calibrate_page():
    return HTMLResponse(calibration.PAGE)


@app.get("/api/bootstrap")
def bootstrap():
    try:
        registry = read_registry()
        keys, warning = key_context(registry["keys"]), None
    except RehearsalError as exc:
        registry, keys, warning = None, [], str(exc)
    profiles = list(registry.get("path_profiles", ("rest_hub",))) if registry else ["rest_hub"]
    audio_model = os.environ.get("BASETEN_AUDIO_MODEL") or DEFAULT_AUDIO_MODEL
    return {"session_token": SESSION_TOKEN, "keys": keys, "warning": warning,
            "keypoint_warnings": registry["warnings"] if registry else [],
            "max_notes": MAX_NOTES, "max_take_notes": MAX_TAKE_NOTES, "max_attempts": MAX_ATTEMPTS,
            "max_capture_seconds": MAX_CAPTURE_SECONDS, "hardware": "real_single_tap_arm",
            "camera": False, "plucking": False, "auto_replay": False,
            "path_profiles": profiles, "shortcuts_qualified": "row_hub" in profiles,
            "key_present": bool(os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")),
            "planner_model": os.environ.get("BASETEN_MODEL") or DEFAULT_MODEL,
            "audio_model": audio_model, "audio_model_supported": audio_model in AUDIO_MODELS,
            "audio_endpoint_status": "unverified; last recorded live probe timed out",
            "active_attempt": manager.active()}


@app.post("/api/plan")
def plan(req: PlanReq):
    registry = read_registry()
    if manager.busy:
        raise RehearsalError("Finish the current take before requesting another arrangement")
    for name in ("BASETEN_API_KEY", "BASETEN"):
        secret = os.environ.get(name)
        if secret and secret in req.prompt:
            raise HTTPException(400, "Do not include credentials in prompts")
    if not _plan_lock.acquire(blocking=False):
        raise RehearsalError("An arrangement request is already pending; no duplicate inference")
    try:
        return arrange(req.prompt, registry["keys"])
    except (BasetenError, ValueError):
        raise HTTPException(502, "Baseten planning unavailable or invalid response; no automatic retry") from None
    finally:
        _plan_lock.release()


@app.post("/api/attempts")
def prepare(req: PrepareReq):
    if not (os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")):
        raise RehearsalError("Configure the server-side Baseten credential before a recorded take")
    if (os.environ.get("BASETEN_AUDIO_MODEL") or DEFAULT_AUDIO_MODEL) not in AUDIO_MODELS:
        raise RehearsalError("Select a supported audio evaluator; the Kimi planner cannot receive this WAV")
    return manager.create(req.plan, parent_attempt_id=req.parent_attempt_id,
                          source_attempt_id=req.source_attempt_id, session_id=req.session_id, title=req.title)


@app.post("/api/play")
def play(req: PlayReq):
    capture = CaptureStart.model_validate(req.model_dump(exclude={"attempt_id"}))
    return manager.start(req.attempt_id, capture)


@app.post("/api/stop")
def stop(req: AttemptReq):
    return manager.stop(req.attempt_id)


class ForceStopReq(StrictModel):
    pass  # explicit empty JSON body; the loopback middleware requires JSON


@app.post("/api/force-stop")
def force_stop(_req: ForceStopReq):
    """Freeze the arm mid-motion NOW: every servo's goal is overwritten with its
    present position and torque stays ON so the arm holds instead of dropping.
    NOT a hardware E-stop (commands ride the same serial link — if the link is
    wedged, cut servo power physically). The take ends as a fault/stop; recover
    by moving to rest from /calibrate or the keyframe GUI."""
    with _halt_lock:
        halt = _active_halt["event"]
    if halt is None:
        raise RehearsalError("No take is executing right now; nothing to freeze")
    halt.set()
    active = manager.active()
    if active and active.get("attempt_id"):
        try:
            manager.stop(active["attempt_id"], reason="Force stop: arm frozen mid-path, torque held")
        except RehearsalError:
            pass  # the executor is already unwinding via Halted
    return {"force_stop": True, "torque": "held",
            "recovery": "arm frozen mid-path — move it to rest from /calibrate or the GUI"}


@app.get("/api/status")
def status():
    return {"active_attempt": manager.active()}


@app.get("/api/attempts/{attempt_id}")
def attempt_status(attempt_id: str):
    return manager.status(attempt_id)


@app.post("/api/attempts/{attempt_id}/heartbeat")
def heartbeat(attempt_id: str):
    return manager.heartbeat(attempt_id)


@app.post("/api/attempts/{attempt_id}/partial-audio")
async def partial_audio(attempt_id: str, request: Request):
    header = request.headers.get("x-capture-metadata", "")
    if len(header) > 2048:
        raise HTTPException(400, "Capture metadata too large")
    try:
        metadata = PartialCapture.model_validate_json(header, strict=True)
    except ValidationError:
        raise HTTPException(400, "Partial capture metadata is required") from None
    return await run_in_threadpool(manager.save_partial, attempt_id, metadata, await request.body())


@app.get("/api/sessions")
def sessions():
    return {"sessions": manager.sessions()}


@app.get("/api/sessions/{session_id}")
def session_history(session_id: str):
    return manager.history(session_id)


@app.post("/api/sessions/{session_id}/preferred")
def prefer_take(session_id: str, req: AttemptReq):
    return manager.prefer(session_id, req.attempt_id)


@app.get("/api/attempts/{attempt_id}/audio")
def saved_audio(attempt_id: str, request: Request):
    # The UI fetches with its token and creates a local blob URL. Do not expose
    # private clips as embeddable unauthenticated cross-origin media URLs.
    token = request.headers.get("x-session-token", "")
    if not token.isascii() or not secrets.compare_digest(token, SESSION_TOKEN):
        raise HTTPException(403, "This local session's token is required to read recordings")
    return FileResponse(manager.saved_audio(attempt_id), media_type="audio/wav",
                        filename=f"take-{attempt_id}.wav")


@app.post("/api/attempts/{attempt_id}/audio")
async def upload_audio(attempt_id: str, request: Request):
    header = request.headers.get("x-capture-metadata", "")
    if len(header) > 2048:
        raise HTTPException(400, "Capture metadata too large")
    try:
        metadata = CaptureComplete.model_validate_json(header, strict=True)
    except ValidationError:
        raise HTTPException(400, "Complete, uninterrupted capture metadata is required") from None
    body = await request.body()  # middleware enforces an actual streamed byte limit
    return await run_in_threadpool(manager.accept_audio, attempt_id, metadata, body)


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8788)
    args = ap.parse_args()
    load_env()
    print(f"Guitarra tap/rehearsal console: http://127.0.0.1:{args.port} — REAL ARM, supervised only", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
