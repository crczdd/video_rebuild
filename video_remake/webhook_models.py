from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    request_id: str = Field(default="", validation_alias=AliasChoices("request_id", "请求ID"))
    record_id: str = Field(default="", validation_alias=AliasChoices("record_id", "recordId", "记录ID", "row_id"))
    video_name: str = Field(default="", validation_alias=AliasChoices("video_name", "视频名称", "视频标题"))
    video_url: str = Field(default="", validation_alias=AliasChoices("video_url", "视频链接"))
    nanophoto_prompt: str = Field(default="", validation_alias=AliasChoices("nanophoto_prompt", "nanophoto提示词"))
    dialogue_change: str = Field(default="", validation_alias=AliasChoices("dialogue_change", "台词修改"))
    product_change: str = Field(default="", validation_alias=AliasChoices("product_change", "产品修改"))
    character_change: str = Field(default="", validation_alias=AliasChoices("character_change", "人物修改"))
    background_change: str = Field(default="", validation_alias=AliasChoices("background_change", "背景修改"))
    pain_point_change: str = Field(default="", validation_alias=AliasChoices("pain_point_change", "痛点变化"))
    special_shot: str = Field(default="", validation_alias=AliasChoices("special_shot", "特殊镜头描述"))
    final_advice: str = Field(default="", validation_alias=AliasChoices("final_advice", "修改最终建议"))

    @model_validator(mode="before")
    @classmethod
    def unwrap_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("data", "fields", "payload"):
                nested = value.get(key)
                if isinstance(nested, dict):
                    merged = dict(nested)
                    for identity in ("request_id", "record_id", "recordId", "row_id"):
                        if identity in value and identity not in merged:
                            merged[identity] = value[identity]
                    return merged
        return value

    def stripped(self) -> "GenerateRequest":
        values = {
            name: value.strip() if isinstance(value, str) else value
            for name, value in self.model_dump().items()
        }
        return GenerateRequest(**values)


class GenerateData(BaseModel):
    request_id: str
    record_id: str
    final_prompt: str
    cached: bool = False


class APIResponse(BaseModel):
    code: int
    message: str
    data: GenerateData | dict[str, Any] | None = None
