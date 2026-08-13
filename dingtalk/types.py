from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TableAPIError(RuntimeError):
    """Base error carrying the provider response for diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


@dataclass(slots=True)
class FieldInfo:
    field_id: str
    field_name: str
    field_type: int
    ui_type: str | None = None
    description: str | None = None
    is_primary: bool | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class TableInfo:
    table_id: str
    name: str
    revision: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class UploadedFile:
    file_token: str
    url: str | None = None
    raw: dict[str, Any] | None = None
