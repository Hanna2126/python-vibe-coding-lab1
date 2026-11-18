"""Pydantic 请求/响应模型：把"校验规则"集中在一处，路由里不写散装 if。"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MoneyType = Literal["收入", "支出"]


class RecordCreate(BaseModel):
    """POST /records 请求体。

    - extra="forbid"：多传字段直接 422，避免"以为写进去了其实被忽略"；
    - str_strip_whitespace=True：分类首尾空格自动裁掉；
    - amount 用 gt=0（不是 ge=0），0 元流水无业务意义；
    - date 用 date 类型，pydantic 会拒绝 2026-02-30 这种"格式对、日期不存在"的值。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: float = Field(gt=0, allow_inf_nan=False, description="金额，必须大于 0")
    type: MoneyType = Field(description="类型：收入 / 支出")
    category: str = Field(min_length=1, max_length=32, description="分类，如 餐饮、工资")
    date: DateType = Field(description="记账日期，ISO 格式 YYYY-MM-DD")

    @field_validator("category")
    @classmethod
    def category_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分类不能全是空白字符")
        return value


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: float
    type: MoneyType
    category: str
    date: DateType
    created_at: datetime


class RecordsPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[RecordOut]


class SummaryOut(BaseModel):
    income: float
    expense: float
    balance: float
