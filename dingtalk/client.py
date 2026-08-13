"""DingTalk AI table API client.

This standalone module exposes the record and attachment operations required
by an automation workflow.

Official docs used while implementing:
- https://open.dingtalk.com/document/development/api-notable-getallsheets
- https://open.dingtalk.com/document/development/api-noatable-getallfields
- https://open.dingtalk.com/document/development/api-notable-listrecords
- https://open.dingtalk.com/document/development/api-notable-insertrecords
- https://open.dingtalk.com/document/development/api-noatable-updaterecords
- https://open.dingtalk.com/document/development/api-noatable-updatesheet
- https://open.dingtalk.com/document/development/api-getresourceuploadinfo
- https://open.dingtalk.com/document/development/upload-attachment
"""

from __future__ import annotations

from io import BytesIO
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from PIL import Image

from .types import FieldInfo, TableAPIError, TableInfo, UploadedFile


class DingtalkAPIError(TableAPIError):
    """DingTalk API error with the original response attached as ``payload``."""


class DingtalkBitableClient:
    """DingTalk AI table client with a Feishu-compatible method surface."""

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        base_id: str,
        sheet_id_or_name: str,
        view_id: str = "",
        operator_id: str,
        base_url: str = "https://api.dingtalk.com",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        # Kept for backwards-compatible construction by older callers. The
        # official AI table attachment API does not use a DingDrive folder.
        upload_parent_dentry_uuid: str = "",
        upload_union_id: str = "",
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_id = base_id
        self.table_id = sheet_id_or_name
        self.sheet_id_or_name = sheet_id_or_name
        self.view_id = view_id
        self.operator_id = operator_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        del upload_parent_dentry_uuid, upload_union_id
        self._access_token: str | None = None
        self._client: httpx.Client | None = None
        self._attachment_resources: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> DingtalkBitableClient:
        self._client = httpx.Client(timeout=self.timeout, transport=self._transport)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._access_token = None

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, transport=self._transport)
        return self._client

    def _path_base(self, *, sheet_id_or_name: str | None = None) -> str:
        sheet = quote(sheet_id_or_name or self.sheet_id_or_name, safe="")
        base = quote(self.base_id, safe="")
        return f"{self.base_url}/v1.0/notable/bases/{base}/sheets/{sheet}"

    def _params(self) -> dict[str, str]:
        return {"operatorId": self.operator_id} if self.operator_id else {}

    def get_access_token(self, *, refresh: bool = False) -> str:
        if self._access_token and not refresh:
            return self._access_token
        response = self._ensure_client().post(
            f"{self.base_url}/v1.0/oauth2/accessToken",
            json={"appKey": self.app_key, "appSecret": self.app_secret},
        )
        payload = self._handle(response, action="获取 DingTalk accessToken")
        token = payload.get("accessToken") or payload.get("access_token")
        if not token:
            raise DingtalkAPIError("获取 DingTalk accessToken 失败: 响应中缺少 accessToken", payload=payload)
        self._access_token = str(token)
        return self._access_token

    # Existing diagnostics call this Feishu-named method. Keep it as an alias.
    def get_tenant_access_token(self, *, refresh: bool = False) -> str:
        return self.get_access_token(refresh=refresh)

    def _headers(self) -> dict[str, str]:
        return {
            "x-acs-dingtalk-access-token": self.get_access_token(),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _handle(self, response: httpx.Response, *, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise DingtalkAPIError(
                f"{action} 失败: HTTP {response.status_code} {response.reason_phrase}",
                code=response.status_code,
                payload=_safe_json(response),
            )
        payload = _safe_json(response)
        if not isinstance(payload, dict):
            raise DingtalkAPIError(f"{action} 失败: 响应不是 JSON", payload=payload)

        code = payload.get("code")
        errcode = payload.get("errcode")
        success = payload.get("success")
        if code not in (None, 0, "0"):
            raise DingtalkAPIError(
                f"{action} 失败: {payload.get('message') or payload.get('msg') or code}",
                code=code,
                payload=payload,
            )
        if errcode not in (None, 0, "0"):
            raise DingtalkAPIError(
                f"{action} 失败: {payload.get('errmsg') or errcode}",
                code=errcode,
                payload=payload,
            )
        if success is False:
            raise DingtalkAPIError(
                f"{action} 失败: {payload.get('message') or payload.get('msg') or 'success=false'}",
                payload=payload,
            )
        return payload

    def _value(self, payload: dict[str, Any]) -> Any:
        if "value" in payload:
            return payload["value"]
        if "data" in payload:
            data = payload["data"]
            if isinstance(data, dict) and "value" in data:
                return data["value"]
            return data
        if "result" in payload:
            result = payload["result"]
            if isinstance(result, dict) and "value" in result:
                return result["value"]
            return result
        return payload

    def list_tables(self) -> list[TableInfo]:
        url = f"{self.base_url}/v1.0/notable/bases/{quote(self.base_id, safe='')}/sheets"
        response = self._ensure_client().get(url, headers=self._headers(), params=self._params())
        payload = self._handle(response, action="列出 DingTalk AI 表格数据表")
        value = self._value(payload)
        items = value.get("items") if isinstance(value, dict) else value
        if items is None:
            items = []
        results: list[TableInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            table_id = str(item.get("id") or item.get("sheetId") or item.get("sheetIdOrName") or "")
            results.append(TableInfo(table_id=table_id, name=str(item.get("name") or table_id), raw=item))
        return results

    def list_fields(self, *, table_id: str | None = None) -> list[FieldInfo]:
        url = f"{self._path_base(sheet_id_or_name=table_id)}/fields"
        response = self._ensure_client().get(url, headers=self._headers(), params=self._params())
        payload = self._handle(response, action="列出 DingTalk AI 表格字段")
        value = self._value(payload)
        items = value.get("items") if isinstance(value, dict) else value
        if items is None:
            items = []
        return [_field_info(item) for item in items if isinstance(item, dict)]

    def list_records(
        self,
        *,
        page_size: int = 50,
        max_pages: int = 20,
        filter_: str | None = None,
        table_id: str | None = None,
        view_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del view_id
        url = f"{self._path_base(sheet_id_or_name=table_id)}/records/list"
        headers = self._headers()
        records: list[dict[str, Any]] = []
        next_token: str | None = None
        for _ in range(max(1, max_pages)):
            body: dict[str, Any] = {"maxResults": min(max(1, page_size), 100)}
            if filter_:
                body["filter"] = filter_
            if next_token:
                body["nextToken"] = next_token
            response = self._ensure_client().post(
                url,
                headers=headers,
                params=self._params(),
                json=body,
            )
            payload = self._handle(response, action="查询 DingTalk AI 表格记录")
            value = self._value(payload)
            items = value.get("records") if isinstance(value, dict) else value
            for item in items or []:
                if isinstance(item, dict):
                    self._remember_attachment_resources(item)
                    records.append(_record_info(item))
            if not isinstance(value, dict) or not value.get("hasMore"):
                break
            next_token = value.get("nextToken")
            if not next_token:
                break
        return records

    def create_record(
        self,
        fields: dict[str, Any],
        *,
        table_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._path_base(sheet_id_or_name=table_id)}/records"
        body = {"records": [{"fields": self._normalize_fields(fields)}]}
        response = self._ensure_client().post(
            url,
            headers=self._headers(),
            params=self._params(),
            json=body,
        )
        payload = self._handle(response, action="新增 DingTalk AI 表格记录")
        value = self._value(payload)
        items = value if isinstance(value, list) else value.get("records") if isinstance(value, dict) else []
        if isinstance(items, list) and items:
            self._remember_attachment_resources(items[0])
            return _record_info(items[0])
        if isinstance(value, dict):
            self._remember_attachment_resources(value)
            return _record_info(value)
        return {"fields": fields, "raw": payload}

    def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        *,
        table_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._path_base(sheet_id_or_name=table_id)}/records"
        body = {"records": [{"id": record_id, "fields": self._normalize_fields(fields)}]}
        response = self._ensure_client().put(
            url,
            headers=self._headers(),
            params=self._params(),
            json=body,
        )
        payload = self._handle(response, action="更新 DingTalk AI 表格记录")
        value = self._value(payload)
        items = value if isinstance(value, list) else value.get("records") if isinstance(value, dict) else []
        if isinstance(items, list) and items:
            self._remember_attachment_resources(items[0])
            return _record_info(items[0])
        if isinstance(value, dict):
            self._remember_attachment_resources(value)
        return {"record_id": record_id, "id": record_id, "fields": fields, "raw": payload}

    def delete_record(self, record_id: str, *, table_id: str | None = None) -> bool:
        url = f"{self._path_base(sheet_id_or_name=table_id)}/records/delete"
        response = self._ensure_client().post(
            url,
            headers=self._headers(),
            params=self._params(),
            json={"recordIds": [record_id]},
        )
        self._handle(response, action="删除 DingTalk AI 表格记录")
        return True

    def upload_file(self, file_path: Path) -> UploadedFile:
        """Upload a local file through the official AI table resource API.

        The OpenAPI flow is: query a signed upload URL, PUT the bytes, then
        write the returned resource metadata into the attachment cell.
        DingDrive ``fileId``/``dentryUuid`` values are not valid here.
        """
        if not file_path.is_file():
            raise DingtalkAPIError(f"file to upload does not exist: {file_path}")

        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        size = file_path.stat().st_size
        if size <= 0:
            raise DingtalkAPIError(f"file to upload is empty: {file_path}")

        url = (
            f"{self.base_url}/v1.0/doc/docs/resources/"
            f"{quote(self.base_id, safe='')}/uploadInfos/query"
        )
        response = self._ensure_client().post(
            url,
            headers=self._headers(),
            params=self._params(),
            json={
                "size": size,
                "mediaType": media_type,
                "resourceName": file_path.name,
            },
        )
        payload = self._handle(response, action="query DingTalk resource upload info")
        result = self._value(payload)
        if not isinstance(result, dict):
            raise DingtalkAPIError(
                "DingTalk resource upload response is not an object",
                payload=payload,
            )
        upload_url = str(result.get("uploadUrl") or "")
        if not upload_url:
            raise DingtalkAPIError(
                "DingTalk resource upload response is missing uploadUrl",
                payload=payload,
            )
        resource_id = str(result.get("resourceId") or "")
        resource_url = str(result.get("resourceUrl") or "")
        if not resource_id or not resource_url:
            raise DingtalkAPIError(
                "DingTalk resource upload response is missing resourceId/resourceUrl",
                payload=payload,
            )

        with file_path.open("rb") as handle:
            put_response = self._ensure_client().put(
                upload_url,
                headers={"Content-Type": media_type},
                content=handle,
            )
        if put_response.status_code >= 400:
            raise DingtalkAPIError(
                f"DingTalk resource PUT upload failed: HTTP {put_response.status_code}",
                code=put_response.status_code,
                payload=_safe_json(put_response),
            )

        attachment = {
            "filename": file_path.name,
            "size": size,
            "type": media_type,
            "url": resource_url,
            "resourceUrl": resource_url,
            "download_url": "",
            "downloadUrl": "",
            "resourceId": resource_id,
        }
        self._attachment_resources[resource_id] = attachment
        return UploadedFile(file_token=resource_id, url=resource_url, raw=attachment)

    def download_attachment(self, file_token: str, output_path: Path) -> Path:
        last_error: DingtalkAPIError | None = None
        refreshed_once = False
        while True:
            resource = self._attachment_resources.get(str(file_token))
            candidates = self._attachment_download_candidates(file_token, resource)
            for download_url in candidates:
                try:
                    response = self._ensure_client().get(
                        download_url,
                        headers={"x-acs-dingtalk-access-token": self.get_access_token()},
                    )
                except Exception as exc:
                    last_error = DingtalkAPIError(
                        f"DingTalk attachment download failed: {exc}",
                        payload={"resourceId": file_token, "downloadUrl": download_url},
                    )
                    continue
                if response.status_code >= 400:
                    last_error = DingtalkAPIError(
                        f"DingTalk attachment download failed: HTTP {response.status_code}",
                        code=response.status_code,
                        payload=_safe_json(response),
                    )
                    continue
                content = response.content
                if not _looks_like_image_bytes(content):
                    last_error = DingtalkAPIError(
                        "DingTalk attachment download did not return a valid image",
                        payload={
                            "resourceId": file_token,
                            "downloadUrl": download_url,
                            "content_type": response.headers.get("content-type", ""),
                            "preview": content[:200].decode("utf-8", errors="ignore"),
                        },
                    )
                    continue
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(content)
                return output_path

            if refreshed_once:
                break
            if not resource or not str(resource.get("download_url") or resource.get("downloadUrl") or "").strip():
                refreshed_once = True
                try:
                    self.list_records(page_size=100, max_pages=5)
                except Exception:
                    pass
                continue
            break

        if last_error is not None:
            raise last_error
        raise DingtalkAPIError(
            "DingTalk attachment URL is unavailable; read the record first",
            payload={"resourceId": file_token},
        )

    def _remember_attachment_resources(self, record: dict[str, Any]) -> None:
        fields = record.get("fields") if isinstance(record, dict) else None
        if not isinstance(fields, dict):
            return
        for value in fields.values():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if not isinstance(item, dict):
                    continue
                resource_id = str(item.get("resourceId") or item.get("resource_id") or "")
                resource_url = str(item.get("resourceUrl") or item.get("url") or "")
                download_url = str(item.get("url") or item.get("downloadUrl") or item.get("download_url") or "")
                if resource_id and resource_url:
                    self._attachment_resources[resource_id] = {
                        "filename": item.get("filename") or item.get("name") or "",
                        "size": item.get("size") or 0,
                        "type": item.get("type") or item.get("mime_type") or "",
                        "url": resource_url,
                        "resourceUrl": resource_url,
                        "download_url": download_url,
                        "downloadUrl": download_url,
                        "resourceId": resource_id,
                    }

    def _normalize_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in fields.items():
            result[key] = self._normalize_value(value)
        return result

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, list):
            normalized = []
            for item in value:
                if isinstance(item, dict) and (
                    item.get("resourceId") or item.get("resource_id")
                ):
                    normalized.append(
                        {
                            "filename": item.get("filename") or item.get("name") or "",
                            "size": item.get("size") or 0,
                            "type": item.get("type") or item.get("mime_type") or "",
                            "url": item.get("url") or item.get("resourceUrl") or "",
                            "resourceId": item.get("resourceId") or item.get("resource_id"),
                        }
                    )
                elif isinstance(item, dict) and item.get("file_token"):
                    resource_id = str(item["file_token"])
                    attachment = self._attachment_resources.get(resource_id)
                    if not attachment:
                        raise DingtalkAPIError(
                            "DingTalk attachment metadata is missing for file_token",
                            payload={"file_token": resource_id},
                        )
                    normalized.append(
                        {
                            "filename": attachment.get("filename") or "",
                            "size": attachment.get("size") or 0,
                            "type": attachment.get("type") or "",
                            "url": attachment.get("url") or attachment.get("resourceUrl") or "",
                            "resourceId": attachment.get("resourceId") or resource_id,
                        }
                    )
                else:
                    normalized.append(item)
            return normalized
        return value

    def _attachment_download_candidates(
        self,
        file_token: str,
        resource: dict[str, Any] | None,
    ) -> list[str]:
        candidates: list[str] = []
        if resource:
            for key in ("download_url", "downloadUrl"):
                value = str(resource.get(key) or "").strip()
                if value and value not in candidates:
                    candidates.append(value)

            raw_url = str(
                resource.get("url")
                or resource.get("resourceUrl")
                or resource.get("resource_url")
                or ""
            ).strip()
            if raw_url:
                if raw_url.startswith(("http://", "https://")):
                    if raw_url not in candidates:
                        candidates.append(raw_url)
                else:
                    absolute = urljoin(f"{self.base_url}/", raw_url.lstrip("/"))
                    if absolute not in candidates:
                        candidates.append(absolute)

        if not candidates and str(file_token).startswith(("http://", "https://")):
            candidates.append(str(file_token))
        return candidates


def _field_info(item: dict[str, Any]) -> FieldInfo:
    raw_type = item.get("type") or item.get("fieldType") or item.get("uiType") or ""
    return FieldInfo(
        field_id=str(item.get("id") or item.get("fieldId") or item.get("name") or ""),
        field_name=str(item.get("name") or item.get("fieldName") or item.get("id") or ""),
        field_type=_field_type(raw_type),
        ui_type=str(raw_type) if raw_type is not None else None,
        description=item.get("description"),
        is_primary=bool(item.get("isPrimary") or item.get("is_primary")),
        raw=item,
    )


def _field_type(raw_type: Any) -> int:
    text = str(raw_type or "").replace("_", "").replace("-", "").lower()
    if text.isdigit():
        return int(text)
    if "attachment" in text or "file" in text or "附件" in text:
        return 17
    if "number" in text or "integer" in text or "decimal" in text or "数字" in text:
        return 2
    if "date" in text or "time" in text or "日期" in text:
        return 5
    if "url" in text or "link" in text or "链接" in text:
        return 15
    return 1


def _record_info(item: dict[str, Any]) -> dict[str, Any]:
    record_id = str(item.get("id") or item.get("recordId") or item.get("record_id") or "")
    fields = item.get("fields") or {}
    return {"record_id": record_id, "id": record_id, "fields": fields, "raw": item}


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text}


def _looks_like_image_bytes(content: bytes) -> bool:
    if len(content) < 64:
        return False
    if content.lstrip().startswith((b"{", b"[", b"<")):
        return False
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        return True
    except Exception:
        return False


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = dict(left)
    for key, value in right.items():
        if value:
            result[key] = value
    return result


def _first_non_empty(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value:
            return str(value)
    return ""
