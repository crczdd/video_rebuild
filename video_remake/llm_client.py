from __future__ import annotations

import time
from typing import Any, Callable

from openai import OpenAI

from .models import VideoRemakeTask
from .prompt_builder import SYSTEM_PROMPT, build_user_prompt
from .settings import VideoRemakeSettings


class EmptyLLMResponseError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        settings: VideoRemakeSettings,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        settings.validate_llm()
        self.model = settings.llm_model
        self.total_timeout_seconds = settings.llm_timeout_seconds
        self.client = client or OpenAI(
            api_key=settings.llm_api_key,
            base_url=normalize_base_url(settings.llm_base_url),
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        self.sleep = sleep
        self.max_attempts = max_attempts

    def generate_final_prompt(self, task: VideoRemakeTask) -> str:
        deadline = time.monotonic() + self.total_timeout_seconds
        for attempt in range(1, self.max_attempts + 1):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("LLM总处理时间超过限制")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(task)},
                    ],
                    timeout=remaining,
                )
                content = response.choices[0].message.content
                result = content.strip() if isinstance(content, str) else ""
                if not result:
                    raise EmptyLLMResponseError("LLM returned empty content")
                return result
            except EmptyLLMResponseError:
                raise
            except Exception as exc:
                if attempt >= self.max_attempts or not _is_retryable(exc):
                    raise
                delay = float(2 ** (attempt - 1))
                if time.monotonic() + delay >= deadline:
                    raise TimeoutError("LLM总处理时间超过限制") from exc
                self.sleep(delay)
        raise RuntimeError("unreachable")


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429 or (isinstance(status, int) and status >= 500):
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "connection" in name or "ratelimit" in name


def normalize_base_url(base_url: str) -> str:
    """Accept either a provider base URL or an accidentally pasted endpoint URL."""
    normalized = base_url.strip().rstrip("/")
    suffix = "/chat/completions"
    if normalized.lower().endswith(suffix):
        normalized = normalized[: -len(suffix)].rstrip("/")
    return normalized
