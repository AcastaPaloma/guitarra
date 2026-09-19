"""Loopback-only web API. Credentials stay server-side; all execution is fake-only."""
from __future__ import annotations

import hmac
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent.backends.baseten import BasetenBackend
from model.baseten import DEFAULT_MODEL, load_env
from orchestration.rig import FakeRig
from orchestration.scenarios import SCENARIOS, Scenario
from .manager import RunManager

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "static"


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    string: int = Field(ge=1, le=6)
    fret: int = Field(ge=0, le=24)


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario: Literal["single-note", "repeat-and-change", "unsupported-target", "fret-failure", "custom"] = "repeat-and-change"
    prompt: str = Field(default="", max_length=8000)
    notes: list[Note] = Field(default_factory=list, max_length=12)
    inject_fret_failure: bool = False
    allow_inference: bool = False
    effort: Literal["low", "high", "max"] = "high"
    max_calls: int = Field(default=20, ge=1, le=40)
    seconds: int = Field(default=180, ge=10, le=600)
    max_output_tokens: int = Field(default=4096, ge=512, le=8192)

    @model_validator(mode="after")
    def check_task(self):
        if not self.allow_inference:
            raise ValueError("Explicit approval to consume Baseten credits is required")
        if self.scenario == "custom" and not self.notes:
            raise ValueError("Custom goals need an expected note sequence for independent grading")
        if self.scenario != "custom" and (self.notes or self.inject_fret_failure):
            raise ValueError("Preset notes/faults are fixed; select custom to change them")
        return self


def create_app(*, root: Path | None = None, port: int = 8787,
               backend_factory=BasetenBackend, key_ready=None, request_interval: float = 6) -> FastAPI:
    load_env()
    key_ready = key_ready or (lambda: bool(os.environ.get("BASETEN_API_KEY") or os.environ.get("BASETEN")))
    manager = RunManager(root or ROOT / "runs" / "orchestration", backend_factory,
                         request_interval=request_interval)
    token = secrets.token_urlsafe(32)  # local CSRF token, NOT the Baseten credential
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    rig = FakeRig()
    try:
        capabilities, tools, targets = rig.capabilities(), rig.tool_specs, rig.targets
    finally:
        rig.close()

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.shutdown()

    app = FastAPI(title="Guitarra operator console", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Loopback binding + Host checks protect against LAN access and DNS rebinding.
        # Origin/custom-header checks prevent another website from spending credits.
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "Cross-origin access is not allowed"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            supplied = request.headers.get("x-session-token", "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse({"detail": "Reload the local app to establish a session"}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                return JSONResponse({"detail": "JSON request required"}, status_code=415)
            size = request.headers.get("content-length", "")
            if not size.isdigit() or int(size) > 65536:
                return JSONResponse({"detail": "Request too large or length missing"}, status_code=413)
            if len(await request.body()) > 65536:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Don't echo arbitrary submitted values (a user might accidentally paste a key).
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
                                        for e in exc.errors()]}, status_code=422)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/assets/{filename}")
    def asset(filename: str):
        if filename not in {"app.js", "style.css"}:
            raise HTTPException(404, "Unknown asset")
        return FileResponse(STATIC / filename)

    @app.get("/api/bootstrap")
    def bootstrap():
        return {
            "session_token": token, "key_configured": key_ready(),
            "model": os.environ.get("BASETEN_MODEL") or DEFAULT_MODEL, "provider": "Baseten",
            "mode": "fake_only", "hardware_enabled": False,
            "log_root": str(manager.root), "request_interval_s": request_interval,
            "scenarios": [{"id": s.name, "task": s.task(), "expected_outcome": s.expected_outcome}
                          for s in SCENARIOS.values()],
            "capabilities": capabilities, "tools": tools,
            "hardware_blockers": [
                "The recorded 75 C gripper incident has no sustained thermal qualification.",
                "Latest operator-selected grip limit: 110. Code default: 180. Reconnection/protection handling needs review.",
                "Pick motion is a mock: no qualified pick map or coordinated physical scheduler is supplied.",
                "Independent stop/health monitoring and safe model-wait states still need commissioning.",
            ],
        }

    @app.get("/api/runs")
    def history():
        return manager.history()

    @app.post("/api/runs", status_code=202)
    def start(body: StartRun):
        if not key_ready():
            raise HTTPException(400, "Add BASETEN_API_KEY to .env and restart the server; never paste it into a prompt")
        if any(key and key in body.prompt for key in (os.environ.get("BASETEN_API_KEY"), os.environ.get("BASETEN"))):
            raise HTTPException(422, "Do not include credentials in a prompt")
        if body.scenario == "custom":
            notes = tuple((n.string, n.fret) for n in body.notes)
            unsupported = any(f not in targets.get(s, []) for s, f in notes)
            if unsupported and body.inject_fret_failure:
                raise HTTPException(422, "Fault injection requires a supported note sequence")
            scenario = Scenario("custom", notes, "blocked" if unsupported or body.inject_fret_failure else "completed",
                                fail_first_press=body.inject_fret_failure)
        else:
            scenario = SCENARIOS[body.scenario]
        settings = {k: getattr(body, k) for k in ("effort", "max_calls", "seconds", "max_output_tokens")}
        try:
            return manager.start(scenario, prompt=body.prompt, settings=settings)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return manager.get(run_id)
        except (OSError, ValueError):
            raise HTTPException(404, "Run not found or report unavailable") from None

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, after: int = Query(default=0, ge=0, le=10000)):
        try:
            return manager.events(run_id, after)
        except (OSError, ValueError):
            raise HTTPException(404, "Run events unavailable") from None

    @app.post("/api/runs/{run_id}/{action}")
    def control(run_id: str, action: Literal["pause", "resume", "stop"]):
        try:
            return manager.command(run_id, action)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/runs/{run_id}/files/{filename}")
    def file(run_id: str, filename: str):
        try:
            return FileResponse(manager.file(run_id, filename), filename=filename,
                                media_type="application/json" if filename.endswith(".json") else "application/x-ndjson")
        except (OSError, ValueError):
            raise HTTPException(404, "Log file unavailable") from None

    return app
