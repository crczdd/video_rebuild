"""Central definitions for DingTalk AI table business fields."""

VIDEO_NAME = "视频名称"
VIDEO_URL = "视频链接"
NANOPHOTO_PROMPT = "nanophoto提示词"
DIALOGUE_CHANGE = "台词修改"
PRODUCT_CHANGE = "产品修改"
CHARACTER_CHANGE = "人物修改"
BACKGROUND_CHANGE = "背景修改"
PAIN_POINT_CHANGE = "痛点变化"
SPECIAL_SHOT = "特殊镜头描述"
FINAL_ADVICE = "修改最终建议"
GPT_CONFIRMED = "gpt请求确认"
FINAL_PROMPT = "最终提示词"

# Fields whose values must be present before a generation request can run.
# VIDEO_URL is optional: DingTalk may keep the video as an attachment without
# sending it to the cloud workflow.
BASE_FIELDS = (VIDEO_NAME, NANOPHOTO_PROMPT)
SPECIFIC_CHANGE_FIELDS = (
    DIALOGUE_CHANGE,
    PRODUCT_CHANGE,
    CHARACTER_CHANGE,
    BACKGROUND_CHANGE,
    PAIN_POINT_CHANGE,
    SPECIAL_SHOT,
)
CHANGE_FIELDS = (*SPECIFIC_CHANGE_FIELDS, FINAL_ADVICE)
INPUT_FIELDS = (
    VIDEO_NAME,
    VIDEO_URL,
    NANOPHOTO_PROMPT,
    *CHANGE_FIELDS,
    GPT_CONFIRMED,
    FINAL_PROMPT,
)
REQUIRED_FIELDS = tuple(name for name in INPUT_FIELDS if name != VIDEO_URL)
