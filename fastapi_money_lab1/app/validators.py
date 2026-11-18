"""跨路由共用的业务校验。"""

from __future__ import annotations

from datetime import date

from .errors import ApiError


def ensure_date_range(date_from: date | None, date_to: date | None) -> None:
    """区间倒置属于业务规则错误 → 400（而不是参数格式错误 422）。"""
    if date_from and date_to and date_from > date_to:
        raise ApiError(
            status_code=400,
            code="INVALID_DATE_RANGE",
            message="date_from 不能晚于 date_to",
            detail={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        )
