"""区间汇总：收入、支出、结余。"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ..database import get_connection
from ..schemas import SummaryOut
from ..validators import ensure_date_range

router = APIRouter(prefix="/summary", tags=["汇总"])

SUMMARY_SQL = """
SELECT
    COALESCE(SUM(CASE WHEN type = '收入' THEN amount END), 0) AS income,
    COALESCE(SUM(CASE WHEN type = '支出' THEN amount END), 0) AS expense
FROM records
"""


@router.get("", response_model=SummaryOut, summary="统计日期区间内的收入、支出与结余")
def summarize(
    date_from: Annotated[date | None, Query(description="起始日期（含）")] = None,
    date_to: Annotated[date | None, Query(description="结束日期（含）")] = None,
    conn: sqlite3.Connection = Depends(get_connection),
) -> SummaryOut:
    """无数据时三项都返回 0（不是 null），前端不用做空值判断。"""
    ensure_date_range(date_from, date_to)

    conditions: list[str] = []
    params: list[Any] = []
    if date_from:
        conditions.append("date >= ?")
        params.append(date_from.isoformat())
    if date_to:
        conditions.append("date <= ?")
        params.append(date_to.isoformat())
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    row = conn.execute(SUMMARY_SQL + where_sql, params).fetchone()
    income = round(float(row["income"]), 2)
    expense = round(float(row["expense"]), 2)
    return SummaryOut(income=income, expense=expense, balance=round(income - expense, 2))
