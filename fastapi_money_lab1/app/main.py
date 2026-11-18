"""FastAPI 入口：生命周期内建库、注册结构化错误处理、挂载路由。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .errors import register_error_handlers
from .routers import records, summary


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="简易记账服务",
    version="1.0.0",
    description="Python Vibe Coding lab1 · 考题二：新增 / 查询 / 汇总，SQLite + WAL",
    lifespan=lifespan,
)

register_error_handlers(app)
app.include_router(records.router)
app.include_router(summary.router)


@app.get("/healthz", tags=["运维"], summary="健康检查")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> dict[str, str]:
    return {"service": "简易记账服务", "docs": "/docs", "openapi": "/openapi.json"}
