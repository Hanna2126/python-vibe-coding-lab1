#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
接口行为实测：把"期望状态码"和"实际状态码"逐条打出来，方便写报告和博客。

用法（先启动服务）：
    uvicorn app.main:app --port 8000
    python tools/api_demo.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json

import httpx

CASES = [
    ("POST", "/records", {"amount": 5000, "type": "收入", "category": "工资", "date": "2026-09-01"}, 201, "新增收入"),
    ("POST", "/records", {"amount": 12.5, "type": "支出", "category": "餐饮", "date": "2026-09-30"}, 201, "新增支出"),
    ("POST", "/records", {"amount": 30, "type": "支出", "category": "交通", "date": "2026-09-15"}, 201, "新增支出"),
    ("POST", "/records", {"amount": 0, "type": "支出", "category": "餐饮", "date": "2026-09-30"}, 422, "金额为 0"),
    ("POST", "/records", {"amount": -1, "type": "支出", "category": "餐饮", "date": "2026-09-30"}, 422, "金额为负"),
    ("POST", "/records", {"type": "支出", "category": "餐饮", "date": "2026-09-30"}, 422, "缺少金额字段"),
    ("POST", "/records", {"amount": "abc", "type": "支出", "category": "餐饮", "date": "2026-09-30"}, 422, "金额类型错误"),
    ("POST", "/records", {"amount": 10, "type": "转账", "category": "餐饮", "date": "2026-09-30"}, 422, "类型非法"),
    ("POST", "/records", {"amount": 10, "type": "支出", "category": "餐饮", "date": "2026-02-30"}, 422, "日期不存在"),
    ("POST", "/records", {"amount": 10, "type": "支出", "category": "餐饮", "date": "2026/9/30"}, 422, "日期格式错误"),
    ("POST", "/records", {"amount": 10, "type": "支出", "category": "   ", "date": "2026-09-30"}, 422, "分类为空白"),
    ("POST", "/records", {"amount": 10, "type": "支出", "category": "餐饮", "date": "2026-09-30", "note": "多传字段"}, 422, "多传未知字段"),
    ("POST", "/records", {}, 422, "空 body"),
    ("GET", "/records?page=0", None, 422, "页码为 0"),
    ("GET", "/records?page_size=101", None, 422, "每页超上限"),
    ("GET", "/records?date_from=2026-10-01&date_to=2026-09-01", None, 400, "日期区间倒置"),
    ("GET", "/records", None, 200, "默认分页查询"),
    ("GET", "/records?type=收入", None, 200, "按类型筛选"),
    ("GET", "/records?category=餐饮", None, 200, "按分类筛选"),
    ("GET", "/records?date_from=2026-09-15&date_to=2026-09-30", None, 200, "按日期区间筛选"),
    ("GET", "/records?page=2&page_size=2", None, 200, "第二页"),
    ("GET", "/summary", None, 200, "全区间汇总"),
    ("GET", "/summary?date_from=2026-09-01&date_to=2026-09-30", None, 200, "9 月汇总"),
]


def brief(resp: httpx.Response, limit: int = 110) -> str:
    text = json.dumps(resp.json(), ensure_ascii=False) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--brief", type=int, default=110, help="响应摘要截断长度")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    failures = 0
    print(f"{'#':<3}{'方法':<6}{'场景':<18}{'期望':<6}{'实际':<6}{'结论':<6}响应摘要")
    print("-" * 118)
    with httpx.Client(base_url=base, timeout=10.0) as client:
        for index, (method, path, payload, expected, label) in enumerate(CASES, start=1):
            if method == "POST":
                resp = client.post(path, json=payload)
            else:
                resp = client.get(path)
            passed = resp.status_code == expected
            failures += 0 if passed else 1
            print(f"{index:<3}{method:<6}{label:<18}{expected:<6}{resp.status_code:<6}{'PASS' if passed else 'FAIL':<6}{brief(resp, args.brief)}")

    print("-" * 118)
    print(f"共 {len(CASES)} 条，未通过 {failures} 条")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
