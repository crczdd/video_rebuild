from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from dingtalk.attachments import attachment_value
from dingtalk.client import DingtalkBitableClient


def test_attachment_upload_and_record_write(tmp_path: Path) -> None:
    source = tmp_path / "evidence.png"
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    source.write_bytes(image_bytes)
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token-1"})
        if request.url.path.endswith("/uploadInfos/query"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "uploadUrl": "https://oss.example/upload",
                        "resourceId": "res-1",
                        "resourceUrl": "/core/api/resources/img/res-1",
                    },
                },
            )
        if request.url.host == "oss.example":
            assert request.content == image_bytes
            return httpx.Response(200)
        if request.url.path == "/core/api/resources/img/res-1":
            return httpx.Response(200, content=image_bytes, headers={"content-type": "image/png"})
        if request.url.path.endswith("/records"):
            observed["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"success": True, "result": {"records": [{"id": "rec-1", "fields": {}}]}},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = DingtalkBitableClient(
        app_key="key",
        app_secret="secret",
        base_id="base-1",
        sheet_id_or_name="sheet-1",
        operator_id="union-1",
        transport=httpx.MockTransport(handler),
    )
    with client:
        uploaded = client.upload_file(source)
        result = client.create_record({"侵权截图1": attachment_value(uploaded.file_token)})
        downloaded = client.download_attachment("res-1", tmp_path / "downloaded.png")

    assert result["record_id"] == "rec-1"
    assert downloaded.read_bytes() == image_bytes
    attachment = observed["body"]["records"][0]["fields"]["侵权截图1"][0]
    assert attachment == {
        "filename": "evidence.png",
        "size": len(image_bytes),
        "type": "image/png",
        "url": "/core/api/resources/img/res-1",
        "resourceId": "res-1",
    }
