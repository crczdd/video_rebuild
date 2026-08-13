from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable

from dingtalk.factory import make_client
from dingtalk.settings import DingtalkSettings

from .llm_client import LLMClient
from .service import CycleResult, run_cycle, safe_error_message
from .settings import VideoRemakeSettings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = PROJECT_ROOT / ".video_remake_web.json"
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 86400


def execute_workflow(
    dry_run: bool, env_path: str | Path = PROJECT_ROOT / ".env"
) -> CycleResult:
    settings = VideoRemakeSettings.from_env(env_path)
    try:
        llm = None if dry_run else LLMClient(settings)
    except Exception as exc:
        raise RuntimeError(f"LLM初始化失败：{safe_error_message(exc)}") from exc
    dingtalk_settings = DingtalkSettings.from_env(env_path)
    try:
        with make_client("video_remake", settings=dingtalk_settings) as client:
            return run_cycle(client, llm, dry_run=dry_run)
    except Exception as exc:
        raise RuntimeError(f"钉钉读取失败：{safe_error_message(exc)}") from exc


class SchedulerManager:
    """Single-process, non-overlapping scheduler used by the local web UI."""

    def __init__(
        self,
        *,
        execute: Callable[[bool], CycleResult] = execute_workflow,
        default_interval: int = 600,
        state_path: Path = DEFAULT_STATE_PATH,
    ) -> None:
        self._execute = execute
        self._state_path = state_path
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._enabled = False
        self._running = False
        self._run_mode = ""
        self._interval = self._load_interval(default_interval)
        self._next_run_at: float | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._events: deque[str] = deque(maxlen=200)
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="video-remake-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        self._event("Web 控制台已就绪，定时任务当前未启动")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "running": self._running,
                "run_mode": self._run_mode,
                "interval_seconds": self._interval,
                "next_run_at": _iso_from_timestamp(self._next_run_at),
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "last_result": self._last_result,
                "events": list(self._events),
            }

    def set_interval(self, interval_seconds: int) -> dict[str, Any]:
        if not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
            raise ValueError(
                f"轮询间隔必须在 {MIN_INTERVAL_SECONDS} 到 {MAX_INTERVAL_SECONDS} 秒之间"
            )
        with self._lock:
            self._interval = interval_seconds
            if self._enabled and not self._running:
                self._next_run_at = time.time() + interval_seconds
            self._save_interval()
            self._event(f"定时间隔已设置为 {interval_seconds} 秒")
            self._wake.set()
            return self.status()

    def start(self, *, run_immediately: bool = False) -> dict[str, Any]:
        with self._lock:
            self._enabled = True
            if not self._running:
                self._next_run_at = time.time() if run_immediately else time.time() + self._interval
            self._event(
                "定时任务已启动，将立即执行" if run_immediately else "定时任务已启动"
            )
            self._wake.set()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._enabled = False
            self._next_run_at = None
            message = "定时任务已停止"
            if self._running:
                message += "；当前正在执行的一轮会安全完成"
            self._event(message)
            self._wake.set()
            return self.status()

    def run_now(self, *, dry_run: bool) -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise RuntimeError("已有任务正在执行，请等待本轮完成")
            self._launch_locked(dry_run=dry_run)
            return self.status()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._wake.set()
        self._scheduler_thread.join(timeout=2)

    def _scheduler_loop(self) -> None:
        while not self._shutdown.is_set():
            should_run = False
            with self._lock:
                should_run = bool(
                    self._enabled
                    and not self._running
                    and self._next_run_at is not None
                    and self._next_run_at <= time.time()
                )
                if should_run:
                    self._launch_locked(dry_run=False)
            self._wake.wait(timeout=0.5)
            self._wake.clear()

    def _launch_locked(self, *, dry_run: bool) -> None:
        self._running = True
        self._run_mode = "dry-run" if dry_run else "正式执行"
        self._next_run_at = None
        self._last_started_at = _now_iso()
        self._last_error = None
        self._last_result = None
        self._event(f"开始{self._run_mode}")
        threading.Thread(
            target=self._execute_once,
            args=(dry_run,),
            name="video-remake-cycle",
            daemon=True,
        ).start()

    def _execute_once(self, dry_run: bool) -> None:
        try:
            result = self._execute(dry_run)
            with self._lock:
                self._last_result = asdict(result)
                self._event(f"钉钉读取成功：共读取 {result.fetched} 条记录")
                if result.dry_run:
                    self._event("安全检查模式：未调用 LLM，未回写钉钉")
                else:
                    self._event(
                        f"LLM调用结果：成功 {result.llm_success}，失败 {result.llm_failed}"
                    )
                    self._event(
                        "钉钉回写结果：成功 "
                        f"{result.dingtalk_update_success}，失败 {result.dingtalk_update_failed}"
                    )
                for detail in result.failure_details:
                    self._event(f"失败原因：{detail}")
                self._event(
                    "执行完成：读取 {fetched}，符合 {eligible}，成功 {success}，"
                    "跳过 {skipped}，失败 {failed}".format(**self._last_result)
                )
        except Exception as exc:
            logger.exception("scheduled cycle failed")
            with self._lock:
                self._last_error = safe_error_message(exc)
                self._event(f"执行失败：{self._last_error}")
        finally:
            with self._lock:
                self._running = False
                self._run_mode = ""
                self._last_finished_at = _now_iso()
                if self._enabled:
                    self._next_run_at = time.time() + self._interval
                self._wake.set()

    def _event(self, message: str) -> None:
        self._events.append(f"{datetime.now().astimezone().strftime('%H:%M:%S')}  {message}")

    def _load_interval(self, default: int) -> int:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            interval = int(payload.get("interval_seconds", default))
            if MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
                return interval
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, default))

    def _save_interval(self) -> None:
        self._state_path.write_text(
            json.dumps({"interval_seconds": self._interval}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_from_timestamp(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None
