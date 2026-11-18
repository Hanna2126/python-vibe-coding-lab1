#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
并发写入验证脚本：多个线程同时对运行中的服务 POST /records，
然后回查 total 与金额合计，确认"不丢、不重、不脏"。

用法（先启动服务）：
    uvicorn app.main:app --port 8000
    python tools/concurrency_check.py --base-url http://127.0.0.1:8000 --count 40 --workers 16
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

CATEGORY = "并发压测"


def build_payload(index: int) -> dict:
    return {
        "amount": float(index + 1),
        "type": "支出" if index % 3 else "收入",
        "category": CATEGORY,
        "date": "2026-09-20",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="并发写入一致性验证")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--count", type=int, default=40, help="并发写入条数")
    parser.add_argument("--workers", type=int, default=16, help="并发线程数")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    expected_sum = round(sum(range(1, args.count + 1)), 2)

    with httpx.Client(timeout=15.0) as probe:
        before = probe.get(f"{base}/records", params={"page_size": 1}).json()["total"]

    def worker(index: int) -> tuple[int, int | None]:
        # 每个线程独立连接，模拟多客户端同时打进来的真实场景
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{base}/records", json=build_payload(index))
            record_id = resp.json().get("id") if resp.status_code == 201 else None
            return resp.status_code, record_id

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(worker, range(args.count)))

    codes = [code for code, _ in results]
    ids = [rid for _, rid in results if rid is not None]

    with httpx.Client(timeout=15.0) as probe:
        after = probe.get(f"{base}/records", params={"page_size": 1}).json()["total"]
        batch = probe.get(f"{base}/records", params={"category": CATEGORY, "page_size": 100}).json()

    ok_codes = codes.count(201)
    batch_sum = round(sum(item["amount"] for item in batch["items"]), 2)
    unique_ids = len(set(ids)) == len(ids)

    print("=" * 46)
    print(f"并发线程数            : {args.workers}")
    print(f"发起写入条数          : {args.count}")
    print(f"返回 201 的条数       : {ok_codes}")
    print(f"写入前 total          : {before}")
    print(f"写入后 total          : {after}")
    print(f"本批记录金额合计      : {batch_sum:,.2f}（期望 {expected_sum:,.2f}）")
    print(f"本批记录 id 是否唯一  : {unique_ids}")
    print("=" * 46)

    problems = []
    if ok_codes != args.count:
        problems.append(f"存在非 201 响应：{sorted(set(codes) - {201})}")
    if after != before + args.count:
        problems.append(f"total 对不上：{before} + {args.count} != {after}")
    if abs(batch_sum - expected_sum) > 0.01:
        problems.append(f"金额合计对不上：{batch_sum} != {expected_sum}")
    if not unique_ids:
        problems.append("出现重复 id")

    if problems:
        for item in problems:
            print(f"[失败] {item}")
        return 1

    print("[通过] 并发写入不丢、不重、不脏")
    return 0


if __name__ == "__main__":
    sys.exit(main())
