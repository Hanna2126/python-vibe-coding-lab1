"""pytest 公共夹具：每个用例一份独立临时数据库，互不污染。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """环境变量指向临时库；TestClient 作为上下文管理器会触发 lifespan 建表。"""
    monkeypatch.setenv("MONEY_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client
