from __future__ import annotations

from typing import Any


def attachment_value(resource_id: str) -> list[dict[str, str]]:
    """Build a value accepted by ``DingtalkBitableClient.create_record``.

    The client expands the resource id to the complete attachment metadata
    cached by ``upload_file``.
    """
    return [{"file_token": resource_id}]


def extract_attachments(field_value: Any) -> list[dict[str, str]]:
    """Normalize attachment cells returned by DingTalk AI Table."""
    if not isinstance(field_value, list):
        return []
    result: list[dict[str, str]] = []
    for item in field_value:
        if not isinstance(item, dict):
            continue
        resource_id = str(item.get("resourceId") or item.get("resource_id") or "")
        if not resource_id:
            continue
        result.append(
            {
                "resource_id": resource_id,
                "resource_url": str(item.get("resourceUrl") or item.get("url") or ""),
                "name": str(item.get("filename") or item.get("fileName") or item.get("name") or ""),
                "size": str(item.get("size") or item.get("fileSize") or ""),
                "mime_type": str(item.get("type") or item.get("mediaType") or ""),
            }
        )
    return result


def text_value(field_value: Any) -> str:
    if field_value is None:
        return ""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, dict):
        return str(
            field_value.get("link")
            or field_value.get("url")
            or field_value.get("text")
            or field_value.get("name")
            or ""
        )
    if isinstance(field_value, list):
        return "".join(text_value(item) for item in field_value)
    return str(field_value)
