#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
考题二测试：覆盖正常路径、校验边界、业务规则、并发写入。

运行：cd fastapi_money_lab1 && pytest -v
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

VALID = {"amount": 12.5, "type": "支出", "category": "餐饮", "date": "2026-09-30"}


def post(client, **kwargs):
    body = {**VALID, **kwargs}
    return client.post("/records", json=body)


# ---------------------------------------------------------------- 正常路径


def test_create_income_returns_201_and_echoes_payload(client):
    resp = post(client, amount=5000.0, type="收入", category="工资", date="2026-09-01")
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount"] == 5000.0
    assert body["type"] == "收入"
    assert body["category"] == "工资"
    assert body["date"] == "2026-09-01"
    assert isinstance(body["id"], int) and body["id"] == 1


def test_create_expense_returns_201(client):
    assert post(client, amount=12.5, type="支出", category="餐饮").status_code == 201


def test_small_amount_is_accepted(client):
    """边界：0.01 元是合法金额，不能被 gt=0 误伤。"""
    assert post(client, amount=0.01).status_code == 201


def test_category_is_stripped(client):
    resp = post(client, category="  餐饮  ")
    assert resp.status_code == 201
    assert resp.json()["category"] == "餐饮"


# ---------------------------------------------------------------- 校验边界（422）


@pytest.mark.parametrize("amount", [0, -1, -12.5])
def test_non_positive_amount_rejected(client, amount):
    resp = post(client, amount=amount)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_amount_missing_rejected(client):
    resp = client.post("/records", json={"type": "支出", "category": "餐饮", "date": "2026-09-30"})
    assert resp.status_code == 422


def test_amount_wrong_type_rejected(client):
    resp = post(client, amount="abc")
    assert resp.status_code == 422


def test_invalid_type_rejected(client):
    resp = post(client, type="转账")
    assert resp.status_code == 422


def test_nonexistent_date_rejected(client):
    """2026-02-30 格式对但日期不存在，必须被拒。"""
    resp = post(client, date="2026-02-30")
    assert resp.status_code == 422


def test_bad_date_format_rejected(client):
    resp = post(client, date="2026/09/30")
    assert resp.status_code == 422


def test_empty_body_rejected(client):
    assert client.post("/records", json={}).status_code == 422


def test_unknown_field_rejected(client):
    """多传未知字段 → 422，避免"以为写进去了"。"""
    resp = post(client, note="偷偷加个字段")
    assert resp.status_code == 422


def test_blank_category_rejected(client):
    resp = post(client, category="   ")
    assert resp.status_code == 422


def test_error_body_is_structured(client):
    resp = post(client, amount=-1)
    error = resp.json()["error"]
    assert set(error) == {"code", "message", "detail"}
    assert error["code"] == "VALIDATION_ERROR"
    assert isinstance(error["detail"], list)
    assert {"loc", "msg", "type"} <= set(error["detail"][0])
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------- 查询与分页


@pytest.fixture()
def seeded(client):
    seed = [
        (12.5, "支出", "餐饮", "2026-09-30"),
        (5000.0, "收入", "工资", "2026-09-01"),
        (30.0, "支出", "交通", "2026-09-15"),
        (800.0, "收入", "兼职", "2026-10-05"),
        (99.0, "支出", "餐饮", "2026-10-08"),
    ]
    for amount, type_, category, day in seed:
        assert post(client, amount=amount, type=type_, category=category, date=day).status_code == 201
    return client


def test_list_default_page(seeded):
    body = seeded.get("/records").json()
    assert body["total"] == 5
    assert body["page"] == 1 and body["page_size"] == 10
    assert len(body["items"]) == 5
    assert body["items"][0]["date"] >= body["items"][-1]["date"]  # 按日期倒序


def test_filter_by_type(seeded):
    body = seeded.get("/records", params={"type": "收入"}).json()
    assert body["total"] == 2
    assert all(item["type"] == "收入" for item in body["items"])


def test_filter_by_category(seeded):
    body = seeded.get("/records", params={"category": "餐饮"}).json()
    assert body["total"] == 2


def test_filter_by_date_range_is_inclusive(seeded):
    body = seeded.get("/records", params={"date_from": "2026-09-15", "date_to": "2026-09-30"}).json()
    assert body["total"] == 2
    assert {item["date"] for item in body["items"]} == {"2026-09-15", "2026-09-30"}


def test_pagination_second_page(seeded):
    page1 = seeded.get("/records", params={"page": 1, "page_size": 2}).json()
    page2 = seeded.get("/records", params={"page": 2, "page_size": 2}).json()
    assert page1["total"] == page2["total"] == 5
    assert len(page1["items"]) == 2 and len(page2["items"]) == 2
    ids1 = {item["id"] for item in page1["items"]}
    ids2 = {item["id"] for item in page2["items"]}
    assert not (ids1 & ids2)  # 两页不重叠


def test_page_out_of_range_returns_empty_items(seeded):
    body = seeded.get("/records", params={"page": 99, "page_size": 10}).json()
    assert body["total"] == 5
    assert body["items"] == []


def test_page_zero_rejected(seeded):
    assert seeded.get("/records", params={"page": 0}).status_code == 422


def test_page_size_over_limit_rejected(seeded):
    assert seeded.get("/records", params={"page_size": 101}).status_code == 422


def test_inverted_date_range_returns_400(seeded):
    resp = seeded.get("/records", params={"date_from": "2026-10-01", "date_to": "2026-09-01"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_invalid_query_type_returns_422(seeded):
    assert seeded.get("/records", params={"type": "转账"}).status_code == 422


def test_empty_result_returns_zero_total(client):
    body = client.get("/records", params={"category": "不存在的分类"}).json()
    assert body["total"] == 0 and body["items"] == []


def test_sql_injection_in_category_is_harmless(client):
    """分类里塞 SQL 片段：参数化后用 ? 绑定，只会被当成普通字符串存下来。"""
    payload = "'; DROP TABLE records; --"
    resp = post(client, category=payload)
    assert resp.status_code == 201
    assert resp.json()["category"] == payload
    assert client.get("/records").json()["total"] == 1  # 表还在，数据也在


# ---------------------------------------------------------------- 汇总


def test_summary_math(seeded):
    body = seeded.get("/summary").json()
    assert body["income"] == 5800.0     # 5000 + 800
    assert body["expense"] == 141.5     # 12.5 + 30 + 99
    assert body["balance"] == 5658.5


def test_summary_with_date_range(seeded):
    body = seeded.get("/summary", params={"date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
    assert body["income"] == 5000.0
    assert body["expense"] == 42.5


def test_summary_empty_returns_zeros_not_null(client):
    """无数据时必须是 0，不能是 null —— 前端不用做空值判断。"""
    body = client.get("/summary").json()
    assert body == {"income": 0.0, "expense": 0.0, "balance": 0.0}


def test_summary_inverted_range_returns_400(client):
    resp = client.get("/summary", params={"date_from": "2026-12-01", "date_to": "2026-11-01"})
    assert resp.status_code == 400


# ---------------------------------------------------------------- 并发与一致性


def test_concurrent_writes_do_not_lose_records(seeded):
    """8 线程并发写 24 条：全部成功，且 total 精确等于 5 + 24。"""
    def write(i: int) -> int:
        return post(seeded, amount=float(i + 1), type="支出", category="并发", date="2026-09-20").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(write, range(24)))

    assert codes == [201] * 24
    body = seeded.get("/records", params={"page_size": 100}).json()
    assert body["total"] == 29
    concurrent_amounts = round(sum(item["amount"] for item in body["items"] if item["category"] == "并发"), 2)
    assert concurrent_amounts == round(sum(range(1, 25)), 2)  # 不丢、不重


def test_database_check_constraint_blocks_dirty_write(tmp_path, monkeypatch):
    """绕过 API 直接写库：CHECK 约束必须拦下负金额，证明"双保险"生效。"""
    monkeypatch.setenv("MONEY_DB_PATH", str(tmp_path / "raw.db"))
    from app.database import init_db, new_connection

    init_db()
    conn = new_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO records (amount, type, category, date) VALUES (?, ?, ?, ?)",
                (-5, "收入", "工资", "2026-09-01"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO records (amount, type, category, date) VALUES (?, ?, ?, ?)",
                (5, "转账", "工资", "2026-09-01"),
            )
    finally:
        conn.close()
