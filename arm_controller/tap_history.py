"""Private, bounded rehearsal history. Saved plans/audio are evidence, never auto-replays."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tap_plans import TapPlan, pitch

MAX_SESSION_TAKES = 100


def canonical_id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError("Noncanonical identifier")
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid recording/session identifier") from None
    return value


def private_file(root: Path, *parts: str) -> Path:
    """Only caller-allowlisted filenames/UUIDs; no symlinks out of the run archive."""
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Archive path is outside the private run directory")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Symlinked archive entries are not served")
        current = current.parent
    return path


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        raise ValueError("Archive record too large")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Invalid archive record")  # noqa: TRY004 - invalid serialized value, not a caller type error
    return result


def write_json(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False))
    temporary.chmod(0o600)
    temporary.replace(path)


def tuning_id(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:12]


def phrase_key(plan: dict):
    return [pitch(n["string"], n["fret"]) for n in plan["notes"]]


class SessionArchive:
    def __init__(self, root: Path, read_attempt):
        self.root, self.read_attempt = Path(root), read_attempt

    def _path(self, session_id):
        return private_file(self.root, "sessions", canonical_id(session_id) + ".json")

    def create(self, title: str, plan: TapPlan) -> dict:
        session = {"session_id": str(uuid.uuid4()), "title": title[:80] or "Rehearsal",
                   "created_at": datetime.now(timezone.utc).isoformat(),
                   "baseline_plan": plan.model_dump(), "attempt_ids": [], "preferred_attempt_id": None}
        self.save(session)
        return session

    def get(self, session_id) -> dict:
        result = read_json(self._path(session_id))
        if result.get("session_id") != session_id or not isinstance(result.get("attempt_ids"), list):
            raise ValueError("Invalid session archive")
        if len(result["attempt_ids"]) > MAX_SESSION_TAKES:
            raise ValueError("Session archive exceeds the take limit")
        return result

    def save(self, session):
        write_json(self._path(session["session_id"]), session)

    def summaries(self):
        directory = private_file(self.root, "sessions")
        if not directory.exists():
            return []
        result = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            try:
                session = self.get(path.stem)
                result.append({key: session[key] for key in ("session_id", "title", "created_at", "preferred_attempt_id")}
                              | {"take_count": len(session["attempt_ids"])})
            except (OSError, ValueError, KeyError):
                continue  # malformed/interrupted records never become executable plans
        return result

    def history(self, session_id):
        session = self.get(session_id)
        records = []
        for attempt_id in session["attempt_ids"]:
            try:
                record = self.read_attempt(attempt_id)
                if record.get("session_id") != session_id:
                    continue
                records.append(record)
            except (OSError, ValueError):
                continue
        baseline = next((r for r in records if r.get("playback_outcome") == "completed"), None)
        rows = []
        for record in records:
            assessment = record.get("assessment")
            completed = record.get("playback_outcome") == "completed"
            comparable = bool(baseline and completed
                              and record["capability_fingerprint"] == baseline["capability_fingerprint"]
                              and phrase_key(record["plan"]) == phrase_key(baseline["plan"]))
            elapsed = record.get("playback_elapsed_s") if completed else None
            base_elapsed = baseline.get("playback_elapsed_s") if baseline else None
            delta = round(elapsed - base_elapsed, 3) if comparable and elapsed is not None and base_elapsed is not None else None
            rows.append({
                "attempt_id": record["attempt_id"], "take_number": record.get("take_number", len(rows) + 1),
                "created_at": record["created_at"], "phase": record["phase"],
                "playback_outcome": record["playback_outcome"], "tuning_id": tuning_id(record["plan"]),
                "plan": record["plan"], "assessment": assessment, "error": record.get("error"),
                "revision": record.get("revision"), "command_elapsed_s": elapsed,
                "command_delta_from_first_s": delta, "same_phrase_and_calibration": comparable,
                "audio_available": bool(record.get("capture") or record.get("partial_capture")),
                "audio_incomplete": bool(record.get("partial_capture") and not record.get("capture")),
                "can_load_tuning": completed,
                "preferred_by_operator": record["attempt_id"] == session.get("preferred_attempt_id"),
            })
        return {**session, "takes": rows, "max_session_takes": MAX_SESSION_TAKES,
                "comparison_note": "Command duration is not audio quality. Model ratings are uncertain, "
                                   "not calibrated scores. Changed phrases/calibration are not time-compared."}

    def planner_context(self, session_id, current_id):
        # Bounded textual memory, never raw audio, hardware targets, or tool instructions.
        rows = [r for r in self.history(session_id)["takes"] if r["attempt_id"] != current_id][-3:]
        return [{key: row[key] for key in ("take_number", "plan", "assessment", "playback_outcome",
                                           "command_elapsed_s", "same_phrase_and_calibration", "preferred_by_operator")}
                for row in rows]

    def prefer(self, session_id, attempt_id):
        session = self.get(session_id)
        record = self.read_attempt(canonical_id(attempt_id))
        if attempt_id not in session["attempt_ids"] or record.get("playback_outcome") != "completed":
            raise ValueError("Only a completed take in this session can be marked preferred")
        session["preferred_attempt_id"] = attempt_id
        self.save(session)
        return session
