# Python Vibe Coding 实操 · lab1

> 两个考题的完整落地工程：**考题一 Excel 报表脚本（必做）** + **考题二 FastAPI 记账服务**。
> 评测维度：结果 / 过程 / 验证 / 风险 / 复盘。

## 一、快速开始

```bash
# 0. 建虚拟环境并装依赖
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 考题一：Excel 报表（含脏数据清洗）

```bash
cd excel_report
python data/make_dirty_sample.py     # 生成 19 行样例数据（含 6 行脏数据）
python sales_report.py               # 输出 output/report.xlsx
pytest -v                            # 8 个用例
```

### 考题二：FastAPI 记账服务

```bash
cd fastapi_money_lab1
uvicorn app.main:app --reload        # 打开 http://127.0.0.1:8000/docs
pytest -v                            # 34 个用例
python tools/api_demo.py             # 23 条接口行为实测（需服务已启动）
python tools/concurrency_check.py    # 并发写入一致性验证（需服务已启动）
```

## 二、目录结构

```
python-vibe-coding-lab1/
├── README.md
├── requirements.txt
├── 需求澄清与复盘.md          # 交给 AI 之前写的东西 + 事后复盘
├── 验证记录.md                # 运行 / 测试 / 并发结果留档（可直接截图）
├── blog/
│   ├── Python-Vibe-Coding-lab1.md   # 博客原稿（Markdown，可直接发 CSDN）
│   └── images/                      # 博客里的真实运行截图
├── excel_report/               # 考题一
│   ├── sales_report.py         # 清洗 + 三个维度汇总 + 四表输出
│   ├── data/
│   │   ├── make_dirty_sample.py
│   │   └── sales_raw.xlsx      # 脏样例：空值 / 重复 / 非正数量
│   ├── output/
│   │   └── report.xlsx         # 运行产物：明细清洗后 / 按销售员 / 按地区 / 总览
│   └── tests/
│       └── test_sales_report.py
└── fastapi_money_lab1/         # 考题二
    ├── app/
    │   ├── main.py             # 入口、lifespan 建库、路由挂载
    │   ├── database.py         # SQLite 连接、WAL、busy_timeout、CHECK 约束
    │   ├── schemas.py          # Pydantic 校验规则
    │   ├── errors.py           # 结构化错误体 {error: {code, message, detail}}
    │   ├── validators.py       # 跨路由共用业务校验（日期区间）
    │   └── routers/
    │       ├── records.py      # POST /records、GET /records
    │       └── summary.py      # GET /summary
    ├── tests/
    │   ├── conftest.py         # 每个用例一份独立临时数据库
    │   └── test_api.py         # 34 个用例（正常 + 边界 + 并发 + 注入）
    └── tools/
        ├── api_demo.py         # 期望状态码 vs 实际状态码逐条比对
        └── concurrency_check.py
```

## 三、考题一：报表口径

| 环节 | 口径 |
| --- | --- |
| 关键字段 | 日期、销售员、产品、数量、单价、地区，六列任一为空即整行剔除 |
| 数量异常 | `数量 <= 0` 剔除（0 单、负数、测试数据） |
| 去重 | 六字段全一致才算重复，保留首次出现 |
| 销售额 | `数量 × 单价`，保留两位小数 |
| 输出 | 四个工作表：明细清洗后（含销售额列）/ 按销售员 / 按地区 / 总览 |
| 异常 | 文件不存在、表头缺列、空表、清洗后无有效数据 → 可读报错 + 退出码 2 |
| 只读 | 运行前后对源文件做 SHA-256 比对，内容被改动直接报错 |

样例数据跑出来：原始 19 行 → 剔除 6 行（缺失 3 / 数量异常 2 / 重复 1）→ 有效 13 行，
销售额总额 **33 870.00 元**（张三 13 200 / 李四 9 600 / 赵六 6 170 / 王五 4 900）。

## 四、考题二：接口约定

| 方法 | 路径 | 说明 | 成功 | 失败 |
| --- | --- | --- | --- | --- |
| POST | `/records` | 新增流水 | 201 + 记录 | 422 |
| GET | `/records` | 类型 / 分类 / 日期区间筛选 + 分页 | 200 + `{total,page,page_size,items}` | 400 / 422 |
| GET | `/summary` | 区间收入、支出、结余 | 200 + `{income,expense,balance}` | 400 / 422 |

校验规则：`amount > 0`、`type ∈ {收入, 支出}`、`date` 必须是真实存在的 ISO 日期、`category` 非空白、
`1 ≤ page_size ≤ 100`、`page ≥ 1`、`date_from ≤ date_to`（否则 400）。

错误体统一为：

```json
{"error": {"code": "VALIDATION_ERROR", "message": "...", "detail": [{"loc": ["body","amount"], "msg": "...", "type": "..."}]}}
```

## 五、并发与一致性

- **WAL 模式**：读写不互斥，查询不会被写事务阻塞；
- **busy_timeout=5000**：写锁竞争最多等 5 秒，避免瞬时冲突直接 500；
- **每请求一条连接**：不跨请求持有事务，请求结束即 `close()`；
- **显式事务**：`BEGIN IMMEDIATE` → `INSERT` → `COMMIT`，异常一律 `ROLLBACK`；
- **CHECK 约束兜底**：`CHECK (amount > 0)`、`CHECK (type IN ('收入','支出'))`，绕过 API 也写不进脏数据；
- 实测：16 线程并发写 40 条，40 条全部 201，`total` 精确等于 40，金额合计 820.00 与期望一致。

## 六、技术栈

Python 3.10+ · FastAPI · Pydantic v2 · SQLite（WAL）· pandas · openpyxl · pytest · httpx
