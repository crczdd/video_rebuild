from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dingtalk.settings import _read_env_file


@dataclass(slots=True)
class VideoRemakeSettings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_api_mode: str = "chat_completions"
    poll_interval_seconds: int = 600

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "VideoRemakeSettings":
        values = _read_env_file(Path(env_path))

        def value(name: str, default: str = "") -> str:
            return os.getenv(name, values.get(name, default)).strip()

        raw_interval = value("VIDEO_REMAKE_POLL_INTERVAL_SECONDS", "600")
        try:
            interval = int(raw_interval)
        except ValueError as exc:
            raise ValueError("VIDEO_REMAKE_POLL_INTERVAL_SECONDS must be an integer") from exc
        if interval <= 0:
            raise ValueError("VIDEO_REMAKE_POLL_INTERVAL_SECONDS must be greater than zero")
        return cls(
            llm_api_key=value("LLM_API_KEY"),
            llm_base_url=value("LLM_BASE_URL"),
            llm_model=value("LLM_MODEL"),
            llm_api_mode=value("LLM_API_MODE", "chat_completions"),
            poll_interval_seconds=interval,
        )

    def validate_llm(self) -> None:
        missing = [
            name for name, current in (
                ("LLM_API_KEY", self.llm_api_key),
                ("LLM_BASE_URL", self.llm_base_url),
                ("LLM_MODEL", self.llm_model),
            ) if not current
        ]
        if missing:
            raise ValueError("Missing LLM settings: " + ", ".join(missing))
        if self.llm_api_mode != "chat_completions":
            raise ValueError("Only LLM_API_MODE=chat_completions is currently supported")
