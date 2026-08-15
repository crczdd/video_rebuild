from __future__ import annotations

import hashlib
import json
import threading
import time

from . import fields as f
from .job_store import JobStore
from .llm_client import LLMClient
from .models import VideoRemakeTask
from .service import safe_error_message
from .webhook_models import GenerateData, GenerateRequest


class WebhookError(RuntimeError):
    def __init__(self, code: int, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class WebhookService:
    def __init__(self, llm: LLMClient, store: JobStore, max_concurrency: int = 2) -> None:
        self.llm = llm
        self.store = store
        self._capacity = threading.BoundedSemaphore(max_concurrency)

    def generate(self, incoming: GenerateRequest) -> GenerateData:
        request = incoming.stripped()
        task = _to_task(request)
        _validate(task)

        request_key = _request_key(request)
        request_id = request.request_id or request_key[:24]
        created, existing = self.store.begin(
            request_key, request_id, request.record_id, request.video_name
        )
        if not created and existing:
            if existing.status == "success":
                return GenerateData(
                    request_id=existing.request_id,
                    record_id=existing.record_id,
                    final_prompt=existing.final_prompt,
                    cached=True,
                )
            if existing.status == "processing":
                age = _processing_age_seconds(existing)
                timeout = self.store.processing_timeout_seconds
                message = (
                    f"相同请求正在处理中（已耗时{int(age)}秒，超时阈值{int(timeout)}秒），"
                    f"请等待{max(5, int(timeout - age))}秒后重试"
                )
                raise WebhookError(40901, message, 409)

        started = time.monotonic()
        if not self._capacity.acquire(blocking=False):
            self.store.fail(request_key, "服务器处理繁忙", 0)
            raise WebhookError(42901, "服务器处理繁忙，请稍后重试", 429)
        try:
            try:
                final_prompt = self.llm.generate_final_prompt(task).strip()
                if not final_prompt:
                    raise ValueError("LLM 返回了空内容")
            except Exception as exc:
                message = safe_error_message(exc)
                self.store.fail(request_key, message, _duration(started))
                raise WebhookError(50201, f"LLM调用失败：{message}", 502) from exc

            duration = _duration(started)
            self.store.succeed(request_key, final_prompt, duration)
            return GenerateData(
                request_id=request_id,
                record_id=request.record_id,
                final_prompt=final_prompt,
                cached=False,
            )
        finally:
            self._capacity.release()


def _to_task(request: GenerateRequest) -> VideoRemakeTask:
    return VideoRemakeTask(
        record_id=request.record_id,
        values={
            f.VIDEO_NAME: request.video_name,
            f.VIDEO_URL: request.video_url,
            f.NANOPHOTO_PROMPT: request.nanophoto_prompt,
            f.DIALOGUE_CHANGE: request.dialogue_change,
            f.PRODUCT_CHANGE: request.product_change,
            f.CHARACTER_CHANGE: request.character_change,
            f.BACKGROUND_CHANGE: request.background_change,
            f.PAIN_POINT_CHANGE: request.pain_point_change,
            f.SPECIAL_SHOT: request.special_shot,
            f.FINAL_ADVICE: request.final_advice,
        },
    )


def _validate(task: VideoRemakeTask) -> None:
    missing = [name for name in f.BASE_FIELDS if not task.get(name)]
    if missing:
        raise WebhookError(42201, "缺少必填字段：" + "、".join(missing), 422)
    if not task.non_empty_changes():
        raise WebhookError(42202, "至少填写一项修改字段或修改最终建议", 422)


def _request_key(request: GenerateRequest) -> str:
    if request.request_id:
        source = f"request:{request.request_id}"
    else:
        source = json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _duration(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _processing_age_seconds(job) -> float:
    from datetime import datetime, timezone
    try:
        updated = datetime.fromisoformat(job.updated_at.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
