from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from video_remake.scheduler import SchedulerManager
from video_remake.service import CycleResult
from video_remake.web import create_app


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_manual_dry_run_and_non_overlap(tmp_path) -> None:
    release = threading.Event()
    modes: list[bool] = []

    def execute(dry_run: bool) -> CycleResult:
        modes.append(dry_run)
        release.wait(timeout=1)
        return CycleResult(
            dry_run=dry_run,
            dingtalk_read_success=True,
            fetched=2,
            eligible=1,
            success=0,
            skipped=1,
            failed=0,
        )

    manager = SchedulerManager(
        execute=execute,
        default_interval=600,
        state_path=tmp_path / "state.json",
    )
    try:
        manager.run_now(dry_run=True)
        wait_until(lambda: manager.status()["running"])
        with pytest.raises(RuntimeError, match="已有任务正在执行"):
            manager.run_now(dry_run=False)
        release.set()
        wait_until(lambda: not manager.status()["running"])
        assert modes == [True]
        assert manager.status()["last_result"]["eligible"] == 1
        assert any("钉钉读取成功" in event for event in manager.status()["events"])
        assert any("未调用 LLM" in event for event in manager.status()["events"])
    finally:
        manager.shutdown()


def test_interval_is_persisted_but_enabled_state_is_not(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    manager = SchedulerManager(state_path=state_path)
    manager.set_interval(300)
    manager.start()
    assert manager.status()["enabled"] is True
    manager.shutdown()

    restored = SchedulerManager(state_path=state_path)
    try:
        assert restored.status()["interval_seconds"] == 300
        assert restored.status()["enabled"] is False
    finally:
        restored.shutdown()


def test_web_api_controls_scheduler(tmp_path) -> None:
    manager = SchedulerManager(
        execute=lambda dry_run: CycleResult(fetched=1, eligible=0, skipped=1),
        state_path=tmp_path / "state.json",
    )
    app = create_app(manager)
    try:
        with TestClient(app) as client:
            assert client.get("/").status_code == 200
            response = client.put("/api/settings", json={"interval_seconds": 120})
            assert response.status_code == 200
            assert response.json()["interval_seconds"] == 120

            response = client.post("/api/start", json={"run_immediately": False})
            assert response.json()["enabled"] is True
            assert response.json()["next_run_at"] is not None

            response = client.post("/api/stop", json={})
            assert response.json()["enabled"] is False

            assert client.put("/api/settings", json={"interval_seconds": 2}).status_code == 422
    finally:
        manager.shutdown()
