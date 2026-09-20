"""One supervised take -> consented browser WAV -> assessment -> reviewed proposal.

No device access here. The executor/registry are injected by the single-arm web
app. There is deliberately NO auto-replay, model tool dispatch, or recovery move.
"""
from __future__ import annotations

import copy
import io
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from model.audio import evaluate_file, prepare_clip
from pydantic import Field
from tap_history import (
    MAX_SESSION_TAKES,
    SessionArchive,
    canonical_id,
    private_file,
    read_json,
    tuning_id,
    write_json,
)
from tap_audio_metrics import measure_take
from tap_plans import (
    MAX_ATTEMPTS,
    MAX_CAPTURE_SECONDS,
    MAX_PLAY_SECONDS,
    Consent,
    StrictModel,
    TapPlan,
    expected_phrase,
    pitch,
    propose_revision,
    validate_take,
)

TERMINAL = {"review_ready", "keep", "inspect", "unavailable", "stopped", "fault", "expired"}
HEARTBEAT_SECONDS = 8
PROPOSAL_TTL_SECONDS = 300
MAX_WAV_BYTES = MAX_CAPTURE_SECONDS * 96000 * 2 + 4096


class RehearsalError(ValueError):
    """A local admission/state error, never permission to replay."""


CaptureRate = Literal[8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000]


class CaptureStart(StrictModel):
    capture_id: str = Field(min_length=36, max_length=36)
    sample_rate: CaptureRate
    dispatch_frame: int = Field(ge=1, le=MAX_CAPTURE_SECONDS * 96000)
    capture_ready: Consent


class CaptureComplete(StrictModel):
    capture_id: str = Field(min_length=36, max_length=36)
    sample_rate: CaptureRate
    dispatch_frame: int = Field(ge=1, le=MAX_CAPTURE_SECONDS * 96000)
    completion_frame: int = Field(ge=1, le=MAX_CAPTURE_SECONDS * 96000)
    frames: int = Field(ge=1, le=MAX_CAPTURE_SECONDS * 96000)
    elapsed_s: float = Field(gt=0, le=MAX_CAPTURE_SECONDS + 2)
    interrupted: Literal[False]


class PartialCapture(StrictModel):
    capture_id: str = Field(min_length=36, max_length=36)
    sample_rate: CaptureRate
    frames: int = Field(ge=1, le=MAX_CAPTURE_SECONDS * 96000)
    incomplete: Consent


@dataclass
class Attempt:
    record: dict
    registry: dict = field(repr=False)
    stop: threading.Event = field(default_factory=threading.Event, repr=False)
    last_heartbeat: float = 0
    stage_deadline: float = 0
    proposal_deadline: float = 0


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class RehearsalManager:
    def __init__(self, root: Path, *, registry, execute, lock=None, calibration_active=lambda: False,
                 evaluate=evaluate_file, revise=propose_revision, clock=time.monotonic):
        self.root = Path(root)
        self.registry = registry
        self.execute = execute
        self.calibration_active = calibration_active
        self.evaluate = evaluate
        self.revise = revise
        self.clock = clock
        self.lock = lock or threading.RLock()
        self.attempts: dict[str, Attempt] = {}
        self.active_id: str | None = None
        self.archive = SessionArchive(self.root, self.read_attempt)

    @property
    def busy(self):
        with self.lock:
            return self.active_id is not None

    def _get(self, attempt_id):
        try:
            return self.attempts[attempt_id]
        except KeyError:
            raise RehearsalError("Unknown or previous-server attempt; never resume/replay it") from None

    def _save(self, attempt):
        path = private_file(self.root, canonical_id(attempt.record["attempt_id"]), "attempt.json")
        write_json(path, attempt.record)

    def read_attempt(self, attempt_id):
        """Read persisted evidence after restart, but never restore an execution lease."""
        with self.lock:
            if attempt_id in self.attempts:
                return copy.deepcopy(self.attempts[attempt_id].record)
            try:
                path = private_file(self.root, canonical_id(attempt_id), "attempt.json")
                record = read_json(path)
                if record.get("attempt_id") != attempt_id:
                    raise ValueError("Mismatched record")
                TapPlan.model_validate(record["plan"])
            except (OSError, ValueError, KeyError):
                raise RehearsalError("Recording is missing or invalid; no replay is available") from None
            if record["phase"] not in TERMINAL:
                record.update(phase="interrupted", error="Previous process ended; this take cannot resume")
            return record

    def history(self, session_id):
        with self.lock:
            try:
                return self.archive.history(session_id)
            except (OSError, ValueError, KeyError):
                raise RehearsalError("Session history is missing or invalid") from None

    def sessions(self):
        with self.lock:
            return self.archive.summaries()

    def prefer(self, session_id, attempt_id):
        with self.lock:
            try:
                self.archive.prefer(session_id, attempt_id)
                return self.archive.history(session_id)
            except (OSError, ValueError, KeyError):
                raise RehearsalError("Choose a completed take from this session") from None

    def saved_audio(self, attempt_id):
        with self.lock:
            record = self.read_attempt(attempt_id)
            if not (record.get("capture") or record.get("partial_capture")):
                raise RehearsalError("This take has no validated saved recording")
            try:
                filename = "capture.wav" if record.get("capture") else "capture.partial.wav"
                path = private_file(self.root, canonical_id(attempt_id), filename)
                if not path.is_file() or path.stat().st_size > MAX_WAV_BYTES:
                    raise ValueError("Missing/invalid clip")
                return path
            except (OSError, ValueError):
                raise RehearsalError("Saved recording is unavailable") from None

    def _phase(self, attempt, phase, timeout=0):
        attempt.record["phase"] = phase
        attempt.stage_deadline = self.clock() + timeout if timeout else 0
        self._save(attempt)

    def _finish(self, attempt, phase, error=None):
        attempt.record.update(phase=phase, finished_at=utc_now(), error=error)
        attempt.stage_deadline = 0
        if self.active_id == attempt.record["attempt_id"]:
            self.active_id = None
        self._save(attempt)

    def create(self, plan: TapPlan, *, parent_attempt_id=None, source_attempt_id=None,
               session_id=None, title="Rehearsal") -> dict:
        """Reserve one operator-started take; keep history across bounded revision sets."""
        with self.lock:
            if self.busy or self.calibration_active():
                raise RehearsalError("Another take or calibration session owns the arm; finish/disconnect first")
            if parent_attempt_id and source_attempt_id:
                raise RehearsalError("Choose a new proposal OR a saved performed tuning")
            registry = self.registry()
            validate_take(plan, registry["keys"],
                          registry.get("path_profiles", ("rest_hub",)))
            number, parent, source = 1, None, None
            if parent_attempt_id:
                parent = self._get(parent_attempt_id)
                previous = parent.record
                if (previous["phase"] != "review_ready" or not previous.get("revision")
                        or previous.get("child_attempt_id")):
                    raise RehearsalError("This proposal is not available for another attempt")
                if self.clock() >= parent.proposal_deadline:
                    raise RehearsalError("Proposal expired; inspect/replan rather than replay stale motion")
                if previous["capability_fingerprint"] != registry["fingerprint"]:
                    raise RehearsalError("Keypoints/calibration changed; proposal is stale")
                if plan.model_dump() != previous["revision"]["plan"]:
                    raise RehearsalError("Approved plan must exactly match the locally validated proposal")
                number = previous["attempt_number"] + 1
                source = previous
            elif source_attempt_id:
                source = self.read_attempt(source_attempt_id)
                if source.get("playback_outcome") != "completed" or plan.model_dump() != source["plan"]:
                    raise RehearsalError("Only an exact saved completed tuning can be loaded; inspect faults first")
                if source["capability_fingerprint"] != registry["fingerprint"]:
                    raise RehearsalError("Saved tuning calibration is stale; inspect/replan")
            if number > MAX_ATTEMPTS:
                raise RehearsalError("Three-attempt revision set reached; inspect before starting a new supervised set")
            if source:
                if session_id and session_id != source["session_id"]:
                    raise RehearsalError("Saved tuning belongs to a different session")
                session_id = source["session_id"]
            if session_id:
                try:
                    session = self.archive.get(session_id)
                except (OSError, ValueError, KeyError):
                    raise RehearsalError("Session is missing or invalid") from None
                if not source and plan.model_dump() != session["baseline_plan"]:
                    raise RehearsalError("Load a saved tuning or start a new phrase session")
            else:
                session = self.archive.create(title, plan)
            if len(session["attempt_ids"]) >= MAX_SESSION_TAKES:
                raise RehearsalError("Session archive limit reached; explicitly start a new session")
            attempt_id, capture_id = str(uuid.uuid4()), str(uuid.uuid4())
            (self.root / attempt_id).mkdir(mode=0o700)
            record = {
                "schema_version": "guitarra.tap-rehearsal.v1", "attempt_id": attempt_id,
                "capture_id": capture_id, "created_at": utc_now(), "phase": "ready",
                "session_id": session["session_id"], "take_number": len(session["attempt_ids"]) + 1,
                "attempt_number": number, "max_attempts": MAX_ATTEMPTS,
                "parent_attempt_id": parent_attempt_id, "source_attempt_id": source_attempt_id,
                "original_plan": session["baseline_plan"], "tuning_id": tuning_id(plan.model_dump()),
                "plan": plan.model_dump(), "capability_fingerprint": registry["fingerprint"],
                "consent": {"browser_mic_and_baseten_upload": True, "one_revision_request": True,
                            "supervised_play_and_body_support": True},
                "index": -1, "completed_notes": 0, "total": len(plan.notes),
                "stop_requested": False, "error": None, "telemetry": [],
                "playback_outcome": "not_started", "assessment": None, "revision": None,
                "audio_model_report": None, "is_physical_qualification": False,
                "auto_replay": False, "camera": False,
            }
            attempt = Attempt(record, registry, last_heartbeat=self.clock())
            self.attempts[attempt_id] = attempt
            self.active_id = attempt_id
            if parent:
                parent.record["child_attempt_id"] = attempt_id
                self._save(parent)
            self._phase(attempt, "ready", timeout=60)
            session["attempt_ids"].append(attempt_id)
            self.archive.save(session)
            threading.Thread(target=self._watch, args=(attempt,), daemon=True).start()
            return copy.deepcopy(record)

    def start(self, attempt_id, capture: CaptureStart):
        with self.lock:
            attempt = self._get(attempt_id)
            record = attempt.record
            if capture.capture_id != record["capture_id"]:
                raise RehearsalError("Capture does not belong to this attempt")
            if capture.dispatch_frame >= capture.sample_rate * MAX_CAPTURE_SECONDS:
                raise RehearsalError("Capture has already exhausted its recording budget")
            if record["phase"] != "ready":
                # Idempotent acknowledgement of an already-started request, NEVER replay.
                if record.get("capture_start") == capture.model_dump():
                    return copy.deepcopy(record)
                raise RehearsalError("Attempt is not awaiting its first Play request")
            if attempt.stop.is_set() or self.clock() >= attempt.stage_deadline:
                self._finish(attempt, "expired", "Reservation expired before capture was ready")
                raise RehearsalError("Reservation expired; no motion started")
            if self.calibration_active() or self.registry()["fingerprint"] != record["capability_fingerprint"]:
                self._finish(attempt, "expired", "Calibration/keypoints changed before Play")
                raise RehearsalError("Calibration/keypoints changed before Play; no motion started")
            record.update(capture_start=capture.model_dump(), playback_outcome="running")
            attempt.last_heartbeat = self.clock()
            self._phase(attempt, "playing", timeout=MAX_PLAY_SECONDS)
            threading.Thread(target=self._play, args=(attempt,), daemon=True).start()
            return copy.deepcopy(record)

    def status(self, attempt_id):
        with self.lock:
            return copy.deepcopy(self._get(attempt_id).record)

    def active(self):
        with self.lock:
            return self.status(self.active_id) if self.active_id else None

    def heartbeat(self, attempt_id):
        with self.lock:
            attempt = self._get(attempt_id)
            attempt.last_heartbeat = self.clock()
            return {"phase": attempt.record["phase"], "stop_requested": attempt.stop.is_set()}

    def stop(self, attempt_id, reason="Operator stopped; no automatic replay"):
        with self.lock:
            attempt = self._get(attempt_id)
            if attempt.record["phase"] in TERMINAL:
                return copy.deepcopy(attempt.record)
            attempt.stop.set()
            attempt.record.update(stop_requested=True, error=reason)
            if attempt.record["phase"] in {"ready", "awaiting_audio"}:
                self._finish(attempt, "stopped", reason)
            else:
                self._save(attempt)
            return copy.deepcopy(attempt.record)

    def _watch(self, attempt):
        while True:
            time.sleep(0.25)
            with self.lock:
                if attempt.record["phase"] in TERMINAL:
                    return
                now = self.clock()
                reason = None
                if now - attempt.last_heartbeat > HEARTBEAT_SECONDS:
                    reason = "Browser heartbeat lost; stop after the current bounded tap, no replay"
                elif attempt.stage_deadline and now >= attempt.stage_deadline:
                    reason = "Local stage/time budget expired; no automatic replay"
                if reason and not attempt.stop.is_set():
                    self.stop(attempt.record["attempt_id"], reason)

    def _play(self, attempt):
        started = self.clock()

        def emit(event):
            with self.lock:
                event = {**event, "server_elapsed_s": round(self.clock() - started, 4)}
                attempt.record["telemetry"].append(event)
                if event["event"] == "note_start":
                    attempt.record["index"] = event["index"]
                elif event["event"] == "note_end":
                    attempt.record["completed_notes"] += 1

        try:
            completed = self.execute(TapPlan.model_validate(attempt.record["plan"]),
                                     attempt.registry, attempt.stop, emit)
            with self.lock:
                attempt.record["playback_elapsed_s"] = round(self.clock() - started, 4)
                if attempt.stop.is_set() or not completed:
                    attempt.record["playback_outcome"] = "stopped"
                    self._finish(attempt, "stopped", attempt.record["error"] or "Stopped before completion")
                else:
                    attempt.record["playback_outcome"] = "completed"
                    # Executor has closed/released BODY torque before any network wait.
                    self._phase(attempt, "awaiting_audio", timeout=30)
        except Exception as exc:  # noqa: BLE001 - boundary must fail closed on any driver failure
            with self.lock:
                attempt.record["playback_outcome"] = "fault"
                self._finish(attempt, "fault", f"Playback failed ({type(exc).__name__}); "
                             "state uncertain, inspect the arm. No recovery/homing or review.")

    def accept_audio(self, attempt_id, metadata: CaptureComplete, wav_bytes: bytes):
        """Exactly one complete clip bound to a COMPLETED take; never accept arbitrary paths."""
        with self.lock:
            attempt = self._get(attempt_id)
            record = attempt.record
            if record["phase"] != "awaiting_audio" or attempt.stop.is_set():
                raise RehearsalError("Audio requires a completed, uncancelled take awaiting its own recording")
            start = record["capture_start"]
            if any(getattr(metadata, key) != start[key]
                   for key in ("capture_id", "sample_rate", "dispatch_frame")):
                raise RehearsalError("Recording identity/timebase does not match this take")
            if not 0 < len(wav_bytes) <= MAX_WAV_BYTES:
                raise RehearsalError("Recording exceeds the bounded WAV upload size")
            self._phase(attempt, "processing_audio", timeout=20)
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE"
                        or wav.getframerate() != metadata.sample_rate or wav.getnframes() != metadata.frames):
                    raise ValueError("Browser WAV and capture metadata disagree")
            duration = metadata.frames / metadata.sample_rate
            covered_play = (metadata.completion_frame - metadata.dispatch_frame) / metadata.sample_rate
            if (not 0 < metadata.dispatch_frame < metadata.completion_frame <= metadata.frames
                    or duration > MAX_CAPTURE_SECONDS
                    or abs(duration - metadata.elapsed_s) > 2
                    or covered_play + 0.75 < record["playback_elapsed_s"]):
                raise ValueError("Incomplete/interrupted or misaligned capture; no assessment")
            path = self.root / attempt_id / "capture.wav"
            with path.open("xb") as stream:
                stream.write(wav_bytes)
            path.chmod(0o600)
            clip = prepare_clip(path)
            with self.lock:
                record["capture"] = {**metadata.model_dump(), "clip": clip.metadata,
                                     "timebase": "browser sample frames; server alignment is approximate",
                                     "source": "browser_microphone", "device_identity": "not_collected"}
                if attempt.stop.is_set():
                    self._finish(attempt, "stopped", record["error"])
                elif clip.metadata["local_signal_estimates"]["rms_dbfs"] is None:
                    self._finish(attempt, "unavailable", "Capture contains only zero samples; "
                                 "not a missed-note diagnosis. No provider request made.")
                else:
                    self._phase(attempt, "reviewing", timeout=100)
                    threading.Thread(target=self._review, args=(attempt, path), daemon=True).start()
                return copy.deepcopy(record)
        except Exception as exc:  # noqa: BLE001 - incomplete capture must never reach the provider
            with self.lock:
                self._finish(attempt, "unavailable", f"Recording validation failed ({type(exc).__name__}); "
                             "no assessment or replay")
            raise RehearsalError("Recording was incomplete/invalid; no audio-model request made") from None

    def save_partial(self, attempt_id, metadata: PartialCapture, wav_bytes: bytes):
        """Keep interrupted audio locally for inspection; NEVER evaluate or replay it."""
        with self.lock:
            attempt = self._get(attempt_id)
            record = attempt.record
            start = record.get("capture_start")
            if (not start or not (attempt.stop.is_set() or record["phase"] in {"fault", "stopped"})
                    or record.get("partial_capture") or record.get("capture")):
                raise RehearsalError("Only one interrupted recording from a stopped/faulted take can be saved")
            if metadata.capture_id != record["capture_id"] or metadata.sample_rate != start["sample_rate"]:
                raise RehearsalError("Partial recording does not match this take")
            if not 0 < len(wav_bytes) <= MAX_WAV_BYTES:
                raise RehearsalError("Partial recording exceeds the upload limit")
            try:
                with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                    if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE"
                            or wav.getframerate() != metadata.sample_rate or wav.getnframes() != metadata.frames):
                        raise ValueError("Partial capture metadata mismatch")
                    if not 0 < metadata.frames <= metadata.sample_rate * MAX_CAPTURE_SECONDS:
                        raise ValueError("Partial duration exceeds capture budget")
                    if len(wav.readframes(metadata.frames)) != metadata.frames * 2:
                        raise ValueError("Truncated WAV")
                path = private_file(self.root, canonical_id(attempt_id), "capture.partial.wav")
                with path.open("xb") as stream:
                    stream.write(wav_bytes)
                path.chmod(0o600)
                clip = prepare_clip(path)
            except (OSError, ValueError, wave.Error, EOFError):
                raise RehearsalError("Partial WAV is invalid; no evaluation performed") from None
            record["partial_capture"] = {**metadata.model_dump(), "clip": clip.metadata,
                                         "source": "browser_microphone_partial", "uploaded_to_baseten": False}
            self._save(attempt)
            return {"saved_locally": True, "incomplete": True, "uploaded_to_baseten": False}

    def _review(self, attempt, path):
        record = attempt.record
        plan = TapPlan.model_validate(record["plan"])
        # Deterministic local measurement FIRST: reproducible per-note onset/
        # clarity/pitch numbers from the capture itself. This — not the audio
        # model's hearing — is the planner's primary evidence. Local DSP only.
        try:
            metrics = measure_take(path.read_bytes(), record["telemetry"],
                                   int(record["capture"]["dispatch_frame"]),
                                   [pitch(n.string, n.fret) for n in plan.notes])
        except Exception as exc:  # noqa: BLE001 - measurement is best-effort, never blocks
            metrics = {"error": f"local measurement failed ({type(exc).__name__})"}
        with self.lock:
            record["acoustic_metrics"] = metrics
            self._save(attempt)
        try:
            # No retry here: one audio request, and at most one text revision request.
            report = self.evaluate(path, expected_phrase=expected_phrase(plan),
                                   attempt_id=record["attempt_id"], source="browser_microphone",
                                   allow_upload=True)
            with self.lock:
                if attempt.stop.is_set():
                    self._finish(attempt, "stopped", record["error"])
                    return
                record["audio_model_report"] = report
                if report["status"] != "assessed":
                    self._finish(attempt, "unavailable", report.get("error", "Audio assessment unavailable"))
                    return
                assessment = record["assessment"] = report["assessment"]
                # Only a genuinely empty/corrupt recording blocks the loop now.
                # Uncertain hearing still reaches the planner WITH its caveats —
                # the operator sees the graded score/suggestions either way, and
                # the planner may simply decide "keep" on weak evidence.
                if assessment["recording_quality"] == "unusable":
                    self._finish(attempt, "inspect", "Recording unusable; check the microphone, then listen and retake")
                    return
                if record["attempt_number"] >= MAX_ATTEMPTS:
                    self._finish(attempt, "inspect", "Three-attempt budget reached; assessment saved, no further revision")
                    return
                self._phase(attempt, "revising", timeout=65)
            history = self.archive.planner_context(record["session_id"], record["attempt_id"])
            revision = self.revise(plan, attempt.registry["keys"], assessment, copy.deepcopy(record["telemetry"]),
                                   history=history,
                                   allowed_profiles=attempt.registry.get("path_profiles", ("rest_hub",)),
                                   acoustic_metrics=copy.deepcopy(metrics))
            with self.lock:
                if attempt.stop.is_set():
                    self._finish(attempt, "stopped", record["error"])
                    return
                if self.registry()["fingerprint"] != record["capability_fingerprint"]:
                    self._finish(attempt, "expired", "Keypoints/calibration changed during review; proposal discarded")
                    return
                record["revision"] = revision
                attempt.proposal_deadline = self.clock() + PROPOSAL_TTL_SECONDS
                record["proposal_ttl_s"] = PROPOSAL_TTL_SECONDS
                phase = "review_ready" if revision["decision"] == "revise" else revision["decision"]
                self._finish(attempt, phase)
        except Exception as exc:  # noqa: BLE001 - reject all provider/parser failures, never replay
            with self.lock:
                self._finish(attempt, "stopped" if attempt.stop.is_set() else "unavailable",
                             record["error"] if attempt.stop.is_set() else
                             f"Review/revision unavailable ({type(exc).__name__}); unchanged plan, no automatic retry/replay")
