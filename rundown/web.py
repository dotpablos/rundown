from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import RLock
from contextlib import ExitStack
import os
import sqlite3

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from filelock import FileLock, Timeout
from pydantic import ValidationError

from .config import Config, needs_setup, resolve_paths, save_config, token_setting
from .engine import Busy, Engine


def create_app(config=None, engine=None, config_path="config.toml"):
    engine = engine or Engine(config)
    app = FastAPI(title="Rundown", docs_url=None, redoc_url=None)
    app.state.engine = engine
    settings_path = Path(config_path).expanduser().resolve()
    settings_guard = RLock()
    app.state.token_setting = token_setting(settings_path, engine.config)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    def current():
        return app.state.engine

    def settings_response():
        cfg = current().config
        data = cfg.model_dump(mode="json")
        data["slack"]["token"] = ""
        return {"config": data, "setup_required": needs_setup(cfg), "token_configured": bool(cfg.slack.token.get_secret_value()), "busy": current().is_busy()}

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never echo request input: settings requests can contain credentials.
        return JSONResponse({"detail": "Invalid request. Check the field types and try again."}, status_code=422)

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if request.headers.get("x-rundown-request") != "1" or (origin and origin != expected):
                return JSONResponse({"detail": "Request must come from the local Rundown page"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    def status(check: bool = False):
        engine = current()
        result = {"busy": engine.is_busy(), "latest": engine.store.latest(), "provider_name": engine.config.ai.provider, "timezone": engine.config.storage.timezone, "setup_required": needs_setup(engine.config)}
        if check:
            result["readiness"] = engine.check()
        return result

    @app.get("/api/config")
    def get_config():
        with settings_guard:
            return settings_response()

    @app.post("/api/config")
    def set_config(payload: dict):
        with settings_guard:
            old = current()
            data = old.config.model_dump(mode="json")
            try:
                for section, values in payload.items():
                    if section not in data or not isinstance(values, dict):
                        raise ValueError("Unknown settings section or invalid section format")
                    if section == "keywords":
                        data[section] = values
                    else:
                        data[section].update(values)
                supplied = payload.get("slack", {}).get("token")
                if supplied is not None and not isinstance(supplied, str):
                    raise ValueError("Slack token must be text")
                saved_token = supplied.strip() if supplied and supplied.strip() else app.state.token_setting
                data["slack"]["token"] = os.environ.get(saved_token[4:], "") if saved_token.startswith("env:") else saved_token
                cfg = resolve_paths(Config.model_validate(data), settings_path)
                if needs_setup(cfg):
                    raise ValueError("Add a Slack user token (xoxp-...) and complete the selected AI provider settings")
                if cfg.storage.database.resolve() == settings_path:
                    raise ValueError("The history database and configuration must use different files")
            except ValidationError as exc:
                details = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False, include_context=False, include_url=False)]
                raise HTTPException(422, " · ".join(details)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            # Same lock as browser/CLI runs. Never swap configuration mid-run.
            paths = sorted({old.lock_path, str(cfg.storage.database) + ".lock"})
            try:
                with ExitStack() as stack:
                    for path in paths:
                        Path(path).parent.mkdir(parents=True, exist_ok=True)
                        stack.enter_context(FileLock(path, timeout=0))
                    replacement = Engine(cfg)
                    save_config(settings_path, cfg, saved_token)
                    app.state.engine = replacement
                    app.state.token_setting = saved_token
            except Timeout:
                raise HTTPException(409, "A digest is running. Wait for it to finish before saving settings.") from None
            except (OSError, sqlite3.Error):
                raise HTTPException(422, "Could not save settings. Check the file and folder paths and permissions.") from None
            return settings_response()

    @app.get("/api/dates")
    def dates():
        return current().store.dates()

    @app.get("/api/digests")
    def digests(date: date):
        return current().store.by_date(date.isoformat())

    @app.post("/api/runs", status_code=202)
    def run(background: BackgroundTasks):
        with settings_guard:
            engine = current()
            if needs_setup(engine.config):
                raise HTTPException(409, "Complete setup before running a digest")
            try:
                run_id = engine.begin()
            except Busy as exc:
                raise HTTPException(409, str(exc)) from None
        background.add_task(engine.execute, run_id)
        return {"id": run_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = current().store.run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        return run

    return app
