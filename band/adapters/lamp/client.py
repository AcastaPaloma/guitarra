"""SDK v1 lifecycle client; no raw motor, dashboard, or torque fallback.

An action's success proves executor completion, not physical tracking accuracy.
The runtime still owns entry transitions, collision checks and the serial bus.
This adapter does not provide exclusive ownership against other controllers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from band.performance.primitives import JOINTS

TERMINAL = {"succeeded", "failed", "rejected", "canceled"}


class LampError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LampError("SDK redirect refused; verify the runtime address")


@dataclass(frozen=True)
class Observation:
    data: dict
    received_monotonic: float
    round_trip_seconds: float


class LampClient:
    def __init__(self, base_url, token, ledger: Path, *, transport=None,
                 clock=time.monotonic, sleep=time.sleep):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Expected a runtime origin without credentials or path")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Use HTTPS or an SSH tunnel for SDK credentials")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("An SDK token is required; authentication cannot be bypassed")
        self.base_url, self._token = base_url.rstrip("/"), token
        self.clock, self.sleep = clock, sleep
        self._transport = transport or self._http
        self._session = None
        self._active = None
        ledger.parent.mkdir(parents=True, exist_ok=True)
        self._ledger = sqlite3.connect(ledger)
        self._ledger.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, session TEXT, digest TEXT, action TEXT)")
        self._ledger.commit()
        ledger.chmod(0o600)

    def close(self):
        self._ledger.close()

    def _http(self, method, path, body, content_type):
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                   "Content-Type": content_type}
        if self._session:
            headers["X-LeLamp-SDK-Session"] = self._session
        request = Request(self.base_url + "/api/sdk/v1" + path, data=body,
                          headers=headers, method=method)
        try:
            with build_opener(NoRedirect()).open(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as error:
            # Do not echo arbitrary response bodies or headers containing secrets.
            raise LampError(f"SDK HTTP {error.code} for {method} {path}") from None

    def _request(self, method, path, data=None, *, csv=None):
        body = csv if csv is not None else (json.dumps(data, allow_nan=False).encode() if data is not None else None)
        result = self._transport(method, path, body, "text/csv" if csv is not None else "application/json")
        if not isinstance(result, dict) or result.get("ok") is not True:
            code = result.get("error", {}).get("code", "invalid_response") if isinstance(result, dict) else "invalid_response"
            raise LampError(f"SDK request failed: {code}")
        return result

    def connect(self):
        if self._session:
            raise LampError("Client already has a session")
        capabilities = self._request("GET", "/capabilities")
        if capabilities.get("protocol_version") != "lelamp.sdk.v1":
            raise LampError("Unsupported SDK protocol")
        names = {item["name"] for item in capabilities.get("capabilities", []) if item.get("available") is True}
        if "clip.play" not in names:
            raise LampError("clip.play is unavailable")
        for resource in ("joints", "clips"):
            if capabilities.get("resources", {}).get(resource, {}).get("available") is not True:
                raise LampError(f"{resource} resource is unavailable")
        result = self._request("POST", "/sessions", {"app_id": "guitarra.rehearsal", "metadata": {"version": 1}})
        self._session = result["session"]["session_id"]
        if not isinstance(self._session, str) or not self._session:
            raise LampError("Malformed session response")

    def observe(self):
        start = self.clock()
        data = self._request("GET", "/joints")
        end = self.clock()
        positions = data.get("positions", {})
        if set(positions) != set(JOINTS) or any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or not -100 <= v <= 100 for v in positions.values()):
            raise LampError("Invalid joint telemetry")
        return Observation(data, end, end - start)

    def _fresh(self, observation, robot_id, calibration_id):
        if not self._session:
            raise LampError("Connect before using motion resources")
        age = self.clock() - observation.received_monotonic
        if not 0 <= age <= 2 or not 0 <= observation.round_trip_seconds <= 1:
            raise LampError("Stale or delayed observation; obtain fresh telemetry")
        info = observation.data
        if robot_id == "simulation" or info.get("robot_id") != robot_id or info.get("calibration_id") != calibration_id:
            raise LampError("Device/calibration identity mismatch")
        if info.get("units") != "normalized_m100_100" or info.get("self_collision_check") is not True:
            raise LampError("Checked normalized motion is unavailable")

    def upload_scene(self, compiled, stage):
        stage.validate()
        if compiled.envelope_id != stage.envelope_id:
            raise LampError("Scene/stage envelope mismatch")
        observation = self.observe()
        self._fresh(observation, stage.robot_id, stage.calibration_id)
        return self._request("POST", "/clips", csv=compiled.csv_bytes())["clip"]

    def play_clip(self, clip, observation, *, idempotency_key):
        self._fresh(observation, clip["robot_id"], clip["calibration_id"])
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("Use a unique, nonempty trial key of at most 128 characters")
        payload = {"command_type": "clip.play", "payload": {"clip_id": clip["id"]},
                   "idempotency_key": idempotency_key}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self._ledger:
            existing = self._ledger.execute("SELECT session,digest,action FROM requests WHERE key=?", (idempotency_key,)).fetchone()
            if existing and (existing[0] != self._session or existing[1] != digest):
                raise LampError("Trial key already belongs to another session or payload")
            if existing and existing[2]:
                return self.action(existing[2])
            pending = self._ledger.execute("SELECT key FROM requests WHERE action IS NULL AND key != ?", (idempotency_key,)).fetchone()
            if pending:
                raise LampError("A previous submission has unknown status; reconcile it before another trial")
            if self._active:
                raise LampError("Finish or cancel the current action first")
            self._ledger.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,NULL)", (idempotency_key, self._session, digest))
        # A transport failure leaves a durable pending entry. Only this session
        # may retry the exact key/payload; a new session must reconcile it.
        action = self._request("POST", "/actions", payload)["action"]
        identifier = action["action_id"]
        with self._ledger:
            self._ledger.execute("UPDATE requests SET action=? WHERE key=?", (identifier, idempotency_key))
        self._active = identifier if action.get("state") not in TERMINAL else None
        return action

    def action(self, identifier):
        action = self._request("GET", f"/actions/{quote(identifier, safe='')}")["action"]
        if action.get("action_id") != identifier or action.get("expired") is True:
            raise LampError("Action missing, mismatched, or expired")
        if action.get("state") in TERMINAL and self._active == identifier:
            self._active = None
        return action

    def cancel(self, identifier):
        try:
            result = self._request("POST", f"/actions/{quote(identifier, safe='')}/cancel", {})["action"]
        except Exception:
            # Execution can finish between the status read and cancel request;
            # the SDK rejects cancellation of an already-terminal action.
            result = self.action(identifier)
        if result.get("action_id") != identifier or result.get("state") not in TERMINAL:
            raise LampError("Cancellation has not reached a terminal state")
        if self._active == identifier:
            self._active = None
        # Never use system.stop here: it releases torque on this runtime.
        return result

    def wait(self, identifier, *, timeout=90.0, on_update=None):
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 660:
            raise ValueError("Invalid completion deadline")
        deadline = self.clock() + timeout
        terminal = False
        try:
            while True:
                action = self.action(identifier)
                terminal = action.get("state") in TERMINAL
                if on_update:
                    on_update(self.clock(), action)
                state = action.get("state")
                if state == "succeeded":
                    result = action.get("result", {})
                    if result.get("completed") is not True or result.get("collision_checked") is not True:
                        raise LampError("Success lacks a checked execution result")
                    return action
                if state in TERMINAL:
                    raise LampError(f"Motion ended with state {state}")
                if state not in ("accepted", "running"):
                    raise LampError("Unknown action state")
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError("Motion completion deadline exceeded")
                self.sleep(min(0.1, remaining))
        except BaseException as error:
            # Preserve the original fault; explicitly report uncertainty if
            # even cancellation cannot be delivered. No automatic idle start.
            if not terminal:
                try:
                    self.cancel(identifier)
                except Exception:
                    raise LampError("Action failed and cancellation could not be confirmed; inspect runtime and hold") from error
            raise
