from __future__ import annotations

import argparse
from pathlib import Path

from dingtalk.identity import (
    DEFAULT_ENV_PATH,
    DingtalkIdentityError,
    read_env_values,
    resolve_operator_from_auth_code,
    resolve_operator_from_userid,
    upsert_env_value,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve DingTalk operatorId and write it to .env."
    )
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="Path to .env")
    parser.add_argument("--auth-code", default="", help="DingTalk auth code, overrides .env")
    parser.add_argument("--userid", default="", help="DingTalk userid, overrides .env")
    parser.add_argument("--no-write", action="store_true", help="Only print results")
    args = parser.parse_args()

    env_path = Path(args.env)
    pairs = read_env_values(env_path)
    app_key = pairs.get("DIPR_DINGTALK_APP_KEY", "")
    app_secret = pairs.get("DIPR_DINGTALK_APP_SECRET", "")
    auth_code = args.auth_code or pairs.get("DIPR_DINGTALK_AUTH_CODE", "")
    userid = args.userid or pairs.get("DIPR_DINGTALK_USERID", "")

    if not app_key or not app_secret:
        raise SystemExit("missing DIPR_DINGTALK_APP_KEY / DIPR_DINGTALK_APP_SECRET")
    if not auth_code and not userid:
        raise SystemExit(
            "missing DingTalk auth code or userid. Set DIPR_DINGTALK_AUTH_CODE / DIPR_DINGTALK_USERID "
            "or pass --auth-code / --userid."
        )

    try:
        if userid:
            result = resolve_operator_from_userid(
                app_key=app_key,
                app_secret=app_secret,
                userid=userid,
            )
        else:
            result = resolve_operator_from_auth_code(
                app_key=app_key,
                app_secret=app_secret,
                auth_code=auth_code,
            )
    except DingtalkIdentityError as exc:
        raise SystemExit(str(exc)) from exc
    token = result["access_token"]
    print(f"access_token: {_mask(token)}")
    userid = str(result.get("userid") or "")
    resolved_userid = str(result.get("userid") or userid or "")
    if resolved_userid:
        print(f"userid: {resolved_userid}")
    unionid = str(result["unionid"])
    print(f"unionid/operatorId: {unionid}")

    if not args.no_write:
        if resolved_userid:
            upsert_env_value(env_path, "DIPR_DINGTALK_USERID", resolved_userid)
        upsert_env_value(env_path, "DIPR_DINGTALK_OPERATOR_ID", unionid)
        if auth_code:
            upsert_env_value(env_path, "DIPR_DINGTALK_AUTH_CODE", "")
        print(f"updated: {env_path}")
    return 0


def _mask(value: str) -> str:
    if len(value) <= 12:
        return "<set>"
    return f"{value[:8]}...{value[-6:]}"


if __name__ == "__main__":
    raise SystemExit(main())
