from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from video_remake import fields as f
from video_remake.llm_client import EmptyLLMResponseError, LLMClient, normalize_base_url
from video_remake.models import VideoRemakeTask, field_text, is_non_empty
from video_remake.prompt_builder import build_merged_change_advice, build_user_prompt
from video_remake.service import run_cycle, validate_table_fields
from video_remake.settings import VideoRemakeSettings


def task_fields(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        f.VIDEO_NAME: "测试视频",
        f.VIDEO_URL: "https://example.test/video/1",
        f.NANOPHOTO_PROMPT: "镜头1：人物走入房间。",
        f.DIALOGUE_CHANGE: "改为：你好",
        f.PRODUCT_CHANGE: "",
        f.CHARACTER_CHANGE: "",
        f.BACKGROUND_CHANGE: "",
        f.PAIN_POINT_CHANGE: "",
        f.SPECIAL_SHOT: "",
        f.FINAL_ADVICE: "",
        f.GPT_CONFIRMED: "是",
        f.FINAL_PROMPT: "",
        "额外秘密字段": "不得发送",
    }
    values.update(overrides)
    return values


def make_record(record_id: str = "rec-1", **overrides: Any) -> dict[str, Any]:
    return {"record_id": record_id, "fields": task_fields(**overrides)}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({f.GPT_CONFIRMED: "否"}, False),
        ({f.VIDEO_NAME: ""}, False),
        ({f.VIDEO_URL: None}, True),
        ({f.NANOPHOTO_PROMPT: "  "}, False),
        ({f.FINAL_PROMPT: "已完成"}, False),
        ({}, True),
    ],
)
def test_eligibility(overrides: dict[str, Any], expected: bool) -> None:
    assert VideoRemakeTask.from_record(make_record(**overrides)).is_eligible() is expected


def test_video_url_is_not_a_required_table_field() -> None:
    assert f.VIDEO_URL in f.INPUT_FIELDS
    assert f.VIDEO_URL not in f.REQUIRED_FIELDS


def test_all_change_fields_empty_is_ineligible() -> None:
    overrides = {name: "" for name in f.CHANGE_FIELDS}
    assert not VideoRemakeTask.from_record(make_record(**overrides)).is_eligible()


def test_only_final_advice_is_eligible() -> None:
    overrides = {name: "" for name in f.CHANGE_FIELDS}
    overrides[f.FINAL_ADVICE] = "保持结构，增强节奏"
    assert VideoRemakeTask.from_record(make_record(**overrides)).is_eligible()


@pytest.mark.parametrize("empty", [None, "", "  ", [], {}, [" "]])
def test_is_non_empty_false(empty: Any) -> None:
    assert not is_non_empty(empty)


def test_dingtalk_cell_shapes_extract_text() -> None:
    assert field_text("  文本  ") == "文本"
    assert field_text([{"text": "甲"}, {"name": "乙"}]) == "甲\n乙"
    assert field_text({"value": [{"label": "是"}]}) == "是"
    assert VideoRemakeTask.from_record(
        make_record(**{f.GPT_CONFIRMED: [{"text": "是"}]})
    ).is_eligible()


def test_task_whitelists_fields_and_prompt_omits_empty_changes() -> None:
    task = VideoRemakeTask.from_record(make_record())
    assert "额外秘密字段" not in task.values
    prompt = build_user_prompt(task)
    assert "额外秘密字段" not in prompt
    assert "台词修改：改为：你好" in prompt
    assert f.PRODUCT_CHANGE not in prompt
    assert "测试视频" not in prompt
    assert "https://example.test/video/1" not in prompt
    assert "Seedance 2.0 Mini" in prompt


def test_local_advice_merges_only_non_empty_specific_fields() -> None:
    task = VideoRemakeTask.from_record(
        make_record(
            **{
                f.DIALOGUE_CHANGE: "原台词“旧话”改为“新话”",
                f.PRODUCT_CHANGE: "产品换成新包装",
                f.BACKGROUND_CHANGE: "",
                f.FINAL_ADVICE: "整体保持原节奏",
            }
        )
    )
    advice = build_merged_change_advice(task)
    assert "原台词“旧话”改为“新话”" in advice
    assert "产品修改：产品换成新包装" in advice
    assert "背景修改" not in advice
    assert "总体修改建议：整体保持原节奏" in advice


def test_only_final_advice_is_sent_when_specific_fields_are_empty() -> None:
    overrides = {name: "" for name in f.SPECIFIC_CHANGE_FIELDS}
    overrides[f.FINAL_ADVICE] = "仅增强画面质感"
    task = VideoRemakeTask.from_record(make_record(**overrides))
    assert build_merged_change_advice(task) == "总体修改建议：仅增强画面质感"


@dataclass
class FakeField:
    field_name: str


class FakeTable:
    def __init__(self, records: list[dict[str, Any]], *, fail_record: str = "") -> None:
        self.records = records
        self.fail_record = fail_record
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def list_fields(self) -> list[FakeField]:
        return [FakeField(name) for name in f.REQUIRED_FIELDS]

    def list_records(self, *, page_size: int, max_pages: int) -> list[dict[str, Any]]:
        assert page_size == 100
        assert max_pages >= 20
        return self.records

    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if record_id == self.fail_record:
            raise RuntimeError("DingTalk update failed")
        self.updates.append((record_id, fields))
        return {"record_id": record_id}


class FakeLLM:
    def __init__(self, *, fail_record: str = "", empty_record: str = "") -> None:
        self.fail_record = fail_record
        self.empty_record = empty_record
        self.called: list[str] = []

    def generate_final_prompt(self, task: VideoRemakeTask) -> str:
        self.called.append(task.record_id)
        if task.record_id == self.fail_record:
            raise RuntimeError("LLM failed")
        if task.record_id == self.empty_record:
            return "   "
        return f"最终-{task.record_id}"


def test_success_updates_only_final_prompt_with_original_record_id() -> None:
    table = FakeTable([make_record("original-id")])
    result = run_cycle(table, FakeLLM())
    assert result.success == 1
    assert result.dingtalk_read_success is True
    assert result.llm_success == 1
    assert result.llm_failed == 0
    assert result.dingtalk_update_success == 1
    assert table.updates == [("original-id", {f.FINAL_PROMPT: "最终-original-id"})]


def test_llm_failure_and_empty_output_do_not_stop_following_records() -> None:
    table = FakeTable([make_record("bad"), make_record("empty"), make_record("good")])
    llm = FakeLLM(fail_record="bad", empty_record="empty")
    result = run_cycle(table, llm)
    assert result.failed == 2
    assert result.success == 1
    assert result.llm_success == 1
    assert result.llm_failed == 2
    assert "recordId=bad" in result.failure_details[0]
    assert "LLM调用失败" in result.failure_details[0]
    assert "LLM failed" in result.failure_details[0]
    assert "LLM 返回了空内容" in result.failure_details[1]
    assert llm.called == ["bad", "empty", "good"]
    assert table.updates == [("good", {f.FINAL_PROMPT: "最终-good"})]


def test_dingtalk_update_failure_does_not_stop_following_records() -> None:
    table = FakeTable([make_record("bad"), make_record("good")], fail_record="bad")
    result = run_cycle(table, FakeLLM())
    assert result.failed == 1
    assert result.success == 1
    assert result.llm_success == 2
    assert result.dingtalk_update_success == 1
    assert result.dingtalk_update_failed == 1
    assert "钉钉回写失败" in result.failure_details[0]
    assert table.updates == [("good", {f.FINAL_PROMPT: "最终-good"})]


def test_dry_run_never_calls_llm_or_updates() -> None:
    table = FakeTable([make_record("eligible")])
    result = run_cycle(table, None, dry_run=True)
    assert result.eligible == 1
    assert result.success == 0
    assert result.dry_run is True
    assert result.dingtalk_read_success is True
    assert result.llm_success == 0
    assert result.dingtalk_update_success == 0
    assert table.updates == []


def test_missing_field_fails_before_records_are_read() -> None:
    table = FakeTable([])
    table.list_fields = lambda: [FakeField(name) for name in f.REQUIRED_FIELDS[:-1]]  # type: ignore[method-assign]
    with pytest.raises(ValueError, match=f.FINAL_PROMPT):
        validate_table_fields(table)


def test_llm_empty_response_is_failure() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  "))]
    )
    observed = {}
    def create(**kwargs):
        observed.update(kwargs)
        return response
    completions = SimpleNamespace(create=create)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = VideoRemakeSettings("key", "https://llm.test/v1", "model")
    llm = LLMClient(settings, client=client, sleep=lambda _: None)
    with pytest.raises(EmptyLLMResponseError):
        llm.generate_final_prompt(VideoRemakeTask.from_record(make_record()))
    assert 0 < observed["timeout"] <= 120


def test_responses_api_uses_reasoning_and_disables_storage() -> None:
    observed = {}

    def create(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(output_text="Responses API 最终提示词")

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    settings = VideoRemakeSettings(
        "key",
        "https://llm.test",
        "gpt-5.5",
        llm_api_mode="responses",
        llm_reasoning_effort="xhigh",
        llm_disable_response_storage=True,
    )
    llm = LLMClient(settings, client=client, sleep=lambda _: None)
    result = llm.generate_final_prompt(VideoRemakeTask.from_record(make_record()))

    assert result == "Responses API 最终提示词"
    assert observed["model"] == "gpt-5.5"
    assert observed["reasoning"] == {"effort": "xhigh"}
    assert observed["store"] is False
    assert "instructions" in observed
    assert "input" in observed
    assert 0 < observed["timeout"] <= 120


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://faroapi.com/v1", "https://faroapi.com/v1"),
        ("https://faroapi.com/v1/", "https://faroapi.com/v1"),
        (
            "https://faroapi.com/v1/chat/completions",
            "https://faroapi.com/v1",
        ),
        (
            " https://faroapi.com/v1/chat/completions/ ",
            "https://faroapi.com/v1",
        ),
        ("https://provider.example/responses", "https://provider.example"),
    ],
)
def test_normalize_llm_base_url(configured: str, expected: str) -> None:
    assert normalize_base_url(configured) == expected
