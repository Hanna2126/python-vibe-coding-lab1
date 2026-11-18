#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
考题一测试：正常流程 1 个 + 边界/异常 7 个。

运行：cd excel_report && pytest -v
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sales_report as sr  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sales_raw.xlsx"
HEADERS = ["日期", "销售员", "产品", "数量", "单价", "地区"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_normal_report_contains_four_sheets_and_correct_totals(tmp_path):
    """正常用例：样例数据一键生成四表报表，金额与人工核对一致。"""
    out = tmp_path / "report.xlsx"
    assert sr.main(["-i", str(SAMPLE), "-o", str(out)]) == 0
    assert out.exists()

    detail = pd.read_excel(out, sheet_name="明细清洗后")
    by_seller = pd.read_excel(out, sheet_name="按销售员")
    by_region = pd.read_excel(out, sheet_name="按地区")
    overview = pd.read_excel(out, sheet_name="总览")

    assert list(detail.columns) == HEADERS + ["销售额"]
    assert len(detail) == 13                                   # 19 行原始数据剔除 6 行
    assert round(detail["销售额"].sum(), 2) == 33870.00        # 人工逐行加总：13200+9600+4900+6170
    assert round(by_seller.iloc[0]["销售额"], 2) == 13200.00    # 张三 10000+800+2400
    assert round(by_region.iloc[0]["销售额"], 2) == 12400.00    # 华东 10000+2400
    assert int(overview.loc[overview["指标"] == "剔除行数合计", "数值"].iloc[0]) == 6
    assert float(overview.loc[overview["指标"] == "销售额总额", "数值"].iloc[0]) == 33870.00


def test_missing_input_file_returns_readable_error(tmp_path, capfd):
    """异常用例 1：文件不存在 → 退出码 2 + 可读提示，不抛裸堆栈。"""
    code = sr.main(["-i", str(tmp_path / "not_exist.xlsx"), "-o", str(tmp_path / "r.xlsx")])
    err = capfd.readouterr().err
    assert code == 2
    assert "找不到输入文件" in err


def test_header_only_file_is_rejected(tmp_path, capfd):
    """异常用例 2：只有表头、没有数据行 → 明确报错。"""
    src = tmp_path / "empty.xlsx"
    pd.DataFrame(columns=HEADERS).to_excel(src, index=False)
    code = sr.main(["-i", str(src), "-o", str(tmp_path / "r.xlsx")])
    assert code == 2
    assert "没有数据行" in capfd.readouterr().err


def test_missing_columns_is_rejected(tmp_path, capfd):
    """异常用例 3：表头缺列 → 报错并列出缺失字段。"""
    src = tmp_path / "bad_header.xlsx"
    pd.DataFrame({"日期": ["2026-09-01"], "销售员": ["张三"]}).to_excel(src, index=False)
    code = sr.main(["-i", str(src), "-o", str(tmp_path / "r.xlsx")])
    assert code == 2
    err = capfd.readouterr().err
    assert "表头缺少必需字段" in err and "产品" in err


def test_all_rows_dirty_raises_no_valid_data(tmp_path, capfd):
    """异常用例 4：全部是脏数据 → 清洗后为空，报错而不是生成空报表。"""
    src = tmp_path / "all_dirty.xlsx"
    pd.DataFrame(
        [
            ("2026-09-01", "张三", "鼠标", 0, 80, "华东"),
            ("2026-09-02", None, "键盘", 5, 200, "华南"),
        ],
        columns=HEADERS,
    ).to_excel(src, index=False)
    code = sr.main(["-i", str(src), "-o", str(tmp_path / "r.xlsx")])
    assert code == 2
    assert "清洗后没有有效数据" in capfd.readouterr().err


def test_source_file_is_never_modified(tmp_path):
    """边界用例：运行前后原始文件哈希不变（只读约束）。"""
    src = tmp_path / "sales_raw.xlsx"
    src.write_bytes(SAMPLE.read_bytes())
    before = digest(src)
    assert sr.main(["-i", str(src), "-o", str(tmp_path / "report.xlsx")]) == 0
    assert digest(src) == before


def test_output_path_must_differ_from_input(tmp_path, capfd):
    """异常用例 5：输出路径与输入相同 → 拒绝执行，避免覆盖原始数据。"""
    src = tmp_path / "sales_raw.xlsx"
    src.write_bytes(SAMPLE.read_bytes())
    code = sr.main(["-i", str(src), "-o", str(src)])
    assert code == 2
    assert "不能与输入路径相同" in capfd.readouterr().err


def test_cleaning_order_and_counts_are_stable(tmp_path):
    """边界用例：清洗计数（缺失3/数量2/重复1）与去重、负数剔除逻辑固定。"""
    df = pd.read_excel(SAMPLE)
    detail, stats = sr.clean(df)
    assert stats.raw_rows == 19
    assert stats.dropped_missing == 3
    assert stats.dropped_bad_qty == 2
    assert stats.dropped_dup == 1
    assert stats.valid_rows == 13
    assert (detail["数量"] > 0).all()
    assert not detail.duplicated().any()
