from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import fields as f


def is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        if not value:
            return False
        values = value.values() if isinstance(value, dict) else value
        return any(is_non_empty(item) for item in values)
    return True


def field_text(value: Any) -> str:
    """Extract readable text from DingTalk text/select/link cell shapes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(part for item in value if (part := field_text(item)))
    if isinstance(value, dict):
        preferred = (
            "text", "value", "name", "label", "displayValue", "title", "url", "link"
        )
        parts = [field_text(value[key]) for key in preferred if key in value]
        parts = [part for part in parts if part]
        if parts:
            return "\n".join(dict.fromkeys(parts))
        return "\n".join(
            part for item in value.values() if (part := field_text(item))
        )
    return str(value).strip()


@dataclass(slots=True)
class VideoRemakeTask:
    record_id: str
    values: dict[str, str]

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "VideoRemakeTask":
        raw_fields = record.get("fields")
        if not isinstance(raw_fields, dict):
            raw_fields = {}
        values = {name: field_text(raw_fields.get(name)) for name in f.INPUT_FIELDS}
        record_id = str(
            record.get("record_id") or record.get("recordId") or record.get("id") or ""
        ).strip()
        return cls(record_id=record_id, values=values)

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    @property
    def video_name(self) -> str:
        return self.get(f.VIDEO_NAME)

    def non_empty_changes(self) -> dict[str, str]:
        return {name: self.get(name) for name in f.CHANGE_FIELDS if self.get(name)}

    def is_eligible(self) -> bool:
        return (
            self.get(f.GPT_CONFIRMED) == "是"
            and all(self.get(name) for name in f.BASE_FIELDS)
            and bool(self.non_empty_changes())
            and not self.get(f.FINAL_PROMPT)
        )
