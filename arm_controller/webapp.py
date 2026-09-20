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

import arm1
import calibration
import fret
import songsterr
from tap_arms import (PRIMARY, SECONDARY, assign, capabilities as arm_capabilities,
                      enabled_key_map, owner_of_row)
from tap_paths import PROFILE, ClearancePaths, PathUnavailable, motion_contract
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
    NOTE_PACE_S,
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


def _read_secondary_registry():
    """Arm-1 (upper rows 7-11) snapshot. Missing/invalid data makes the secondary
    UNAVAILABLE with an exact reason; it never blocks the primary registry.

    -> (secondary dict, keyframes bytes, calibration bytes) — the bytes feed the
    capability fingerprint so any arm-1 change invalidates reservations too.
    """
    secondary = {"keys": set(), "grid": None, "hovers": {}, "paths": None,
                 "warnings": [], "available": False, "path_blocker": None}
    try:
        raw = (HERE / "keyframes_arm1.json").read_bytes()
    except OSError:
        secondary["path_blocker"] = ("no secondary keyframes: keyframes_arm1.json is missing "
                                     "(record arm-1 contact keys first)")
        return secondary, b"", b""
    try:
        calibration_bytes = (HERE / "calibration_arm1.json").read_bytes()
    except OSError:
        calibration_bytes = b""
    try:
        entries = json.loads(raw)
        # Same strictness as the primary map: reject coercion/incomplete poses
        # BEFORE the loader converts counts. Recorded grip 3 may be present in
        # the file but is filtered out of every motion pose.
        if not isinstance(entries, list):
            raise TypeError("Arm-1 keypoints must be a list")
        for entry in entries:
            positions = entry["positions"]
            if (not {str(s) for s in arm1.BODY_IDS} <= set(positions)
                    or any(type(v) is not int or not 0 <= v <= 4095 for v in positions.values())):
                raise ValueError("Arm-1 keypoints must contain complete raw integer poses")
        snapshot = arm1.load_map(entries=entries)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        secondary["path_blocker"] = f"invalid keyframes_arm1.json; secondary disabled ({exc})"
        return secondary, raw, calibration_bytes
    secondary.update(keys=set(snapshot["cells"]),
                     grid=(snapshot["cells"], snapshot["rest"], snapshot["warns"]),
                     hovers=snapshot["hovers"], warnings=snapshot["warns"])
    if not snapshot["cells"]:
        secondary["path_blocker"] = "no contact keys recorded in keyframes_arm1.json"
    elif not snapshot["hovers"]:
        secondary["path_blocker"] = ("no hover poses recorded: record a hover-r{fret}-c{string} "
                                     "lift pose beside each arm-1 contact, then review its paths")
    elif not calibration_bytes:
        secondary["path_blocker"] = ("paths not compiled: calibration_arm1.json is missing; record "
                                     "the operator lift-first path review there (arm1.py --path-template)")
    else:
        try:
            secondary["paths"] = ClearancePaths.from_snapshot(
                snapshot, hashlib.sha256(raw).hexdigest(), json.loads(calibration_bytes),
                body_ids=tuple(arm1.BODY_IDS), fret_rows=arm1.FRET_ROWS)
        except (PathUnavailable, ValueError, TypeError) as exc:
            secondary["path_blocker"] = f"paths not compiled: {exc}"
    secondary["available"] = bool(secondary["keys"]) and secondary["paths"] is not None
    return secondary, raw, calibration_bytes


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
        # Contacts alone (or a global/per-row hub) cannot enforce lift-first.
        # Keep them available for note planning, but NEVER silently execute the
        # old press -> rest -> press route when hover/review data is absent.
        paths, blocker = None, None
        try:
            paths = ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(),
                                                 json.loads(calibration_bytes))
        except PathUnavailable as exc:
            blocker = str(exc)
        secondary, secondary_raw, secondary_calibration = _read_secondary_registry()
        capabilities = arm_capabilities(set(cells), primary_ready=paths is not None,
                                        secondary_keys=secondary["keys"],
                                        secondary_ready=secondary["paths"] is not None,
                                        secondary_blocker=secondary["path_blocker"])
        owners = json.dumps(capabilities, sort_keys=True).encode()
        fingerprint = hashlib.sha256(
            raw + b"\0" + calibration_bytes + motion_contract().encode()
            + b"\0" + secondary_raw + b"\0" + secondary_calibration
            + motion_contract(tuple(arm1.BODY_IDS)).encode() + owners).hexdigest()
        return {"keys": set(cells), "grid": grid, "row_rests": snapshot["row_rests"],
                "hovers": snapshot["hovers"], "paths": paths, "path_blocker": blocker,
                "path_profiles": (PROFILE,) if paths else (), "fingerprint": fingerprint,
                "warnings": warnings, "secondary": secondary, "capabilities": capabilities}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise RehearsalError("No valid current keypoint grid/rest pose. Calibrate first; "
                             "the backup/old fret map is not used automatically.") from None


def _arm_paths(registry, arm_id):
    """The reviewed ClearancePaths for one arm, or its exact blocker."""
    if arm_id == PRIMARY:
        paths, blocker = registry.get("paths"), registry.get("path_blocker")
    else:
        secondary = registry.get("secondary") or {}
        paths, blocker = secondary.get("paths"), secondary.get("path_blocker")
    if paths is None:
        raise PathUnavailable(blocker or f"No reviewed lift-first paths for {arm_id}")
    return paths


def admit_motion(plan, registry):
    """Whole-phrase path/arm admission BEFORE reserving a take or opening a port.

    Each arm's key subsequence is compiled against ITS OWN reviewed registry
    (execution is strictly sequential; the idle arm holds its own hover/rest,
    so an arm's motion is exactly its subsequence of notes)."""
    try:
        assignments = assign(plan.notes, enabled_key_map(registry))
        if plan.path_profile != PROFILE:
            raise PathUnavailable("Hub-only playback is retired: rebuild with lift_first; "
                                  "rest/row hubs do not guarantee lift before sideways motion")
        arm_order = []
        for assignment in assignments:
            if assignment["arm"] not in arm_order:
                arm_order.append(assignment["arm"])
        per_arm = {}
        for arm_id in arm_order or [PRIMARY]:
            paths = _arm_paths(registry, arm_id)
            keys = [(n.string, n.fret) for n, a in zip(plan.notes, assignments)
                    if a["arm"] == arm_id]
            per_arm[arm_id] = paths.compile(keys)
        if arm_order == [PRIMARY]:
            compiled = per_arm[PRIMARY]  # unchanged single-arm trajectory shape
        else:
            cursors = {arm_id: iter(trace["notes"]) for arm_id, trace in per_arm.items()}
            notes = [{**next(cursors[a["arm"]]), "index": index, "arm": a["arm"]}
                     for index, a in enumerate(assignments)]
            compiled = {
                "path_profile": PROFILE, "notes": notes,
                "exit_routes": {arm_id: trace["exit_route"] for arm_id, trace in per_arm.items()},
                "neutral_visits_between_notes": 0,
                "joint_travel_proxy_counts": sum(t["joint_travel_proxy_counts"]
                                                 for t in per_arm.values()),
                "objective": per_arm[arm_order[0]]["objective"],
                "coordination": "strictly sequential; one arm moves at a time, the idle "
                                "arm holds its own hover/rest",
                "physical_clearance_verified_by_software": False,
                "cost_is_not_time_or_acoustic_quality": True}
        compiled["assignments"] = assignments
        return compiled
    except ValueError as exc:
        raise RehearsalError(str(exc)) from None


# Force stop: the executor publishes its halt event here so /api/force-stop can
# freeze motion mid-stage. Only ever holds the CURRENT take's event, under lock.
_halt_lock = threading.Lock()
_active_halt = {"event": None}


def execute_take(plan, registry, stop_event, emit):
    """Local execution only. No cloud call, arbitrary path, or model timing in the servo loop.

    Two-arm takes are STRICTLY SEQUENTIAL: one arm moves at a time while the
    idle arm holds its own hover/rest. Each note's arm comes from the plan's
    validated assignments (tap_plans/tap_arms.assign), never guessed. A single
    shared halt event freezes BOTH arms on force stop.
    """
    if stop_event.is_set():
        return False
    if read_registry()["fingerprint"] != registry["fingerprint"]:
        raise RehearsalError("Calibration changed before connection")
    compiled = admit_motion(plan, registry)
    if stop_event.is_set():
        return False
    emit({"event": "trajectory_admitted", "trajectory": compiled})
    deadline = time.monotonic() + MAX_PLAY_SECONDS
    halt = threading.Event()
    note_arms = [assignment["arm"] for assignment in compiled["assignments"]]
    arms = {}

    def run_notes():
        # Each successful tap finishes at that key's OWN hover. A fault can
        # leave state uncertain; no cleanup route is then attempted.
        for index, note in enumerate(plan.notes):
            if stop_event.is_set():
                return False
            emit({"event": "note_start", "index": index, "arm": note_arms[index],
                  "string": note.string, "fret": note.fret, "shared_workspace": "guitar"})
            result = arms[note_arms[index]].tap_key(note.string, note.fret, deadline=deadline)
            emit({"event": "note_end", "index": index, "arm": note_arms[index], "result": result})
            if index < len(plan.notes) - 1 and stop_event.wait(note.pause_ms / 1000):
                return False
        return not stop_event.is_set()

    clean = False
    with _halt_lock:
        _active_halt["event"] = halt
    try:
        # Open ONLY the arms this plan's assignments name; both share one halt.
        # Opening writes hold-in-place goals at each arm's verified rest — no travel.
        if PRIMARY in note_arms:
            arms[PRIMARY] = fret.FretArm(grid=registry["grid"], paths=registry["paths"],
                                         path_profile=plan.path_profile, halt=halt)
        if SECONDARY in note_arms:
            secondary = registry["secondary"]
            arms[SECONDARY] = arm1.Arm1LiftFirst(grid=secondary["grid"], paths=secondary["paths"],
                                                 path_profile=plan.path_profile, halt=halt)
        completed = run_notes()
        clean = True
        return completed
    finally:
        # Preserve the pulled player's park/hold vs fault/body-torque-off policy,
        # applied PER ARM: clean -> each arm parks once via its reviewed exit
        # (one arm at a time) and holds torque; any fault -> no further motion
        # on ANY arm, body torque released (support the body); force stop ->
        # frozen goals held on both. Not thermal qualification. Force Stop stays
        # wired THROUGH the final exits.
        try:
            park_error = None
            for arm in arms.values():
                parked = False
                if clean and not halt.is_set() and park_error is None:
                    try:
                        arm.rest(deadline=deadline)  # reviewed exit only, once, not between notes
                        parked = True
                    except Exception as exc:  # noqa: BLE001 - failed exit is a fault, NOT a completed take
                        park_error = exc
                try:
                    arm.close(torque_off=not parked and not halt.is_set())
                except Exception as exc:  # noqa: BLE001 - keep releasing the remaining arm
                    if park_error is None:
                        park_error = exc
            if park_error is not None:
                raise park_error
        finally:
            with _halt_lock:
                if _active_halt["event"] is halt:
                    _active_halt["event"] = None


# Seven Nation Army riff button: plays the operator-recorded low-E extra poses
# through fret.play semantics outside the rehearsal pipeline (those poses can't
# be expressed in the grid plan schema). Same ownership rules: never during a
# take or calibration session; STOP is cooperative; FORCE STOP freezes it.
_sna_state_lock = threading.Lock()
_sna = {"running": False, "index": -1, "total": len(fret.SNA_RIFF),
        "stop": False, "error": None}


def _sna_thread():
    halt = threading.Event()
    error = None
    try:
        arm = fret.FretArm(path_profile="rest_hub", halt=halt)
    except Exception as exc:  # noqa: BLE001 - report, never retry motion
        with _sna_state_lock:
            _sna.update(running=False, index=-1, error=f"arm unavailable: {exc}")
        return
    with _halt_lock:
        _active_halt["event"] = halt
    clean = False
    try:
        for index, (name, gap) in enumerate(fret.SNA_RIFF):
            with _sna_state_lock:
                if _sna["stop"]:
                    break
                _sna["index"] = index
            arm.tap_pose(name)
            time.sleep(gap if gap is not None else 0.2)
        clean = True
    except Exception as exc:  # noqa: BLE001 - fault ends the riff, state recorded
        error = str(exc)
    finally:
        with _halt_lock:
            _active_halt["event"] = None
        # Same end-of-motion contract as takes: clean -> park at rest and HOLD;
        # fault -> release with no recovery motion; force stop -> hold frozen.
        parked = False
        if clean and not halt.is_set():
            try:
                arm.rest()
                parked = True
            except Exception:  # noqa: BLE001
                pass
        try:
            arm.close(torque_off=not parked and not halt.is_set())
        except Exception:  # noqa: BLE001
            pass
        with _sna_state_lock:
            _sna.update(running=False, index=-1, error=error)


def sna_running():
    with _sna_state_lock:
        return _sna["running"]


manager = RehearsalManager(RUN_ROOT, registry=read_registry, execute=execute_take,
                           admit=admit_motion, lock=calibration.ownership_lock,
                           calibration_active=calibration.session_active)
calibration.set_play_guard(lambda: manager.busy or sna_running())

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
    # Optional: arrange from an official Songsterr tab. The tab is fetched
    # SERVER-side by songsterr.py and passed to the planner as musical data.
    songsterr_song_id: int | None = Field(default=None, ge=1, le=10_000_000)
    songsterr_track: int | None = Field(default=None, ge=0, le=63)


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


def _planning_key_union(registry):
    """Primary keys plus the secondary's ONLY when it is fully available."""
    keys = set(registry["keys"])
    secondary = registry.get("secondary") or {}
    if secondary.get("available"):
        keys |= set(secondary["keys"])
    return keys


@app.get("/api/bootstrap")
def bootstrap():
    try:
        registry = read_registry()
        keys, warning = key_context(_planning_key_union(registry)), None
    except RehearsalError as exc:
        registry, keys, warning = None, [], str(exc)
    profiles = list(registry.get("path_profiles", ())) if registry else []
    secondary = (registry.get("secondary") or {}) if registry else {}
    audio_model = os.environ.get("BASETEN_AUDIO_MODEL") or DEFAULT_AUDIO_MODEL
    return {"session_token": SESSION_TOKEN, "keys": keys, "warning": warning,
            "keypoint_warnings": registry["warnings"] if registry else [],
            "max_notes": MAX_NOTES, "max_take_notes": MAX_TAKE_NOTES, "max_attempts": MAX_ATTEMPTS,
            "max_capture_seconds": MAX_CAPTURE_SECONDS, "max_play_seconds": MAX_PLAY_SECONDS,
            "note_pace_s": NOTE_PACE_S, "hardware": "real_single_tap_arm",
            "camera": False, "plucking": False, "auto_replay": False,
            "path_profiles": profiles, "shortcuts_qualified": PROFILE in profiles,
            "preferred_path_profile": PROFILE, "paths_ready": PROFILE in profiles,
            "path_blocker": registry.get("path_blocker") if registry else warning,
            "recorded_hover_count": len(registry.get("hovers", {})) if registry else 0,
            "arm_capabilities": (registry.get("capabilities") if registry else None)
                                or arm_capabilities(registry["keys"] if registry else set(),
                                                    primary_ready=PROFILE in profiles,
                                                    secondary_keys=secondary.get("keys") or set(),
                                                    secondary_ready=secondary.get("paths") is not None,
                                                    secondary_blocker=secondary.get("path_blocker")),
            "secondary_available": bool(secondary.get("available")),
            "secondary_path_blocker": secondary.get("path_blocker"),
            "secondary_key_count": len(secondary.get("keys") or ()),
            "secondary_hover_count": len(secondary.get("hovers") or ()),
            "coordination": ("sequential shared-workspace ownership; one arm moves at a time"
                            if secondary.get("available") else
                            "sequential shared-workspace ownership; secondary arm unavailable"),
            "extra_pose_playback_enabled": False,
            "key_present": bool(os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")),
            "planner_model": os.environ.get("BASETEN_MODEL") or DEFAULT_MODEL,
            "audio_model": audio_model, "audio_model_supported": audio_model in AUDIO_MODELS,
            "audio_endpoint_status": "Configured on Baseten; startup does not probe health. "
                                     "See each take's actual reviewer, fallback and result.",
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
        planner_keys = set(registry["paths"].keys if registry.get("paths") else registry["keys"])
        secondary = registry.get("secondary") or {}
        # Only a fully available secondary (recorded keys AND compiled reviewed
        # paths) contributes its qualified keys; notes derive their arm from the
        # fret row (tap_arms.ROW_OWNERS) and are re-validated by assign().
        secondary_keys = set(secondary["paths"].keys) if secondary.get("available") else set()
        if req.songsterr_song_id is not None:
            # Official-tab mode is DETERMINISTIC: the tab's notes are mapped
            # pitch-exactly onto the recorded keys by local code (one global
            # transpose, nearest-pitch fallback). No model call, so the notes
            # can never be paraphrased.
            try:
                tab = songsterr.fetch_track_notes(req.songsterr_song_id, req.songsterr_track)
            except songsterr.SongsterrError as exc:
                raise HTTPException(502, f"Songsterr: {exc}") from None
            result = songsterr.transcribe(tab, planner_keys | secondary_keys, max_notes=MAX_NOTES)
            if not result["notes"]:
                raise HTTPException(502, "This tab's notes do not map onto the recorded "
                                         "keys (out of range even after transposing)")
            return {"title": f"{tab['artist']} — {tab['song']} (official tab)",
                    "model": "deterministic-tab-transcription",
                    "notes": [{"arm": owner_of_row(f), "string": s, "fret": f}
                              for s, f in result["notes"]],
                    "path_profile": PROFILE,
                    "tab_source": {"songId": req.songsterr_song_id,
                                   "artist": tab["artist"], "song": tab["song"],
                                   "track": tab["track_name"]},
                    "transcription": {k: result[k] for k in
                                      ("transpose", "exact", "approximated",
                                       "dropped", "total")}}
        return arrange(req.prompt, planner_keys,
                       motion_context=registry["paths"].model_context() if registry.get("paths") else None,
                       secondary_keys=secondary_keys,
                       secondary_motion_context=(secondary["paths"].model_context()
                                                 if secondary.get("available") else None))
    except (BasetenError, ValueError):
        raise HTTPException(502, "Baseten planning unavailable or invalid response; no automatic retry") from None
    finally:
        _plan_lock.release()


class TrajectoryReq(StrictModel):
    plan: TapPlan


@app.post("/api/trajectory")
def trajectory(req: TrajectoryReq):
    """Local, device-free preview. No microphone, audio evaluator, or billed inference."""
    try:
        registry = read_registry()
        compiled = admit_motion(req.plan, registry)
        return {"executable": True, "blockers": [], "trajectory": compiled,
                "capability_fingerprint": registry["fingerprint"]}
    except RehearsalError as exc:
        return {"executable": False, "blockers": [str(exc)], "trajectory": None}


@app.get("/api/tabs/search")
def tabs_search(pattern: str):
    """Find official Songsterr tabs by song/artist name. Read-only lookup."""
    pattern = pattern.strip()
    if not 1 <= len(pattern) <= 200:
        raise HTTPException(400, "Give a song or artist name (1-200 characters)")
    try:
        return {"results": songsterr.search(pattern)}
    except songsterr.SongsterrError as exc:
        raise HTTPException(502, f"Songsterr: {exc}") from None


@app.post("/api/attempts")
def prepare(req: PrepareReq):
    if sna_running():
        raise RehearsalError("The riff is playing — wait for it to finish")
    if not (os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")):
        raise RehearsalError("Configure the server-side Baseten credential before a recorded take")
    if (os.environ.get("BASETEN_AUDIO_MODEL") or DEFAULT_AUDIO_MODEL) not in AUDIO_MODELS:
        raise RehearsalError("Select a supported audio evaluator; the Kimi planner cannot receive this WAV")
    return manager.create(req.plan, parent_attempt_id=req.parent_attempt_id,
                          source_attempt_id=req.source_attempt_id, session_id=req.session_id, title=req.title)


@app.post("/api/play")
def play(req: PlayReq):
    if sna_running():
        raise RehearsalError("The riff is playing — wait for it to finish")
    capture = CaptureStart.model_validate(req.model_dump(exclude={"attempt_id"}))
    return manager.start(req.attempt_id, capture)


class SnaReq(StrictModel):
    supervised_and_supported: Consent


@app.post("/api/play-sna")
def play_sna(req: SnaReq):
    """The old riff bypass cannot re-enable contact-only rest-hub playback."""
    raise RehearsalError("Extra-pose riff playback is blocked until its own lift/hover paths "
                         "are recorded and reviewed; no rest-hub fallback. Use qualified grid notes.")


class SnaStopReq(StrictModel):
    pass  # explicit empty JSON body


@app.post("/api/sna-stop")
def sna_stop(_req: SnaStopReq):
    """Cooperative riff stop: the current bounded tap finishes, then it parks."""
    with _sna_state_lock:
        _sna["stop"] = True
    return {"stopping": True}


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
    with _sna_state_lock:
        sna = dict(_sna)
    return {"active_attempt": manager.active(), "sna": sna}


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
