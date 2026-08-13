from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import threading
import webbrowser

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from .scheduler import PROJECT_ROOT, SchedulerManager
from .settings import VideoRemakeSettings

STATIC_DIR = Path(__file__).resolve().parent / "static"


class IntervalRequest(BaseModel):
    interval_seconds: int = Field(ge=10, le=86400)


class StartRequest(BaseModel):
    run_immediately: bool = False


class RunRequest(BaseModel):
    dry_run: bool = False


def create_app(manager: SchedulerManager | None = None) -> FastAPI:
    owned_manager = manager is None
    scheduler = manager or SchedulerManager(
        default_interval=VideoRemakeSettings.from_env(PROJECT_ROOT / ".env").poll_interval_seconds
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owned_manager:
            scheduler.shutdown()

    app = FastAPI(title="AI 对标视频复刻控制台", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/styles.css", include_in_schema=False)
    def styles() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "styles.css",
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/app.js", include_in_schema=False)
    def script() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "app.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/status")
    def get_status() -> dict:
        return scheduler.status()

    @app.put("/api/settings")
    def update_settings(payload: IntervalRequest) -> dict:
        try:
            return scheduler.set_interval(payload.interval_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/start")
    def start(payload: StartRequest) -> dict:
        return scheduler.start(run_immediately=payload.run_immediately)

    @app.post("/api/stop")
    def stop() -> dict:
        return scheduler.stop()

    @app.post("/api/run")
    def run(payload: RunRequest) -> dict:
        try:
            return scheduler.run_now(dry_run=payload.dry_run)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 对标视频复刻 Web 控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.open_browser:
        threading.Timer(
            1.0,
            lambda: webbrowser.open(f"http://127.0.0.1:{args.port}"),
        ).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
