from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError

from .job_store import JobStore
from .llm_client import LLMClient
from .settings import VideoRemakeSettings
from .webhook_models import APIResponse, GenerateRequest
from .webhook_service import WebhookError, WebhookService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    *,
    settings: VideoRemakeSettings | None = None,
    service: WebhookService | None = None,
    store: JobStore | None = None,
) -> FastAPI:
    settings = settings or VideoRemakeSettings.from_env(PROJECT_ROOT / ".env")
    if service is None:
        settings.validate_webhook()
        store = store or JobStore(
            settings.database_path,
            processing_timeout_seconds=settings.processing_timeout_seconds,
        )
        service = WebhookService(
            LLMClient(settings), store, max_concurrency=settings.llm_max_concurrency
        )
    elif store is None:
        store = service.store

    app = FastAPI(
        title="AI 对标视频复刻 Webhook",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {settings.webhook_auth_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise WebhookError(40101, "Webhook鉴权失败", 401)

    async def parse_generate_payload(request: Request) -> GenerateRequest:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        try:
            if content_type == "application/x-www-form-urlencoded":
                text = (await request.body()).decode("utf-8")
                raw: object = dict(parse_qsl(text, keep_blank_values=True))
            elif content_type in {"", "application/json"}:
                raw = await request.json()
            else:
                raise WebhookError(
                    41500,
                    "请求Content-Type仅支持application/json或application/x-www-form-urlencoded",
                    415,
                )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookError(42200, "请求内容格式错误：JSON decode error", 422) from exc

        try:
            return GenerateRequest.model_validate(raw)
        except ValidationError as exc:
            errors = [item.get("msg", "字段格式错误") for item in exc.errors()]
            raise WebhookError(42200, "请求字段格式错误：" + "；".join(errors), 422) from exc

    @app.exception_handler(WebhookError)
    async def webhook_error_handler(_: Request, exc: WebhookError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [item.get("msg", "字段格式错误") for item in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"code": 42200, "message": "请求JSON格式错误：" + "；".join(errors), "data": None},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"code": 50000, "message": "服务器内部错误", "data": None},
        )

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict:
        return {"status": "ready"}

    @app.post(
        "/api/v1/video-remake/generate",
        response_model=APIResponse,
        dependencies=[Depends(authenticate)],
    )
    def generate(payload: GenerateRequest = Depends(parse_generate_payload)) -> APIResponse:
        data = service.generate(payload)
        return APIResponse(code=0, message="success", data=data)

    @app.post(
        "/api/v1/video-remake/generate-text",
    )
    async def generate_text(request: Request) -> PlainTextResponse:
        """纯文本端点：成功直接返回 final_prompt 正文，无 JSON 外壳。
        所有失败（鉴权/解析/业务）均返回对应 HTTP 状态码 + 纯文本错误信息。
        钉钉侧用「HTTP状态码 == 200」做条件分支。"""
        try:
            authenticate(request.headers.get("authorization"))
            payload = await parse_generate_payload(request)
            data = service.generate(payload)
        except WebhookError as exc:
            return PlainTextResponse(content=exc.message, status_code=exc.http_status)
        return PlainTextResponse(content=data.final_prompt, status_code=200)

    @app.get("/api/status", dependencies=[Depends(authenticate)])
    def status() -> dict:
        return store.summary()

    @app.post(
        "/api/v1/video-remake/admin/reset-stale",
        dependencies=[Depends(authenticate)],
    )
    def reset_stale() -> dict:
        count = store.reset_stale()
        return {"code": 0, "message": "success", "data": {"reset": count}}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/styles.css", include_in_schema=False)
    def styles() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css", headers={"Cache-Control": "no-store"})

    @app.get("/app.js", include_in_schema=False)
    def script() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    return app
