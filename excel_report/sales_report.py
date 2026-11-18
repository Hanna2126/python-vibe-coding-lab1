#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
考题一：销售报表生成脚本（Python Vibe Coding lab1）

输入：sales_raw.xlsx（字段：日期 / 销售员 / 产品 / 数量 / 单价 / 地区）
输出：report.xlsx（四个工作表：明细清洗后 / 按销售员 / 按地区 / 总览）

设计约束（对应考题"约束"条款）：
1. 只读原始文件，绝不回写；运行前后对源文件做 SHA-256 校验，不一致直接报错；
2. 关键字段缺失、数量<=0、全字段重复的行一律剔除，并统计每类剔除数量；
3. 文件不存在、表头缺列、空表、清洗后无有效数据，都给出可读报错而不是裸堆栈。

用法：
    python sales_report.py                       # 用脚本目录下的默认路径
    python sales_report.py -i data/sales_raw.xlsx -o output/report.xlsx
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE_DIR = Path(__file__).resolve().parent

REQUIRED_COLUMNS = ["日期", "销售员", "产品", "数量", "单价", "地区"]
# 关键字段：六列任一为空即视为脏行（业务口径，人工拍板）
KEY_COLUMNS = REQUIRED_COLUMNS

SHEET_DETAIL = "明细清洗后"
SHEET_BY_SELLER = "按销售员"
SHEET_BY_REGION = "按地区"
SHEET_OVERVIEW = "总览"

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
TOTAL_FONT = Font(name="微软雅黑", size=10, bold=True)
TOTAL_FILL = PatternFill("solid", fgColor="DDEBF7")
THIN = Side(style="thin", color="BFBFBF")
BOX_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY_FORMAT = "#,##0.00"
PCT_FORMAT = "0.00%"
DATE_FORMAT = "yyyy-mm-dd"


class ReportError(Exception):
    """可预期的业务异常：打印可读提示，不输出堆栈。"""


@dataclass
class CleanStats:
    raw_rows: int = 0
    dropped_missing: int = 0
    dropped_bad_qty: int = 0
    dropped_dup: int = 0
    valid_rows: int = 0

    @property
    def dropped_total(self) -> int:
        return self.dropped_missing + self.dropped_bad_qty + self.dropped_dup

    def as_lines(self) -> list[str]:
        return [
            f"原始数据行数      : {self.raw_rows}",
            f"剔除-关键字段缺失 : {self.dropped_missing}",
            f"剔除-数量<=0      : {self.dropped_bad_qty}",
            f"剔除-全字段重复   : {self.dropped_dup}",
            f"清洗后有效行数    : {self.valid_rows}",
        ]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(path: Path) -> pd.DataFrame:
    """读取原始表，先做文件级与表头级校验。"""
    if not path.exists():
        raise ReportError(f"找不到输入文件：{path}（请确认路径，或先用 data/make_dirty_sample.py 生成样例）")
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ReportError(f"仅支持 .xlsx / .xlsm 文件，当前文件后缀为：{path.suffix}")
    if path.stat().st_size == 0:
        raise ReportError(f"输入文件大小为 0 字节，无法读取：{path}")

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as exc:  # openpyxl 抛出的异常类型较杂，这里统一转成业务提示
        raise ReportError(f"文件无法解析，可能已损坏或不是标准 Excel：{path}（{exc}）")

    df.columns = [str(col).strip() for col in df.columns]
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        actual = "、".join(map(str, df.columns)) or "（无表头）"
        raise ReportError(f"表头缺少必需字段：{'、'.join(missing)}；实际表头：{actual}")

    if df.empty:
        raise ReportError("输入文件只有表头、没有数据行，无法生成报表")
    return df


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanStats]:
    """按"缺失 → 数量异常 → 去重"的固定顺序清洗，并记录每一类剔除数量。"""
    stats = CleanStats(raw_rows=len(df))
    work = df[REQUIRED_COLUMNS].copy()

    # 1) 文本列去首尾空白，空白串统一成缺失值，防止 " " 混进有效数据
    for col in ("日期", "销售员", "产品", "地区"):
        work[col] = work[col].astype("string").str.strip().replace("", pd.NA)

    # 2) 数值与日期强制转类型：转不动的变成 NaN/NaT，等价于"脏值"，交给缺失规则处理
    work["数量"] = pd.to_numeric(work["数量"], errors="coerce")
    work["单价"] = pd.to_numeric(work["单价"], errors="coerce")
    work["日期"] = pd.to_datetime(work["日期"], errors="coerce", format="mixed")

    # 3) 关键字段缺失的行整行剔除
    mask_missing = work[KEY_COLUMNS].isna().any(axis=1)
    stats.dropped_missing = int(mask_missing.sum())
    work = work.loc[~mask_missing]

    # 4) 数量 <= 0 的异常行剔除（退款、录错、测试数据都归到这里）
    mask_bad_qty = work["数量"] <= 0
    stats.dropped_bad_qty = int(mask_bad_qty.sum())
    work = work.loc[~mask_bad_qty]

    # 5) 全字段去重（保留首次出现的那一行）
    rows_before_dedup = len(work)
    work = work.drop_duplicates(keep="first")
    stats.dropped_dup = rows_before_dedup - len(work)

    stats.valid_rows = len(work)
    if work.empty:
        raise ReportError(
            "清洗后没有有效数据，无法生成报表（"
            f"原始 {stats.raw_rows} 行，缺失 {stats.dropped_missing} 行，"
            f"数量异常 {stats.dropped_bad_qty} 行，重复 {stats.dropped_dup} 行）"
        )

    # 6) 派生销售额，统一保留两位小数，避免浮点尾差进入汇总
    work["销售额"] = (work["数量"] * work["单价"]).round(2)
    work["日期"] = work["日期"].dt.date
    work = work.sort_values(["日期", "销售员"], kind="stable").reset_index(drop=True)
    return work, stats


def aggregate_by(detail: pd.DataFrame, dimension: str) -> tuple[pd.DataFrame, float]:
    """按某一维度汇总销售额与订单数，并给出占比。"""
    grouped = (
        detail.groupby(dimension, as_index=False)
        .agg(销售额=("销售额", "sum"), 订单数=("销售额", "count"))
        .sort_values(["销售额", dimension], ascending=[False, True])
        .reset_index(drop=True)
    )
    total = round(float(grouped["销售额"].sum()), 2)
    grouped["占比"] = (grouped["销售额"] / total).round(4) if total else 0.0
    grouped["销售额"] = grouped["销售额"].round(2)
    return grouped, total


def build_overview(detail: pd.DataFrame, stats: CleanStats, total: float,
                   sellers: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    first_day = detail["日期"].min().isoformat()
    last_day = detail["日期"].max().isoformat()
    top_seller = sellers.iloc[0]
    top_region = regions.iloc[0]
    drop_ratio = stats.dropped_total / stats.raw_rows if stats.raw_rows else 0.0

    rows = [
        ("原始数据行数", stats.raw_rows),
        ("剔除-关键字段缺失", stats.dropped_missing),
        ("剔除-数量<=0", stats.dropped_bad_qty),
        ("剔除-全字段重复", stats.dropped_dup),
        ("剔除行数合计", stats.dropped_total),
        ("脏数据占比", round(drop_ratio, 4)),
        ("清洗后有效行数", stats.valid_rows),
        ("参与统计的销售员数", int(sellers.shape[0])),
        ("参与统计的地区数", int(regions.shape[0])),
        ("销售额总额", total),
        ("客单价（总额/记录数）", round(total / stats.valid_rows, 2) if stats.valid_rows else 0.0),
        ("销售额最高销售员", f"{top_seller['销售员']}（{top_seller['销售额']:,.2f}）"),
        ("销售额最高地区", f"{top_region['地区']}（{top_region['销售额']:,.2f}）"),
        ("数据日期区间", f"{first_day} ~ {last_day}"),
    ]
    return pd.DataFrame(rows, columns=["指标", "数值"])


def _display_width(text: str) -> int:
    """中文按 2 个字符宽度估算，用于列宽自适应。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def autosize(ws, min_width: int = 10, max_width: int = 42) -> None:
    for idx, column_cells in enumerate(ws.iter_cols(values_only=False), start=1):
        longest = 0
        for cell in column_cells:
            if cell.value is None:
                continue
            if isinstance(cell.value, float):
                text = f"{cell.value:,.2f}"
            else:
                text = str(cell.value)
            longest = max(longest, _display_width(text))
        width = min(max(longest + 4, min_width), max_width)
        ws.column_dimensions[get_column_letter(idx)].width = width


def style_sheet(ws, money_columns: tuple[int, ...] = (), pct_columns: tuple[int, ...] = (),
                date_columns: tuple[int, ...] = (), total_row: int | None = None) -> None:
    """统一表头样式、边框、数字格式；明细/汇总表支持合计行高亮。"""
    max_col = ws.max_column
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=max_col):
        for cell in row:
            cell.font = BODY_FONT
            cell.border = BOX_BORDER
            if isinstance(cell.value, (int, float)):
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in money_columns:
        for row in range(2, ws.max_row + 1):
            ws.cell(row=row, column=col).number_format = MONEY_FORMAT
    for col in pct_columns:
        for row in range(2, ws.max_row + 1):
            ws.cell(row=row, column=col).number_format = PCT_FORMAT
    for col in date_columns:
        for row in range(2, ws.max_row + 1):
            ws.cell(row=row, column=col).number_format = DATE_FORMAT

    if total_row:
        for cell in ws[total_row]:
            cell.font = TOTAL_FONT
            cell.fill = TOTAL_FILL
            cell.border = BOX_BORDER

    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False


def write_report(detail: pd.DataFrame, sellers: pd.DataFrame, regions: pd.DataFrame,
                 overview: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    seller_total_row = len(sellers) + 2
    region_total_row = len(regions) + 2

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        detail.to_excel(writer, sheet_name=SHEET_DETAIL, index=False)
        sellers.to_excel(writer, sheet_name=SHEET_BY_SELLER, index=False)
        regions.to_excel(writer, sheet_name=SHEET_BY_REGION, index=False)
        overview.to_excel(writer, sheet_name=SHEET_OVERVIEW, index=False)

        wb = writer.book
        ws_detail = wb[SHEET_DETAIL]
        style_sheet(ws_detail, money_columns=(5, 7), date_columns=(1,))

        for sheet_name, frame, dim, total_row in (
            (SHEET_BY_SELLER, sellers, "销售员", seller_total_row),
            (SHEET_BY_REGION, regions, "地区", region_total_row),
        ):
            ws = wb[sheet_name]
            style_sheet(ws, money_columns=(2,), pct_columns=(4,))
            # 合计行：让读者一眼看到总额，不用自己加
            ws.cell(row=total_row, column=1, value=f"合计（{len(frame)} 个{dim}）")
            ws.cell(row=total_row, column=2, value=round(float(frame["销售额"].sum()), 2))
            ws.cell(row=total_row, column=3, value=int(frame["订单数"].sum()))
            ws.cell(row=total_row, column=4, value=1.0 if len(frame) else 0.0)
            style_sheet(ws, money_columns=(2,), pct_columns=(4,), total_row=total_row)

        ws_overview = wb[SHEET_OVERVIEW]
        style_sheet(ws_overview, pct_columns=(2,))
        # 总览里混排了字符串与数字，只给数字单元格套金额格式
        for row in range(2, ws_overview.max_row + 1):
            cell = ws_overview.cell(row=row, column=2)
            label = ws_overview.cell(row=row, column=1).value
            if isinstance(cell.value, (int, float)) and label not in ("原始数据行数", "剔除行数合计",
                                                                   "清洗后有效行数", "参与统计的销售员数",
                                                                   "参与统计的地区数"):
                cell.number_format = MONEY_FORMAT

        for ws in (ws_detail, wb[SHEET_BY_SELLER], wb[SHEET_BY_REGION], ws_overview):
            autosize(ws)

    # 打开校验：确认四个 sheet 都在，避免"写出去了但打不开"
    wb_check = load_workbook(output, read_only=True)
    got = wb_check.sheetnames
    wb_check.close()
    if got != [SHEET_DETAIL, SHEET_BY_SELLER, SHEET_BY_REGION, SHEET_OVERVIEW]:
        raise ReportError(f"报表工作表写入异常，期望四个 sheet，实际为：{got}")


def run(input_path: Path, output_path: Path) -> int:
    if not input_path.exists():
        raise ReportError(f"找不到输入文件：{input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ReportError("输出路径不能与输入路径相同（禁止覆盖原始数据）")

    source_hash = sha256_of(input_path)
    raw = load_raw(input_path)
    detail, stats = clean(raw)
    total = round(float(detail["销售额"].sum()), 2)
    sellers, seller_total = aggregate_by(detail, "销售员")
    regions, region_total = aggregate_by(detail, "地区")
    overview = build_overview(detail, stats, total, sellers, regions)

    if abs(seller_total - total) > 0.01 or abs(region_total - total) > 0.01:
        raise ReportError(
            f"汇总校验失败：明细总额 {total}，按销售员 {seller_total}，按地区 {region_total}，请检查聚合逻辑"
        )

    write_report(detail, sellers, regions, overview, output_path)

    if sha256_of(input_path) != source_hash:
        raise ReportError("原始文件内容在运行过程中被改动，违反只读约束，请立即排查")

    print("=" * 46)
    print("清洗过程")
    print("=" * 46)
    for line in stats.as_lines():
        print("  " + line)
    print("=" * 46)
    print(f"销售额总额 : {total:,.2f}")
    print(f"报表已输出 : {output_path}")
    print(f"原始文件哈希未变化 : {source_hash[:16]}…")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="读取销售原始表，清洗并生成四表报表")
    parser.add_argument("-i", "--input", default=str(BASE_DIR / "data" / "sales_raw.xlsx"),
                        help="原始表路径（默认 data/sales_raw.xlsx）")
    parser.add_argument("-o", "--output", default=str(BASE_DIR / "output" / "report.xlsx"),
                        help="报表输出路径（默认 output/report.xlsx）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(Path(args.input).expanduser(), Path(args.output).expanduser())
    except ReportError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"[错误] 无权限读写文件：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
