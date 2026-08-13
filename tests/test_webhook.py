from __future__ import annotations

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from video_remake.api import create_app
from video_remake.job_store import JobStore
from video_remake.settings import VideoRemakeSettings
from video_remake.webhook_service import WebhookService


class FakeLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate_final_prompt(self, task):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        assert task.video_name == "测试视频"
        return "Seedance最终提示词"


def settings(path: Path) -> VideoRemakeSettings:
    return VideoRemakeSettings(
        llm_api_key="key",
        llm_base_url="https://example.test/v1",
        llm_model="model",
        webhook_auth_token="secret-token",
        database_path=str(path),
    )


def payload() -> dict:
    return {
        "request_id": "ding-run-1",
        "record_id": "record-1",
        "视频名称": "测试视频",
        "nanophoto提示词": "镜头1：人物进入房间。",
        "台词修改": "把旧台词改成新台词",
        "产品修改": "",
        "人物修改": "",
        "背景修改": "",
        "痛点变化": "",
        "特殊镜头描述": "",
        "修改最终建议": "保持原节奏",
    }


def make_client(tmp_path: Path, llm: FakeLLM | None = None):
    llm = llm or FakeLLM()
    store = JobStore(tmp_path / "jobs.db")
    service = WebhookService(llm, store)
    app = create_app(settings=settings(tmp_path / "jobs.db"), service=service, store=store)
    return TestClient(app), llm


def test_health_is_public_and_generate_requires_bearer(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.post("/api/v1/video-remake/generate", json=payload())
    assert response.status_code == 401
    assert response.json()["code"] == 40101


def test_generate_returns_json_for_dingtalk_and_is_idempotent(tmp_path: Path) -> None:
    client, llm = make_client(tmp_path)
    headers = {"Authorization": "Bearer secret-token"}
    first = client.post("/api/v1/video-remake/generate", json=payload(), headers=headers)
    second = client.post("/api/v1/video-remake/generate", json=payload(), headers=headers)

    assert first.status_code == 200
    assert first.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "request_id": "ding-run-1",
            "record_id": "record-1",
            "final_prompt": "Seedance最终提示词",
            "cached": False,
        },
    }
    assert second.json()["data"]["cached"] is True
    assert llm.calls == 1


def test_video_url_is_optional_and_legacy_value_is_still_accepted(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    body = payload() | {
        "request_id": "ding-run-with-video-url",
        "视频链接": "https://example.test/legacy.mp4",
    }
    response = client.post(
        "/api/v1/video-remake/generate",
        json=body,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200


def test_wrapped_chinese_payload_is_supported(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    wrapped = {"request_id": "wrapped-1", "data": payload() | {"request_id": "wrapped-1"}}
    response = client.post(
        "/api/v1/video-remake/generate",
        json=wrapped,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["record_id"] == "record-1"


def test_validation_error_is_structured_json(tmp_path: Path) -> None:
    client, llm = make_client(tmp_path)
    invalid = payload()
    invalid["nanophoto提示词"] = ""
    response = client.post(
        "/api/v1/video-remake/generate",
        json=invalid,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42201
    assert "nanophoto提示词" in response.json()["message"]
    assert llm.calls == 0


def test_llm_failure_is_structured_and_can_be_retried(tmp_path: Path) -> None:
    llm = FakeLLM(fail=True)
    client, _ = make_client(tmp_path, llm)
    headers = {"Authorization": "Bearer secret-token"}
    first = client.post("/api/v1/video-remake/generate", json=payload(), headers=headers)
    assert first.status_code == 502
    assert first.json()["code"] == 50201
    assert "LLM调用失败" in first.json()["message"]

    llm.fail = False
    second = client.post("/api/v1/video-remake/generate", json=payload(), headers=headers)
    assert second.status_code == 200
    assert llm.calls == 2


def test_status_requires_auth_and_does_not_return_prompts(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    headers = {"Authorization": "Bearer secret-token"}
    client.post("/api/v1/video-remake/generate", json=payload(), headers=headers)
    assert client.get("/api/status").status_code == 401
    response = client.get("/api/status", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] == 1
    assert "final_prompt" not in str(body)


def test_malformed_json_has_standard_response(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    response = client.post(
        "/api/v1/video-remake/generate",
        content="not-json",
        headers={
            "Authorization": "Bearer secret-token",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200
    assert response.json()["data"] is None
