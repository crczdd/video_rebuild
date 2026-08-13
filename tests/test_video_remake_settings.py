from __future__ import annotations

from dingtalk.settings import DingtalkSettings


def test_video_remake_uses_dedicated_sheet_then_fallback() -> None:
    settings = DingtalkSettings("key", "secret", "base", "operator", fallback_sheet="fallback")
    assert settings.target("video_remake") == ("fallback", "")
    settings.video_remake_sheet = "remake"
    settings.video_remake_view = "view"
    assert settings.target("video_remake") == ("remake", "view")
