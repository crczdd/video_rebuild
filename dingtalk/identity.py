from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

OAPI_BASE = "https://oapi.dingtalk.com"
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class DingtalkIdentityError(RuntimeError):
    def __init__(self, message: str, *, payload: Any = None) -> None:
        super().__init__(message)
        self.payload = payload


def resolve_operator_from_auth_code(
    *,
    app_key: str,
    app_secret: str,
    auth_code: str,
    base_url: str = OAPI_BASE,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, transport=transport) as client:
        token = get_access_token(client, app_key=app_key, app_secret=app_secret, base_url=base_url)
        userinfo = get_userinfo_by_auth_code(client, token=token, auth_code=auth_code, base_url=base_url)
        userid = str(userinfo.get("userid") or userinfo.get("userId") or "")
        unionid = str(userinfo.get("unionid") or userinfo.get("unionId") or "")
        if not unionid:
            raise DingtalkIdentityError("user/getuserinfo response has no unionid", payload=userinfo)
        return {"access_token": token, "userid": userid, "unionid": unionid, "raw": userinfo}


def resolve_operator_from_userid(
    *,
    app_key: str,
    app_secret: str,
    userid: str,
    base_url: str = OAPI_BASE,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, transport=transport) as client:
        token = get_access_token(client, app_key=app_key, app_secret=app_secret, base_url=base_url)
        userinfo = get_user_details_by_userid(client, token=token, userid=userid, base_url=base_url)
        resolved_userid = str(userinfo.get("userid") or userinfo.get("userId") or userid or "")
        unionid = str(userinfo.get("unionid") or userinfo.get("unionId") or "")
        if not unionid:
            raise DingtalkIdentityError("user/get response has no unionid", payload=userinfo)
        return {"access_token": token, "userid": resolved_userid, "unionid": unionid, "raw": userinfo}


def get_access_token(
    client: httpx.Client, *, app_key: str, app_secret: str, base_url: str = OAPI_BASE
) -> str:
    response = client.get(
        f"{base_url.rstrip('/')}/gettoken",
        params={"appkey": app_key, "appsecret": app_secret},
    )
    payload = _json(response)
    _raise_if_dingtalk_error(payload, "gettoken")
    token = str(payload.get("access_token") or payload.get("accessToken") or "")
    if not token:
        raise DingtalkIdentityError("gettoken response has no access_token", payload=payload)
    return token


def get_userinfo_by_auth_code(
    client: httpx.Client, *, token: str, auth_code: str, base_url: str = OAPI_BASE
) -> dict[str, Any]:
    response = client.post(
        f"{base_url.rstrip('/')}/topapi/v2/user/getuserinfo",
        params={"access_token": token},
        json={"code": auth_code},
    )
    payload = _json(response)
    _raise_if_dingtalk_error(payload, "user/getuserinfo")
    result = payload.get("result")
    if not isinstance(result, dict):
        if isinstance(payload, dict) and (payload.get("userid") or payload.get("userId")):
            result = payload
        else:
            raise DingtalkIdentityError("user/getuserinfo response has invalid result", payload=payload)
    return result


def get_user_details_by_userid(
    client: httpx.Client, *, token: str, userid: str, base_url: str = OAPI_BASE
) -> dict[str, Any]:
    response = client.post(
        f"{base_url.rstrip('/')}/topapi/v2/user/get",
        params={"access_token": token},
        json={"userid": userid},
    )
    payload = _json(response)
    _raise_if_dingtalk_error(payload, "topapi/v2/user/get")
    result = payload.get("result")
    if not isinstance(result, dict):
        if isinstance(payload, dict) and (payload.get("userid") or payload.get("userId")):
            result = payload
        else:
            raise DingtalkIdentityError("topapi/v2/user/get response has invalid result", payload=payload)
    return result


def upsert_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    replaced = False
    for index, raw in enumerate(lines):
        if raw.strip().startswith("#") or "=" not in raw:
            continue
        current_key = raw.split("=", 1)[0].strip()
        if current_key == key:
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_env_values(path: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not path.exists():
        return pairs
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise DingtalkIdentityError(
            f"HTTP {response.status_code}: non-json response"
        ) from exc
    if not isinstance(payload, dict):
        raise DingtalkIdentityError(
            f"HTTP {response.status_code}: invalid response {payload!r}"
        )
    return payload


def _raise_if_dingtalk_error(payload: dict[str, Any], action: str) -> None:
    errcode = payload.get("errcode")
    if errcode in (None, 0, "0"):
        return
    errmsg = payload.get("errmsg") or payload.get("sub_msg") or payload
    raise DingtalkIdentityError(f"{action} failed: errcode={errcode}, errmsg={errmsg}", payload=payload)
