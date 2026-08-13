from __future__ import annotations

from .client import DingtalkBitableClient
from .settings import DingtalkSettings


def make_client(
    workflow: str,
    *,
    settings: DingtalkSettings | None = None,
    timeout: float = 30.0,
) -> DingtalkBitableClient:
    settings = settings or DingtalkSettings.from_env()
    settings.validate(workflow)
    sheet, view = settings.target(workflow)
    return DingtalkBitableClient(
        app_key=settings.app_key,
        app_secret=settings.app_secret,
        base_id=settings.base_id,
        sheet_id_or_name=sheet,
        view_id=view,
        operator_id=settings.operator_id,
        base_url=settings.base_url,
        timeout=timeout,
    )
