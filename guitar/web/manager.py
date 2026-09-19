"""One fake run at a time, cooperative controls, and bounded read-only log access."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from orchestration.control import RunControl
from orchestration.runner import RequestPacer, run
from orchestration.scenarios import Scenario

MAX_LOG_BYTES = 8 * 1024 * 1024
FILES = {"events.jsonl", "summary.json", "tools.json"}


@dataclass
class Job:
    id: str
    directory: Path
    created_at: str
    scenario: str
    prompt: str
    settings: dict
    control: RunControl = field(default_factory=RunControl)
    events: list[dict] = field(default_factory=list)
    state: dict | None = None
    report: dict | None = None
    finished: bool = False


class RunManager:
    def __init__(self, root: Path, backend_factory, *, request_interval: float = 6):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend_factory = backend_factory
        self.pacer = RequestPacer(request_interval)
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.index: dict[str, Path] = {}
        self.active_id: str | None = None
        self.thread: threading.Thread | None = None

    def _id(self, directory: Path) -> str:
        relative = directory.resolve().relative_to(self.root).as_posix()
        return hashlib.sha256(relative.encode()).hexdigest()[:24]

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise FileNotFoundError("Log path outside run directory")
        return resolved

    def _read_json(self, path: Path) -> dict:
        path = self._inside(path)
        if path.stat().st_size > MAX_LOG_BYTES:
            raise ValueError("Log is too large for the dashboard")
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid log object")
        return data

    def _discover(self) -> None:
        # No arbitrary paths from the browser. History IDs are opaque hashes of known run dirs.
        for filename in ("summary.json", "events.jsonl"):
            for path in self.root.rglob(filename):
                try:
                    safe = self._inside(path)
                    directory = safe.parent
                    self.index[self._id(directory)] = directory
                except (ValueError, OSError):
                    continue

    def start(self, scenario: Scenario, *, prompt: str, settings: dict) -> dict:
        with self.lock:
            if self.active_id and not self.jobs[self.active_id].finished:
                raise RuntimeError("A run is already active; stop or finish it first")
            created = datetime.now(timezone.utc)
            directory = self.root / "web" / f"{created.strftime('%Y%m%dT%H%M%S.%fZ')}-{scenario.name}-{uuid4().hex[:6]}"
            job_id = self._id(directory)
            job = Job(job_id, directory, created.isoformat(), scenario.name, prompt, dict(settings))
            self.jobs[job_id] = job
            self.index[job_id] = directory
            self.active_id = job_id
            self.thread = threading.Thread(target=self._worker, args=(job, scenario), daemon=True,
                                           name=f"fake-orchestration-{job_id}")
            self.thread.start()
            return self._snapshot(job)

    def _worker(self, job: Job, scenario: Scenario) -> None:
        def on_event(event):
            with self.lock:
                job.events.append(event)
                if event["type"] == "start":
                    job.state = event["opening"]["state"]
                elif event["type"] == "tool":
                    job.state = event["after"]
                elif event["type"] == "summary":
                    job.report = event["report"]

        try:
            backend = self.backend_factory(effort=job.settings["effort"],
                                           max_tokens=job.settings["max_output_tokens"])
            report = run(scenario, backend, output_dir=job.directory, verbose=False,
                         max_calls=job.settings["max_calls"], seconds=job.settings["seconds"],
                         pacer=self.pacer, operator_prompt=job.prompt,
                         control=job.control, on_event=on_event)
            with self.lock:
                job.report = report
                job.state = report["final_state"]
        except Exception as exc:
            # Do not expose arbitrary exception strings/credentials from a backend factory.
            report = {
                "schema_version": "guitarra.web-start-error.v1", "scenario": scenario.name,
                "checked_at_utc": datetime.now(timezone.utc).isoformat(), "mode": "fake_only",
                "hardware_enabled": False, "camera_used": False, "audio_used": False,
                "operator_prompt": job.prompt, "goal": scenario.task(),
                "error": f"Run could not finish ({type(exc).__name__}); inspect local setup/log permissions.",
                "stop_reason": "runner_error", "evaluation": {"status": "incomplete", "passed": False},
            }
            with self.lock:
                job.report = report
            try:
                job.directory.mkdir(parents=True, exist_ok=True)
                # Preserve any core-runner report already written.
                with (job.directory / "summary.json").open("x") as stream:
                    json.dump(report, stream, indent=2)
            except OSError:
                pass
        finally:
            with self.lock:
                job.finished = True

    def _snapshot(self, job: Job) -> dict:
        control = job.control.snapshot()
        status = "finished" if job.finished else (
            "stopping" if control["cancel_requested"] else
            "paused" if control["paused"] else
            "pausing" if control["pause_requested"] else "running")
        return copy.deepcopy({
            "id": job.id, "created_at": job.created_at, "scenario": job.scenario,
            "status": status, "prompt": job.prompt, "settings": job.settings,
            "state": job.state, "report": job.report,
            "event_count": len(job.events), "control": control,
            "directory": str(job.directory),
        })

    def _directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{24}", job_id):
            raise FileNotFoundError("Unknown run")
        if job_id not in self.index:
            self._discover()
        if job_id not in self.index:
            raise FileNotFoundError("Unknown run")
        return self._inside(self.index[job_id])

    def get(self, job_id: str) -> dict:
        with self.lock:
            if job_id in self.jobs:
                return self._snapshot(self.jobs[job_id])
            directory = self._directory(job_id)
            report = self._read_json(directory / "summary.json") if (directory / "summary.json").exists() else None
            return {
                "id": job_id, "created_at": (report or {}).get("checked_at_utc", directory.name),
                "scenario": (report or {}).get("scenario", "unmanaged run"),
                "status": "finished" if report else "unmanaged", "prompt": (report or {}).get("operator_prompt", ""),
                "settings": {}, "state": (report or {}).get("final_state"), "report": report,
                "directory": str(directory), "control": {},
            }

    def history(self) -> dict:
        with self.lock:
            self._discover()
            rows = []
            for job_id in list(self.index):
                try:
                    item = self.get(job_id)
                except (OSError, ValueError):
                    continue
                report = item.get("report") or {}
                evaluation = report.get("evaluation") or {}
                rows.append({"id": job_id, "created_at": item["created_at"], "scenario": item["scenario"],
                             "status": item["status"], "result": evaluation.get("status") or (
                                 "passed" if evaluation.get("passed") else "incomplete"),
                             "tool_calls": evaluation.get("tool_calls"), "model": report.get("model")})
            active = self.active_id if self.active_id and not self.jobs[self.active_id].finished else None
            return {"active_id": active, "runs": sorted(rows, key=lambda r: r["created_at"], reverse=True)[:100]}

    def events(self, job_id: str, after: int) -> dict:
        with self.lock:
            if job_id in self.jobs:
                events = self.jobs[job_id].events
                return {"events": copy.deepcopy(events[after:]), "next_cursor": len(events)}
            directory = self._directory(job_id)
            path = self._inside(directory / "events.jsonl")
            if not path.exists():
                return {"events": [], "next_cursor": 0}
            if path.stat().st_size > MAX_LOG_BYTES:
                raise ValueError("Log too large for timeline; use the download")
            events = []
            for line in path.read_text().splitlines(keepends=True):
                if line.endswith("\n") and line.strip():
                    events.append(json.loads(line))
            return {"events": events[after:], "next_cursor": len(events)}

    def command(self, job_id: str, action: str) -> dict:
        with self.lock:
            if job_id not in self.jobs or self.jobs[job_id].finished:
                raise RuntimeError("This run is not active")
            control = self.jobs[job_id].control
            if action == "pause":
                control.pause()
            elif action == "resume":
                control.resume()
            elif action == "stop":
                control.cancel()
            else:
                raise ValueError("Unknown control")
            return self._snapshot(self.jobs[job_id])

    def file(self, job_id: str, filename: str) -> Path:
        if filename not in FILES:
            raise FileNotFoundError("Unknown log file")
        with self.lock:
            path = self._inside(self._directory(job_id) / filename)
            if not path.is_file():
                raise FileNotFoundError("Log not written yet")
            return path

    def shutdown(self) -> None:
        with self.lock:
            for job in self.jobs.values():
                if not job.finished:
                    job.control.cancel()
