# 架构总览

> 面向 10-20 人小团队的多市场量化研究台。后端 FastAPI + Polars + SQLite，前端 Vue 3 + Naive UI + ECharts，AI 模块用 LLM agent + 流式 SSE 跑工具循环。

## 数据流

```
 用户 ── Basic Auth ──▶ FastAPI ──▶ SQLite (meta) + Parquet (price cache)
                          │
                          ├──▶ Polars 表达式编译 ──▶ DSL 执行 ──▶ 回测引擎 ──▶ 指标/曲线
                          │
                          └──▶ LiteAI Agent ──▶ LLM Stream ──▶ 工具 (validate/run/list)
                                                  │
                                                  SSE ──▶ 前端实时渲染
```

## 进程/部署

- 单台腾讯云机器，公网 `http://152.136.209.150:8001`
- `uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 2`
- HTTP Basic Auth，60s auth cache
- GZip middleware（JSON 压 3-5 倍）
- `/assets/*` 加 `Cache-Control: public, max-age=31536000, immutable`
- APScheduler in-process 每日开盘前增量拉数据

## 模块切分

| 路径 | 责任 |
|---|---|
| `app/main.py` | FastAPI 入口、中间件、静态挂载（带长缓存的 `CachedStaticFiles`）|
| `app/config.py` | pydantic-settings 读 `.env` |
| `app/db.py` | SQLite WAL，schema 版本化迁移（当前 v4）|
| `app/scheduler.py` | APScheduler，每日定时调 fetch |
| `app/data/` | A 股 + 美股数据源 → Parquet 缓存 |
| `app/dsl/` | 词法 / 解析 / 白名单 / Polars 表达式编译 |
| `app/engine/` | 回测引擎 + 基准 + 指标 |
| `app/ai/` | LiteAI Agent（多模型 + 工具循环 + 流式）|
| `app/api/` | REST routes（auth / data / backtest / ai / settings）|
| `frontend/` | Vue 3 SPA |

## 数据库 schema (v4)

```
symbols              市场×代码：名称、上市日、状态、缓存统计（rows/min_date/max_date/size_bytes）
trading_calendar     市场×交易日
strategies           保存的策略
backtests            回测记录（dsl + params + metrics + nav_curve）
settings             KV store（存 AI 多模型配置等运行时配置）
chat_sessions        LiteAI 会话历史（per-user）
```

Schema 版本通过 `PRAGMA user_version` 管理；启动时 `init_db()` 检查版本号，按 `_migrate_vN_to_vN+1` 链式自动迁移，避免重建表丢数据。

## 数据存储

- **元数据**：SQLite WAL（`quant.db`），单进程 + 多 worker 安全
- **价格数据**：Parquet 文件，按 `market/symbol.parquet` 切分到 `data_cache/`
  - 优势：列式存储、Polars 直接 lazy-scan、压缩比高（OHLCV 一只股票 5 年 < 100 KB）
  - 增量拉取：比对 `max_date` 决定从哪天开始拉
- **三层防前视偏差**：DSL parser 拒绝 `delay(x, -n)`；executor 在窗口算子里偏移；engine 用 `t+1` 收盘价结算

## 关键约束

- 用户规模 10-20 人 → Basic Auth + workers=2 + 全团队共享策略库/回测库
- 公网部署 → GZip / 长缓存 / 60s auth cache 把成本压到最低
- 小 → 内存里 cache 全 universe 数据，单次回测毫秒级
