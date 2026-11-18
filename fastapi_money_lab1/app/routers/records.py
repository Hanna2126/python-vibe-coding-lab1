"""流水的新增与查询。"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from ..database import get_connection
from ..errors import ApiError
from ..schemas import MoneyType, RecordCreate, RecordOut, RecordsPage
from ..validators import ensure_date_range

router = APIRouter(prefix="/records", tags=["流水"])

INSERT_SQL = "INSERT INTO records (amount, type, category, date) VALUES (?, ?, ?, ?)"
SELECT_BY_ID_SQL = "SELECT * FROM records WHERE id = ?"


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass  # 事务可能已经结束，这里只做尽力回滚


@router.post("", response_model=RecordOut, status_code=status.HTTP_201_CREATED, summary="新增一条流水")
def create_record(
    payload: RecordCreate,
    conn: sqlite3.Connection = Depends(get_connection),
) -> RecordOut:
    """写入一条流水。

    - 应用层：Pydantic 已保证 amount>0、type 合法、date 真实存在；
    - 数据库层：CHECK 约束再兜一层，防住绕过 API 的写入；
    - 事务：BEGIN IMMEDIATE 显式拿写锁，commit 成功才算数，异常一律回滚。
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(INSERT_SQL, (payload.amount, payload.type, payload.category, payload.date.isoformat()))
        new_id = int(cursor.lastrowid or 0)
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        _safe_rollback(conn)
        raise ApiError(
            422,
            "DATA_INTEGRITY_ERROR",
            "数据未通过数据库约束校验（应用层已拦截，此处为兜底）",
            str(exc),
        ) from exc
    except sqlite3.OperationalError as exc:
        _safe_rollback(conn)
        raise ApiError(503, "DB_BUSY", "数据库繁忙，请稍后重试", str(exc)) from exc
    except sqlite3.Error as exc:
        _safe_rollback(conn)
        raise ApiError(500, "DB_ERROR", "数据库写入失败", str(exc)) from exc

    row = conn.execute(SELECT_BY_ID_SQL, (new_id,)).fetchone()
    if row is None:  # 理论上不会发生，兜住"插入成功却查不到"
        raise ApiError(500, "RECORD_NOT_FOUND_AFTER_INSERT", "写入成功但读取失败，请重试")
    return RecordOut(**dict(row))


@router.get("", response_model=RecordsPage, summary="按类型 / 分类 / 日期区间分页查询流水")
def list_records(
    record_type: Annotated[MoneyType | None, Query(alias="type", description="收入 或 支出")] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=32, description="分类，精确匹配")] = None,
    date_from: Annotated[date | None, Query(description="起始日期（含）")] = None,
    date_to: Annotated[date | None, Query(description="结束日期（含）")] = None,
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数，1~100")] = 10,
    conn: sqlite3.Connection = Depends(get_connection),
) -> RecordsPage:
    ensure_date_range(date_from, date_to)

    conditions: list[str] = []
    params: list[Any] = []
    if record_type:
        conditions.append("type = ?")
        params.append(record_type)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if date_from:
        conditions.append("date >= ?")
        params.append(date_from.isoformat())
    if date_to:
        conditions.append("date <= ?")
        params.append(date_to.isoformat())
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    total = int(conn.execute("SELECT COUNT(*) FROM records" + where_sql, params).fetchone()[0])
    rows = conn.execute(
        "SELECT * FROM records" + where_sql + " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    return RecordsPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[RecordOut(**dict(row)) for row in rows],
    )
