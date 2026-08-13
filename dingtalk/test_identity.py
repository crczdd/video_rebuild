from __future__ import annotations

import httpx

from dingtalk.identity import resolve_operator_from_auth_code


def test_resolve_operator_from_auth_code() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json={"errcode": 0, "accessToken": "token-123"})
        if request.url.path.endswith("/getuserinfo"):
            assert request.url.params.get("access_token") == "token-123"
            assert request.method == "POST"
            assert request.content
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "result": {
                        "userid": "user-456",
                        "unionid": "union-789",
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    result = resolve_operator_from_auth_code(
        app_key="app-key",
        app_secret="app-secret",
        auth_code="auth-code",
        transport=transport,
    )

    assert result["access_token"] == "token-123"
    assert result["userid"] == "user-456"
    assert result["unionid"] == "union-789"
    assert calls == [("GET", "/gettoken"), ("POST", "/topapi/v2/user/getuserinfo")]
