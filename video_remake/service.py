from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any, Protocol

from . import fields as f
from .models import VideoRemakeTask

logger = logging.getLogger(__name__)


class TableClient(Protocol):
    def list_fields(self) -> list[Any]: ...
    def list_records(self, *, page_size: int, max_pages: int) -> list[dict[str, Any]]: ...
    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...


class PromptGenerator(Protocol):
    def generate_final_prompt(self, task: VideoRemakeTask) -> str: ...


@dataclass(slots=True)
class CycleResult:
    dry_run: bool = False
    dingtalk_read_success: bool = False
    fetched: int = 0
    eligible: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    llm_success: int = 0
    llm_failed: int = 0
    dingtalk_update_success: int = 0
    dingtalk_update_failed: int = 0
    failure_details: list[str] = field(default_factory=list)


def validate_table_fields(client: TableClient) -> None:
    available = {
        str(getattr(item, "field_name", "") or (item.get("field_name") if isinstance(item, dict) else ""))
        for item in _call_dingtalk(client.list_fields)
    }
    missing = [name for name in f.REQUIRED_FIELDS if name not in available]
    if missing:
        raise ValueError("DingTalk table is missing required fields: " + ", ".join(missing))


def run_cycle(
    client: TableClient,
    llm: PromptGenerator | None,
    *,
    dry_run: bool = False,
    validate_fields: bool = True,
) -> CycleResult:
    logger.info("cycle started")
    if validate_fields:
        validate_table_fields(client)
    records = _call_dingtalk(client.list_records, page_size=100, max_pages=100)
    result = CycleResult(
        dry_run=dry_run,
        dingtalk_read_success=True,
        fetched=len(records),
    )
    logger.info("records fetched: %d", result.fetched)

    for record in records:
        task = VideoRemakeTask.from_record(record)
        if not task.is_eligible():
            result.skipped += 1
            continue
        result.eligible += 1
        if dry_run:
            logger.info("dry-run eligible record: recordId=%s video=%s", task.record_id, task.video_name)
            continue
        if not task.record_id:
            result.failed += 1
            result.failure_details.append("数据校验失败：记录缺少 recordId")
            continue

        try:
            if llm is None:
                raise RuntimeError("非 dry-run 模式缺少 LLM 客户端")
            final_prompt = llm.generate_final_prompt(task).strip()
            if not final_prompt:
                raise ValueError("LLM 返回了空内容")
            result.llm_success += 1
        except Exception as exc:
            result.failed += 1
            result.llm_failed += 1
            detail = _record_failure(task, "LLM调用失败", exc)
            result.failure_details.append(detail)
            logger.exception("LLM failed: recordId=%s video=%s", task.record_id, task.video_name)
            continue

        try:
            _call_dingtalk(
                client.update_record,
                task.record_id,
                {f.FINAL_PROMPT: final_prompt},
            )
            result.success += 1
            result.dingtalk_update_success += 1
            logger.info("record succeeded: recordId=%s video=%s", task.record_id, task.video_name)
        except Exception as exc:
            result.failed += 1
            result.dingtalk_update_failed += 1
            detail = _record_failure(task, "钉钉回写失败", exc)
            result.failure_details.append(detail)
            logger.exception("DingTalk update failed: recordId=%s video=%s", task.record_id, task.video_name)

    logger.info("eligible records: %d", result.eligible)
    logger.info(
        "success count: %d; skip count: %d; failure count: %d",
        result.success, result.skipped, result.failed,
    )
    logger.info("cycle finished")
    return result


def safe_error_message(exc: Exception) -> str:
    text = " ".join(str(exc).split()) or type(exc).__name__
    text = re.sub(
        r"(?i)(api[_-]?key|authorization|bearer|appsecret|access[_-]?token)\s*[:=]\s*\S+",
        r"\1=[已隐藏]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[API Key 已隐藏]", text)
    return f"{type(exc).__name__}: {text}"[:600]


def _record_failure(task: VideoRemakeTask, stage: str, exc: Exception) -> str:
    return (
        f"recordId={task.record_id}，视频={task.video_name or '未命名'}，"
        f"{stage}：{safe_error_message(exc)}"
    )


def _call_dingtalk(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Retry only timeouts, connection failures, HTTP 429 and 5xx errors."""
    for attempt in range(1, 4):
        try:
            return call(*args, **kwargs)
        except Exception as exc:
            if attempt >= 3 or not _is_transient_dingtalk_error(exc):
                raise
            time.sleep(float(2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


def _is_transient_dingtalk_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        status = int(code)
    except (TypeError, ValueError):
        status = 0
    if status == 429 or status >= 500:
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "connection" in name
