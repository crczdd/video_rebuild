from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DingtalkSettings:
    app_key: str
    app_secret: str
    base_id: str
    operator_id: str
    infringement_sheet: str = ""
    infringement_view: str = ""
    exaggeration_sheet: str = ""
    exaggeration_view: str = ""
    fallback_sheet: str = ""
    video_remake_sheet: str = ""
    video_remake_view: str = ""
    base_url: str = "https://api.dingtalk.com"

    @classmethod
    def from_env(cls, env_path: str | Path | None = ".env") -> "DingtalkSettings":
        file_values = _read_env_file(Path(env_path)) if env_path else {}

        def value(name: str, default: str = "") -> str:
            return os.getenv(name, file_values.get(name, default))

        return cls(
            app_key=value("DIPR_DINGTALK_APP_KEY"),
            app_secret=value("DIPR_DINGTALK_APP_SECRET"),
            base_id=value("DIPR_DINGTALK_BASE_ID"),
            operator_id=value("DIPR_DINGTALK_OPERATOR_ID"),
            infringement_sheet=value("DIPR_DINGTALK_INFRINGEMENT_SHEET_ID_OR_NAME"),
            infringement_view=value("DIPR_DINGTALK_INFRINGEMENT_VIEW_ID"),
            exaggeration_sheet=value("DIPR_DINGTALK_EXAGGERATION_SHEET_ID_OR_NAME"),
            exaggeration_view=value("DIPR_DINGTALK_EXAGGERATION_VIEW_ID"),
            fallback_sheet=value("DIPR_DINGTALK_SHEET_ID_OR_NAME"),
            video_remake_sheet=value("VIDEO_REMAKE_DINGTALK_SHEET_ID_OR_NAME"),
            video_remake_view=value("VIDEO_REMAKE_DINGTALK_VIEW_ID"),
            base_url=value(
                "DIPR_DINGTALK_BASE_URL", "https://api.dingtalk.com"
            ),
        )

    def target(self, workflow: str) -> tuple[str, str]:
        if workflow == "infringement":
            return self.infringement_sheet or self.fallback_sheet, self.infringement_view
        if workflow == "exaggeration":
            return self.exaggeration_sheet or self.fallback_sheet, self.exaggeration_view
        if workflow == "video_remake":
            return self.video_remake_sheet or self.fallback_sheet, self.video_remake_view
        return self.fallback_sheet, ""

    def validate(self, workflow: str) -> None:
        sheet, _ = self.target(workflow)
        missing = [
            name
            for name, value in (
                ("DIPR_DINGTALK_APP_KEY", self.app_key),
                ("DIPR_DINGTALK_APP_SECRET", self.app_secret),
                ("DIPR_DINGTALK_BASE_ID", self.base_id),
                ("DIPR_DINGTALK_OPERATOR_ID", self.operator_id),
                (f"{workflow} sheet", sheet),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing DingTalk settings: " + ", ".join(missing))


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return values
