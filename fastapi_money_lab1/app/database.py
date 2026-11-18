"""SQLite 连接管理、建表与并发相关 PRAGMA 设置。

并发设计要点：
1. WAL 模式：读写不互斥，读操作不会被写事务阻塞；
2. busy_timeout=5000：写锁竞争时最多等 5 秒，避免瞬时冲突直接抛 "database is locked"；
3. 每个请求独立连接、用完即关，不跨请求持有事务；
4. 数据库层 CHECK 约束兜底，即使应用层漏校验也写不进脏数据。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "money.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    amount     REAL    NOT NULL CHECK (amount > 0),
    type       TEXT    NOT NULL CHECK (type IN ('收入', '支出')),
    category   TEXT    NOT NULL CHECK (length(trim(category)) > 0),
    date       TEXT    NOT NULL CHECK (length(date) = 10),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_records_date     ON records (date);
CREATE INDEX IF NOT EXISTS idx_records_type     ON records (type);
CREATE INDEX IF NOT EXISTS idx_records_category ON records (category);
"""


def db_path() -> Path:
    """允许用环境变量切换数据库文件，测试时每个用例一份独立库。"""
    raw = os.getenv("MONEY_DB_PATH")
    return Path(raw) if raw else DEFAULT_DB_PATH


def new_connection() -> sqlite3.Connection:
    # check_same_thread=False：FastAPI 的同步依赖在线程池里执行，连接的创建与关闭
    # 可能落在不同线程；每个请求独占一条连接，不做跨请求共享，因此这里放开线程检查是安全的。
    conn = sqlite3.connect(str(db_path()), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    """服务启动时执行一次：切 WAL、建表与索引。"""
    conn = new_connection()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def get_connection() -> Iterator[sqlite3.Connection]:
    """FastAPI 依赖：请求进来开连接，请求结束一定关闭。"""
    conn = new_connection()
    try:
        yield conn
    finally:
        conn.close()
