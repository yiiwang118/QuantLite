# Quant Lite — 技术报告

> 一份面向 10-20 人小团队的多市场量化策略研究台。自然语言 → DSL → 回测 → 结论，一条龙。
>
> 公网部署：`http://152.136.209.150:8001`
> 仓库：`https://github.com/yiiwang118/QuantLite`

---

## 目录

1. [项目概述](#一项目概述)
2. [系统架构](#二系统架构)
3. [数据层](#三数据层)
4. [DSL 因子语言](#四dsl-因子语言)
5. [回测引擎](#五回测引擎)
6. [LiteAI Agent](#六liteai-agent)
7. [前端架构](#七前端架构)
8. [API 设计](#八api-设计)
9. [部署与运维](#九部署与运维)
10. [测试](#十测试)
11. [演进历程](#十一演进历程)
12. [待办与展望](#十二待办与展望)

---

## 一、项目概述

### 1.1 定位

为小团队（10-20 人）量化研究员提供一个 **自然语言驱动** 的策略研究 + 回测平台。研究员不需要每次都自己写 Python，可以让 LiteAI（内嵌 LLM Agent）帮忙：

- 把策略描述翻译成可执行的 DSL
- 自动校验、跑回测、对照基准
- 解读结果（夏普、回撤、超额）

DSL + 回测引擎是基座，LiteAI 是基座之上的"研究员副驾驶"。**所有人都用同一份数据、同一套引擎、同一份策略库**，避免小团队各自一份 Excel/Notebook 的碎片化。

### 1.2 用户与规模

| 维度 | 量级 |
|---|---|
| 团队规模 | 10-20 人 |
| 用户访问模式 | 公网 + Basic Auth |
| 数据规模 | A 股 + 美股，当前 cached ~140 只样本，可扩 300+100 |
| 单次回测耗时 | 毫秒级（数据全 in-memory，Polars 列式）|
| 并发请求 | uvicorn workers=2 + SQLite WAL |

### 1.3 部署形态

腾讯云单机部署，公网可访问：

```
http://152.136.209.150:8001
├─ HTTP Basic Auth（60s 内存缓存）
├─ uvicorn workers=2
├─ GZip middleware
├─ /assets/* Cache-Control: immutable, max-age=1 year
└─ /api/* + SPA fallback (Vue Router)
```

启停脚本：`scripts/start_server.sh` / `scripts/stop_server.sh`（PID 文件 + nohup）。

---

## 二、系统架构

### 2.1 系统组成

```
┌─────────────────────────────────────────────────────────────────┐
│                       浏览器（Vue 3 SPA）                         │
│   ├─ LiteAI 聊天（流式 SSE） ├─ DSL 编辑 ├─ 回测可视化              │
│   ├─ 主题切换（CSS vars 直写）├─ i18n（zh/en）├─ 移动端适配          │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS Basic Auth
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                          FastAPI 后端                             │
│   ├─ routes_data       (symbols / overview / fetch)              │
│   ├─ routes_backtest   (validate / backtest / strategies / ...)  │
│   ├─ routes_ai         (chat / chat/stream / sessions / status)  │
│   ├─ routes_settings   (ai 多模型配置)                            │
│   └─ middlewares: GZip + CORS + CachedStaticFiles                │
└────┬──────────────────────┬──────────────────────┬──────────────┘
     │                      │                      │
     ▼                      ▼                      ▼
  SQLite               Parquet 文件             LLM 网关
  (元数据, WAL)        (data_cache/daily/      (Anthropic /
   6 张表              <market>/<symbol>.       OpenAI 兼容,
                       parquet)                 支持 stream)
```

### 2.2 数据流（用户视角）

**1. 自然语言对话**：用户描述策略 → 浏览器 POST `/api/ai/chat/stream`

**2. SSE 流式返回**：后端启 worker 线程跑 agent loop，每个事件（thinking / tool_call / final_message）通过 `asyncio.Queue` 桥接到 SSE generator 推送给前端

**3. LLM 工具调用**：
   - `validate_dsl(dsl)` → DSL parser 校验
   - `run_backtest(dsl)` → 加载 Parquet → Polars 表达式编译 → 回测引擎 → 指标
   - `list_universes() / list_saved_strategies()` → 查 SQLite

**4. 自动写回**：DSL → Lab 的编辑器，回测结果 → 净值曲线 + 指标卡片

**5. 会话保存**：每轮对话结束自动 PUT 到 SQLite `chat_sessions`，per-user 隔离

### 2.3 模块切分

| 路径 | 责任 |
|---|---|
| `app/main.py` | FastAPI 入口、中间件链、静态挂载（含长缓存的 `CachedStaticFiles`） |
| `app/config.py` | pydantic-settings 读 `.env` |
| `app/db.py` | SQLite WAL，schema 版本化（当前 v4），含 6 张表 CRUD |
| `app/scheduler.py` | APScheduler 进程内调度，每日开盘前增量拉数据 |
| `app/data/` | 数据源（akshare A 股 + 美股）、Parquet 缓存管理、universe 注册 |
| `app/dsl/` | 词法 / parser / 白名单 / Polars 表达式编译 |
| `app/engine/` | 回测引擎 + 指标 + 基准 |
| `app/ai/` | LiteAI Agent 主循环（多模型 + 工具 + 流式）|
| `app/api/` | REST + SSE routes，统一 auth dependency |
| `frontend/src/` | Vue 3 SPA：views / components / stores / i18n / theme-vars |

---

## 三、数据层

### 3.1 存储设计

**双层存储**：
- **元数据** → SQLite WAL，单文件 `quant.db`，元数据 + 配置 + 会话历史
- **价格数据** → Parquet 文件，按 `market/symbol.parquet` 切分，列式 + 压缩

**为什么不全 SQLite**？OHLCV 数据列式访问更高效，Polars 直接 lazy-scan Parquet 无需序列化反序列化。一只股票 5 年日线压缩后 < 100 KB，全 universe 400 只总共 < 30 MB，可直接 in-memory 计算。

**为什么不全 Parquet**？元数据需要事务、唯一约束、关联查询（strategies ↔ backtests）；SQLite WAL 模式同时支持多 worker 安全读写。

### 3.2 SQLite Schema（v4，6 张表）

```sql
-- 股票元数据 + 缓存统计（避免每次列表读 Parquet 头）
symbols(
  market TEXT, symbol TEXT, name TEXT,
  list_date TEXT, status TEXT, last_fetched_at TEXT,
  rows INT, min_date TEXT, max_date TEXT, size_bytes INT,
  PRIMARY KEY (market, symbol)
)

-- 各市场交易日
trading_calendar(market TEXT, date TEXT, PRIMARY KEY (market, date))

-- 保存的 DSL 策略
strategies(
  id PK, name UNIQUE, dsl TEXT, created_by TEXT,
  created_at, updated_at
)

-- 回测记录
backtests(
  id PK, strategy_id FK, dsl TEXT,
  params JSON, metrics JSON, nav_curve JSON,
  duration_ms INT, created_by TEXT, created_at
)

-- KV 配置（主要存 AI 多模型配置 ai.config）
settings(key PK, value TEXT, updated_at, updated_by)

-- LiteAI 会话历史（per-user 隔离）
chat_sessions(
  id TEXT PK, user TEXT, title TEXT,
  messages JSON, created_at, updated_at
)
CREATE INDEX idx_chat_sessions_user_updated
  ON chat_sessions(user, updated_at DESC);
```

### 3.3 Schema 版本与迁移

`PRAGMA user_version` 管理版本号，启动时 `init_db()`：

```
v0 (空) → 直接建 SCHEMA_V1_FRESH 全套表 → version = 4
v1 → migrate v1→v2→v3→v4
v2 → migrate v2→v3→v4
v3 → migrate v3→v4
v4 → 不动
v > 4 → 拒绝启动（不兼容降级）
```

迁移函数 `_migrate_vN_to_vN+1` 各自幂等：
- v1→v2：给 `symbols` 加 4 列（rows / min_date / max_date / size_bytes）
- v2→v3：建 `settings` 表
- v3→v4：建 `chat_sessions` 表 + 索引

### 3.4 Parquet 组织

```
data_cache/
├── daily/
│   ├── cn/
│   │   ├── 000001.parquet      # 平安银行
│   │   ├── 000002.parquet
│   │   └── ...
│   └── us/
│       ├── AAPL.parquet
│       └── ...
├── _meta.json                   # 全局元信息（schema 版本、初始化时间、压缩算法）
└── .lock/                       # 文件锁，避免并发写
```

Parquet schema 由 `app/data/__init__.py` 的 `UNIVERSE_SCHEMA` 锁死：

```python
UNIVERSE_SCHEMA = {
  "date": Date, "market": Utf8, "symbol": Utf8,
  "open": Float64, "high": Float64, "low": Float64, "close": Float64,
  "volume": Int64, "amount": Float64,
}
```

下游 import 这个常量做断言，schema 变更走版本号 + 强制清缓存。

### 3.5 增量拉取

`fetch_and_cache(market, symbol)`：
1. 查 SQLite `symbols.max_date` 拿最后日期
2. 调 akshare 从 `max_date + 1` 拉到今天
3. 拼接旧 Parquet 写新 Parquet
4. update SQLite stats（rows / min/max date / size_bytes）

retry：`@with_retry(max_attempts=3, base_delay=...)` 装饰器，指数退避。
fallback：A 股 em 失败回退到 sina，美股 em 失败回退到 yfinance（接口适配在 `app/data/sources/`）。

### 3.6 调度（APScheduler in-process）

`app/scheduler.py` 在 FastAPI lifespan 启动时起 APScheduler：
- 工作日开盘前 08:30 拉 A 股
- 美股收盘后 09:00（北京时间）拉美股
- 历次执行结果写 `data_cache/_schedule_runs.json`（前端 DataOps 页面可见 next_run + last_run 状态）

`Process within process`，不引入额外服务，工作量小但够小团队场景用。

### 3.7 命名 universe

`app/data/__init__.py` 维护 `NAMED_UNIVERSES`：

| Universe | 数量 | 数据来源 |
|---|---|---|
| `cn:sample` | 10 | 手挑大白马（茅台/平安/五粮液/...） |
| `cn:hs50` | 50 | 沪深 50 大盘股 |
| `cn:csi300` | 300 | 沪深 300 完整成分（akshare 实时拉） |
| `us:sample` | 10 | 手挑（AAPL/MSFT/GOOG/...） |
| `us:sp50` | 50 | 标普 50 头部 |
| `us:nasdaq100` | 100 | 纳斯达克核心科技 + 消费 + 医药 |

DSL 引用 `universe: cn:csi300` 时，engine 通过 `get_universe(name)` 拿到 `[(market, symbol), ...]` 加载所有 Parquet 拼成 wide DataFrame。

---

## 四、DSL 因子语言

### 4.1 设计目标

**让 LLM 写得对、引擎执行快、研究员看得懂**。

- 语法极简：因子定义 + 策略块，递归下降 parser 一遍过
- 算子白名单：避免任意计算的安全风险，也方便 LLM 学习（system prompt 列全集）
- 编译期防错：字段、算子、窗口、字段名全做静态检查

### 4.2 语法

```
program = factor_def* strategy?

factor_def = "factor" IDENT "=" expr

strategy = "strategy" "{"
    field ":" value
    ...
"}"

field = universe | signal | select | rebalance | cost | start | end

select = "top" NUMBER ("bottom" NUMBER)?

expr = NUMBER
     | IDENT                          # field 或 已定义 factor
     | "-" expr
     | expr ("+"|"-"|"*"|"/") expr
     | OPERATOR "(" expr ("," expr)* ")"
```

### 4.3 18 个算子（4 类）

| 类别 | 算子 | 签名 | 备注 |
|---|---|---|---|
| 时序窗口 | `delay/ma/std/sum/max_ts/min_ts` | `(x, n)` | 第 2 参数 n 是窗口长度 |
| 时序排序/位置 | `ts_argmax/ts_argmin/ts_rank/decay_linear` | `(x, n)` | `ts_rank` 返回 0-1 百分位 |
| 时序双参 | `corr` | `(x, y, n)` | 滚动皮尔逊相关，n 是窗口 |
| 时序单参 | `returns` | `(x)` | 单期收益 = x_t / x_{t-1} - 1 |
| 横截面 | `rank/zscore` | `(x)` | 当日全 universe 截面 |
| 数学 | `abs/log/sign` | `(x)` | 逐元素 |

**关键约束**：所有 `(x, n)` 系列里 `n` 必须是**非负整数常量**。Parser 静态检查，禁止 `delay(close, n-1)` 这种动态窗口（也是防前视偏差的入口）。

### 4.4 字段白名单

```python
FIELDS = frozenset({
    "open", "high", "low", "close", "volume", "amount", "vwap",
})
```

引用未在白名单内的字段 → parser 直接抛 `DSLError` 带行列号。这条规则同时是 LiteAI prompt 的内容，从 `wl.FIELDS` 动态注入，**单一来源**。

### 4.5 三层防前视偏差

| 层 | 位置 | 防御方式 |
|---|---|---|
| **1. Parser** | `app/dsl/parser.py` | 窗口 `n` 必须是非负整数常量，禁止 `delay(close, -1)` |
| **2. Executor** | `app/dsl/executor.py` | 所有时序算子翻译为 `pl.col("close").shift(n)`（n > 0 表示 t-n 时刻的值），不允许 future-looking |
| **3. Engine** | `app/engine/backtest.py` | T+0 信号选股，T+1 close 结算：`next_ret(s, t) = close(s, t+1) / close(s, t) - 1` |

第 1 层是编译时静态检查；2 层是因子计算时只能向后偏移；3 层是结算时持仓收益用下一日收盘价。**任何一层都能独立阻断前视偏差**，纵深防御。

### 4.6 编译流程

```
DSL 字符串
    │
    ▼  Lexer (app/dsl/lexer.py)
Token 流
    │
    ▼  Parser (app/dsl/parser.py，递归下降)
AST (FactorDef / Strategy / Expr)
    │
    ▼  Whitelist 校验 (字段 + 算子 + 策略字段)
合法 AST
    │
    ▼  Executor (app/dsl/executor.py)
Polars 表达式 pl.Expr
    │
    ▼  evaluate(program, df) — df 是 (date, market, symbol, ohlcv) 长表
带 __signal__ 列的 DataFrame
    │
    ▼  Engine 接管
```

`pl.Expr.over("symbol")` 实现 panel data 的 group-by 算子（每个 symbol 自己做时序）。横截面算子（`rank`/`zscore`）用 `pl.Expr.over("date")`。

---

## 五、回测引擎

### 5.1 输入输出

**输入**：
- `Program`（含 `Strategy`）：定义 universe、signal、select、rebalance、cost、start、end
- `df: pl.DataFrame`：长表 `(date, market, symbol, ohlcv, ...)`

**输出**：`BacktestResult` dataclass，关键字段：

```python
@dataclass
class BacktestResult:
    nav_curve: list[(date_iso, nav)]        # 策略净值
    benchmark_curve: list[(date_iso, nav)]  # 基准（同 universe 等权全持）
    metrics: dict                            # cum_return / annual_return / sharpe / max_drawdown / win_rate / annual_vol
    benchmark_metrics: dict
    excess_return: float                     # 策略累计 - 基准累计
    rebalance_dates: list[date_iso]
    holdings_history: dict[date_iso, list[str]]  # "L:cn/600519" 或 "S:cn/000001"
    duration_ms: int
    rows_used: int
    universe: str
    top_n: int
    bottom_n: int                            # 0 = 仅多头
    rebalance: str
    cost: float
    total_cost: float                        # 累计扣除的成本比例
    start: str | None
    end: str | None
```

### 5.2 调仓主循环

```python
nav = 1.0
total_cost = 0.0
longs, shorts = [], []

for d in all_dates:
    if d in rebalance_set:
        new_longs, new_shorts = select_holdings(df, d, top_n, bottom_n)
        # turnover-based cost
        long_to  = turnover(longs, new_longs)
        short_to = turnover(shorts, new_shorts) if bottom_n > 0 else 0
        avg_to   = (long_to + short_to) / 2 if bottom_n > 0 else long_to
        cost_drag = avg_to * cost * 2   # 双边
        nav *= (1.0 - cost_drag)
        total_cost += cost_drag
        longs, shorts = new_longs, new_shorts

    # 当日组合收益 = 多头等权 - 空头等权
    port_ret = equal_weight_ret(d, longs) - equal_weight_ret(d, shorts)
    nav *= (1.0 + port_ret)
    nav_curve.append((d.isoformat(), nav))
```

### 5.3 Long-short 选股

```python
# select: top N bottom M
day_df = df.filter(date == d, signal not null).sort(signal, desc=True)
longs  = day_df.head(top_n)    # 信号最高的 N 只
shorts = day_df.tail(bottom_n)  # 信号最低的 M 只（仅当 M > 0）
```

PnL：`long_ret − short_ret`（market-neutral 思路，实测可消除大盘 beta）。

注意：基准始终是 long-only 等权全持 universe，给一个**绝对收益参考**。超额收益 = 策略 cum − 基准 cum。

### 5.4 交易成本模型

```python
turnover_one_way = 1 − |old ∩ new| / max(|old|, |new|)
# 等权下，等价于"新换股 / 持仓数"

cost_drag_per_rebalance = turnover_one_way × cost × 2
```

- `× 2`：买入 + 卖出双边
- `cost` 字段单位：单边费率（如 `0.001` = 10 bps）
- 首次建仓：`turnover = 1.0`（卖出空仓 = 0，所以单纯按"买入全仓"算 100%）
- 多空模式：取多空 turnover 平均

A 股推荐 `cost: 0.0015`（佣金 + 印花税平均）；美股 `cost: 0.0005`。LiteAI 默认建议 `0.001`。

### 5.5 指标

```python
nav_curve = [1.0, 1.005, 1.012, ...]
ret_series = pct_change(nav_curve)         # 每日 returns

cum_return    = nav_curve[-1] - 1
annual_return = (1 + cum_return) ** (252 / N_days) - 1
annual_vol    = std(ret_series) * sqrt(252)
sharpe        = annual_return / annual_vol
max_drawdown  = max((peak - trough) / peak)
win_rate      = (ret > 0).sum() / len(ret)
```

### 5.6 基准

策略要可比，基准必须明确：

```python
# 等权持有全 universe，每日（理论上）再平衡
daily_mean_ret = df.group_by("date").agg(pl.col("next_ret").mean())
benchmark_nav  = cumprod(1 + daily_mean_ret)
```

不扣 cost，因为基准是"被动 buy & hold"参考。所有 `excess_return` 都是 cost-adjusted 策略 vs 无成本基准。

---

## 六、LiteAI Agent

### 6.1 设计理念

**Tool-using LLM Agent**：LLM 自己决定何时调工具，agent 主循环最多跑 `max_iters = 6` 轮。每轮：

1. 调 LLM（带 system prompt + 历史 messages + 工具定义）
2. 如果返回 `tool_calls` → 执行工具 → 把结果 append 到 messages → 进入下一轮
3. 如果返回 `final_message` / `stop` → 结束

整个过程**流式**：每个 token 生成、每个工具调用启动/结束都通过 SSE 推到前端，用户能看到模型"边想边做"。

### 6.2 多模型 + 双协议

支持 **OpenAI 兼容**（DeepSeek / Moonshot / GPT / GLM / Qwen 等）+ **Anthropic Messages**（Claude）。每个模型一份配置：

```json
{
  "id": "abc123",
  "label": "DeepSeek V4 Pro",
  "format": "openai",          // or "anthropic"
  "api_key": "sk-xxx",
  "model_id": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com"   // 可选，留空走官方
}
```

配置整体存 SQLite `settings` 表的 `ai.config` key（JSON）。前端 GET 时 api_key 自动 mask 为 `sk-xxx****`；POST 时 `""` 或 `"***"` 表示保留原值（避免改其他字段不小心覆盖 key）。

### 6.3 工具系统

4 个工具：

| 工具 | 参数 | 用途 |
|---|---|---|
| `validate_dsl` | `dsl: str` | 校验 DSL 语法，返回错误位置（行号 + 列号 + 消息）|
| `run_backtest` | `dsl: str` | 真跑回测，返回 metrics + 基准对照（裁剪版给 LLM 看，完整版存到 ctx 给前端用）|
| `list_universes` | (无) | 列可用股票池 |
| `list_saved_strategies` | (无) | 列已保存策略 |

**给 LLM 的返回 vs 给前端的返回**：
- 给 LLM：裁剪到最关键的指标 + 错误信息，省 token
- 给前端：完整 `backtest_result`（含 nav_curve / benchmark_curve / holdings_history），存到 `AgentContext.backtest_result_full`，agent 结束后从 ctx 取出回前端

工具定义同时翻译成 Anthropic 和 OpenAI 两份 schema：

```python
def tools_for_anthropic() -> list[dict]:
    return [{"name": "validate_dsl", "description": "...", "input_schema": {...}}, ...]

def tools_for_openai() -> list[dict]:
    return [{"type": "function", "function": {"name": "validate_dsl", ...}}, ...]
```

### 6.4 流式 SSE

`POST /api/ai/chat/stream` 返回 `text/event-stream`，事件类型：

| 事件 | 数据 | 前端处理 |
|---|---|---|
| `started` | `{model: {id, label, ...}}` | 显示选中模型标签 |
| `thinking` | `{iteration: n}` | 新一轮 LLM 调用开始，清空 thinking 文字 + 重置计时 |
| `thinking_text` | `{text, iteration}` | 累积的文字（含 reasoning + content），增量更新展示 |
| `tool_call_start` | `{id, name, input, iteration}` | 工具调用气泡（旋转 icon） |
| `tool_call_end` | `{id, name, result, iteration}` | 工具气泡变 ✓ 或 ✗，可展开看 input/result |
| `final_message` | `{text}` | 最终 assistant 文字 |
| `done` | `{result: {..., dsl, backtest_result, tool_calls, duration_ms}}` | 整轮完成，把 DSL 写回编辑器 + 回测结果写回展示区 |
| `error` | `{error: str}` | 失败提示 |

后端实现：worker 线程跑 agent，`on_event` callback 把事件丢到 `asyncio.Queue`，async generator 从 queue 拿事件 yield 出去。心跳 10s 一次 `: heartbeat\n\n` 防代理超时：

```python
def on_event(event):
    loop.call_soon_threadsafe(queue.put_nowait, event)  # 线程安全

async def producer():
    result = await asyncio.to_thread(ai.chat, text, model, user, on_event)
    await queue.put({"type": "done", "result": result})
    await queue.put(SENTINEL)

async def event_gen():
    asyncio.create_task(producer())
    while True:
        try:
            ev = await asyncio.wait_for(queue.get(), timeout=10.0)
        except asyncio.TimeoutError:
            yield ": heartbeat\n\n"
            continue
        if ev is SENTINEL: break
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
```

### 6.5 LLM 流式调用

**OpenAI 协议**（`stream=True`）：

```python
stream = client.chat.completions.create(..., stream=True)
content_buf = ""
reasoning_buf = ""
tool_calls_acc: list[dict] = []   # 按 index 累积

for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        content_buf += delta.content
        emit("thinking_text", text=compose(reasoning_buf, content_buf))
    if getattr(delta, "reasoning_content", None):
        reasoning_buf += delta.reasoning_content
        emit("thinking_text", text=compose(reasoning_buf, content_buf))
    if delta.tool_calls:
        # tool_calls 是分片来的，arguments 按 index 拼接
        for tc in delta.tool_calls:
            acc = tool_calls_acc[tc.index] or new_empty()
            if tc.function.name: acc.name += tc.function.name
            if tc.function.arguments: acc.args += tc.function.arguments
```

**Anthropic 协议**：

```python
with client.messages.stream(...) as stream:
    for ev in stream:
        if ev.type == "content_block_delta" and ev.delta.type == "text_delta":
            text_buf += ev.delta.text
            emit("thinking_text", text=text_buf)
    final = stream.get_final_message()
    # final.content 含 tool_use blocks
```

### 6.6 DeepSeek-reasoner 适配

DeepSeek-reasoner 等推理模型有 `reasoning_content` 字段（非标准 OpenAI 扩展）：

1. **流式取**：`delta.reasoning_content` 先于 `delta.content` 流出，单独累积
2. **前端渲染**：用 `> 推理过程：` blockquote 套在 content 上方
3. **必须回传**：下一轮 API 调用时把 `reasoning_content` 一并发回，否则报错 `The reasoning_content in the thinking mode must be passed back to the API`

```python
asst_msg = {
    "role": "assistant",
    "content": content_buf,
    "tool_calls": [...],
}
if reasoning_buf:
    asst_msg["reasoning_content"] = reasoning_buf   # 关键
messages.append(asst_msg)
```

### 6.7 会话历史

`chat_sessions` 表 per-user 隔离。所有 endpoint 都 `WHERE user = ?`：

| Endpoint | 用途 |
|---|---|
| `GET /api/ai/sessions` | 列当前用户的会话（仅元数据） |
| `POST /api/ai/sessions` | 创建（id = `secrets.token_urlsafe(9)`，title 取首条 user 消息前 30 字） |
| `GET /api/ai/sessions/{id}` | 拿完整 messages |
| `PUT /api/ai/sessions/{id}` | 更新 messages + 可选 title |
| `DELETE /api/ai/sessions/{id}` | 删 |

前端流程：发完一条消息 → 流式完成 → `finally` 调 `persistSession()`：
- 没 `currentSessionId` → POST 创建，存 id
- 有 → PUT 整个 messages

### 6.8 System prompt

运行时拼装（不写死在文件），字段/算子从 `wl.FIELDS` / `wl.OPERATORS` 动态注入，**单一来源**：

```
你是 Quant Lite 的量化研究助手 / Agent...

# DSL 语法
...

# 字段白名单
{fields}

# 算子白名单（{len(wl.OPERATORS)} 个）
...

# 规则
- 字段/算子只能用白名单里的
- 多空策略：top N bottom M，PnL = long − short
- 交易成本默认推荐 cost: 0.001

# 工具
你有 4 个工具：...

# 工作流程
1. 用户给一句话需求 → 你写一份 DSL
2. 调用 validate_dsl 确认无语法错误
3. 如果用户要求跑回测，调用 run_backtest
4. 用中文总结结果

# 重要
- 用中文回答
- 工具返回 ok:false 时，根据错误信息修正 DSL 再试一次
```

---

## 七、前端架构

### 7.1 技术栈

- Vue 3.5 + Vite 6 + TypeScript
- Naive UI 2.40（按需导入 via `unplugin-vue-components`）
- ECharts 5（净值曲线 / K 线 / Sparkline）
- Pinia（auth / data stores）
- vue-router 4
- vue-i18n 11（zh / en 双语）
- marked + DOMPurify（Markdown 渲染 + 防 XSS）

### 7.2 路由 + KeepAlive

```
/lab                LiteAI 首页（聊天 + DSL 编辑 + 回测结果）
/dashboard          概览
/symbols            股票列表
/symbols/:m/:s      股票详情（K 线 + 日线表）
/strategies         策略库
/backtests          回测历史
/backtests/:id      回测详情（重定向到 /lab?backtest_id=X）
/data               数据操作
/settings           AI 模型 + 系统设置
```

`<KeepAlive :max="10">` 缓存所有 view，切回时不重新 mount。`onActivated` hook 用来在切回时拉新数据（AI 模型 / 会话历史 / 策略库等可能在其他页被改过的状态）。

### 7.3 主题系统

**关键设计：JS 直接 `setProperty` 写 CSS variables 到 documentElement.style**。

```typescript
// frontend/src/theme-vars.ts
export const LIGHT_VARS = {
  '--bg-base': '#f5f6fb',
  '--card-bg': '#ffffff',
  '--surface-1': '#f8f9fd',
  '--text-primary': '#0f172a',
  // ... 约 30 个变量
}
export const DARK_VARS = { /* 对应 dark 值 */ }

export function applyTheme(isDark: boolean) {
  const root = document.documentElement
  for (const [k, v] of Object.entries(isDark ? DARK_VARS : LIGHT_VARS)) {
    root.style.setProperty(k, v)
  }
  root.classList.toggle('dark', isDark)
  root.style.colorScheme = isDark ? 'dark' : 'light'
}
```

**为什么不用 `:root.dark { ... }` class cascading**？踩过坑：

1. Naive UI `<NGlobalStyle />` 会运行时注入 `<style>` 到 `<head>`，包括 `body { background-color: var(--xxx) }`
2. 该 `<style>` 的 source order 比 vite 打包的 style.css 晚 → 盖掉我设的 body bg
3. 加上 Naive 用户设的 `common.bodyColor: transparent` → body 实际透明 → 透出 macOS dark mode 的浏览器默认色（黑色）→ 看起来 light 模式没生效

**解决方案**：
- 去掉 `<NGlobalStyle />`，自己掌控 body 样式
- CSS vars 用 JS `setProperty` 直写 inline style，**inline 优先级最高**，绕过所有 class/cascade race

### 7.4 性能优化

#### Bundle 拆分

`vite.config.ts` 的 `manualChunks` 按依赖拆 6 个 vendor chunk：

| Chunk | 内容 | gzip size |
|---|---|---|
| `vendor-vue` | vue + vue-router + pinia + @vue/* | 43 KB |
| `vendor-naive` | naive-ui + vooks + vueuc + css-render + ... | 193 KB |
| `vendor-echarts` | echarts + vue-echarts + zrender | 191 KB |
| `vendor-i18n` | vue-i18n + @intlify | 18 KB |
| `vendor-md` | marked + dompurify | 22 KB |
| `vendor-icons` | @vicons | 5 KB |
| `vendor-utils` | axios + dayjs | 17 KB |

**主入口从 1.6 MB → 19 KB（95% 缩小）**。

各 view 单独 lazy chunk：
- `Lab.vue`: 26 KB
- `Dashboard.vue`: 9.5 KB
- 其他 3-10 KB

#### Tree-shaking

`unplugin-vue-components` + `NaiveUiResolver` 自动按需注册 Naive 组件，去掉 `app.use(naive)` 全量加载。Naive UI 实际打包大小从 ~500 KB（旧）降到 ~200 KB（按需）。

#### 静态资源缓存

后端 `CachedStaticFiles` 子类给 `/assets/*` 加：

```
Cache-Control: public, max-age=31536000, immutable
```

Vite 出的带 hash 文件名（如 `vendor-naive-Vek1seNq.js`）= immutable，一年内永久缓存。文件内容变 → hash 变 → 新 URL 必拉新版。

#### 首次加载估算

- 主入口 + vendor-vue + Lab view chunk + 当前路由 CSS = 约 80 KB gzip
- 其他 vendor 浏览器空闲时 `modulepreload`

### 7.5 移动端适配

**全屏断点**：`max-width: 768px`（tablet 以下）+ `max-width: 480px`（手机）。

**AppLayout**：
- < 768px sider 变 drawer（CSS `transform: translateX(-100%)`，加 `sider-mobile-open` class 时 translateX(0)）
- topbar 加 hamburger 按钮，遮罩层 + 点击外部关闭
- 用户名在 chip 内隐藏（`.user-chip :deep(.n-text) { display: none }`）

**表格 → 卡片视图替换**（mobile 完全不用横向滚动）：
- `Symbols`：mobile 卡片 + NPagination
- `Strategies`：mobile 卡片 + 打开/删除按钮
- `Backtests`：mobile 卡片 + 3 列指标 grid

桌面端保留 NDataTable，靠 `desktop-only`/`mobile-only` class 配 `display: none/block` 切换。

**关键交互**：filter 三件套窄屏纵向占满宽、card-header 自动换行 + extra 占满宽、按钮全部 `width: 100%`、N 列网格降到 2 列 / 1 列。

### 7.6 智能滚动（Lab.vue）

LLM 流式输出时，传统做法是每个 chunk 都 `scrollTop = scrollHeight` 强制滚到底，但用户向上回看历史时会被拉回。

**新方案**（`stickToBottom` 状态机）：

```typescript
const stickToBottom = ref(true)

function onThreadScroll() {
  const el = threadRef.value
  if (!el) return
  // 距底 < 60px 视为"贴底"
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return  // 用户离开底部就不自动滚
  nextTick(() => {
    threadRef.value.scrollTop = threadRef.value.scrollHeight
  })
}
```

- 用户向上滑 → 自动滚动停止
- 重新滑到底部附近 → 恢复贴底跟随
- 用户主动发新消息 → 强制贴底
- 流式过程中如果离开底部 → 右下角浮一个圆形 ↓ 按钮一键回最新

### 7.7 Markdown 紧凑

LLM 长输出（特别是 reasoning_content）容易段落太多。`Markdown.vue` 收紧间距：

```css
.md :deep(p) { margin: 4px 0; }
.md :deep(p + p) { margin-top: 8px; }   /* 相邻才大间距 */
.md :deep(ul), .md :deep(ol) { margin: 4px 0; padding-left: 22px; }
.md :deep(li > p) { margin: 0; }
.md :deep(blockquote > p) { margin: 2px 0; }
```

### 7.8 设计令牌

`style.css` 30+ 个语义化变量，dark + light 两套：

```
--bg-base / --card-bg / --surface-1/2/3 / --surface-deep
--text-primary / --text-secondary / --text-muted / --text-on-deep / --text-on-accent
--border-soft / --border-strong / --border-accent
--brand / --brand-grad / --accent / --accent-bg-soft / --accent-bg-hover
--user-bubble-bg / --user-bubble-border
--success / --danger / --warning / --info（+ -bg 浅底版）
--shadow-sm / --shadow-md / --shadow-lg / --shadow-glow / --focus-ring
--chart-axis-label / --chart-axis-line / --chart-split-line / --chart-tooltip-*
```

所有组件用 `var()`，**不硬编码颜色**（早期版本踩过坑：Lab.vue 大量 `rgba(255,255,255,0.025)` 这种 dark 默认值，切到 light 时反过来；现已全部改为 var）。

ECharts 颜色也从 var 读：

```typescript
function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim() || fallback
}
const axisLabel = cssVar('--chart-axis-label', '#94a3b8')
```

主题切换时图表自动适配。

---

## 八、API 设计

### 8.1 Endpoint 列表

#### Data（`/api`）

| Method | Path | 用途 |
|---|---|---|
| GET | `/overview` | 全局元信息：symbols 总数、缓存大小、各 market 统计、定时任务状态 |
| GET | `/markets` | 列各市场配置 + 命名 universe |
| GET | `/symbols` | 股票列表（可 `?market=cn`） |
| GET | `/symbols/{market}/{symbol}` | 单股 K 线 + 元信息（可 `?limit=N` 限制行数） |
| GET | `/symbols/{market}/{symbol}/sparkline` | 30 日收盘价数组（迷你折线用） |
| POST | `/data/fetch` | 拉取 universe 数据 `{universe: "cn:hs50"}` |
| POST | `/data/refresh_calendar` | 刷新交易日历 `{market: "cn"}` |
| POST | `/data/scheduled/trigger` | 触发定时任务立即跑一次 `{universe: "cn:hs50"}` |

#### Backtest（`/api`）

| Method | Path | 用途 |
|---|---|---|
| POST | `/dsl/validate` | 校验 DSL，返回 `{ok, factors, has_strategy, strategy: {...}}` |
| POST | `/backtest` | 跑回测 `{dsl, save_as?}`，可选保存为 strategy + 写 backtests 表 |
| GET | `/strategies` | 列已保存策略 |
| GET | `/strategies/{id}` | 单条策略 |
| DELETE | `/strategies/{id}` | 删 |
| GET | `/backtests` | 列回测历史（含每条的 metrics 摘要） |
| GET | `/backtests/{id}` | 完整回测结果（含 nav_curve） |
| DELETE | `/backtests/{id}` | 删 |

#### AI（`/api/ai`）

| Method | Path | 用途 |
|---|---|---|
| GET | `/status` | AI 配置状态 `{enabled, models: [...], default_model_id}` |
| POST | `/chat` | 非流式调用（保留兼容，前端已不用） |
| POST | `/chat/stream` | SSE 流式 |
| GET | `/sessions` | 当前用户会话列表（per-user 隔离） |
| POST | `/sessions` | 创建会话 |
| GET | `/sessions/{id}` | 拿单条会话 |
| PUT | `/sessions/{id}` | 更新 |
| DELETE | `/sessions/{id}` | 删 |

#### Settings（`/api/settings`）

| Method | Path | 用途 |
|---|---|---|
| GET | `/ai` | 拿 AI 配置（api_key 自动 mask） |
| POST | `/ai` | 写 AI 配置（`""` / `"***"` 表示保留原 key） |
| POST | `/ai/test` | 测试模型连通（参数全在请求里，不需要先保存） |
| DELETE | `/ai/models/{id}` | 删某个模型 |

### 8.2 鉴权

**HTTP Basic Auth**，用户表在 `users.yaml`（bcrypt hash）：

```yaml
users:
  - username: yiiwang
    password_hash: "$2b$12$..."
    display_name: "Yi Wang"
```

`get_current_user` dependency 注入到所有 endpoint。Basic header 60s 内存缓存（避免每次都 bcrypt verify）。

per-user 资源（会话历史）查询都 `WHERE user = ?` 保护。

### 8.3 错误约定

- `400` 参数错误（含 DSL 语法错误）
- `401` 未鉴权 → 前端拦截 → 触发登录弹窗
- `404` 资源不存在
- `500` 服务器内部错误（含回测失败、LLM 调用失败）

DSL 校验错误返回带行列号 + 错误消息，前端 highlight 错误位置：

```json
{"ok": false, "error": "未知字段 'volume_x'（允许：close, high, low, open, volume, amount, vwap）", "line": 1, "col": 15}
```

---

## 九、部署与运维

### 9.1 启停脚本

`scripts/start_server.sh`：

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/.."

PIDFILE=/tmp/quant-lite.pid
LOGFILE=server.log

# 优雅停止已有进程
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    sleep 2
fi
pkill -f "uvicorn app.main" 2>/dev/null || true

nohup .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 --port 8001 \
    --workers 2 --access-log \
    > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
disown
```

`stop_server.sh` 类似，读 PID 文件优雅关。

### 9.2 中间件链

```python
app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allow_origins.split(","))

# 静态资源
app.mount("/assets", CachedStaticFiles(directory=assets_dir), name="assets")

# SPA fallback
@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    return FileResponse(index_html)
```

`CachedStaticFiles`：

```python
class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["cache-control"] = "public, max-age=31536000, immutable"
        return resp
```

### 9.3 远程开发模式

代码同步约定：
- 核心代码在 `ssh tencent` 上 `/home/ubuntu/src/quant-lite/`
- 本地 `/Users/wangyi/Documents/Tencent-server/Quant/quant-lite/` 是镜像，方便阅读
- 改完用 rsync 同步：`rsync -avz ... tencent:/home/ubuntu/...`

### 9.4 监控

- `/api/health` 健康检查
- `server.log` access log + error log
- 前端 console.warn 失败重试逻辑
- 暂无 metrics / tracing，规模决定不需要

---

## 十、测试

### 10.1 测试覆盖

`pytest -q` 跑全部 114 个用例，单次 < 2s：

| 测试文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_dsl_parser.py`（项目根 + tests/）| 30 + N | 词法、parser、错误恢复、白名单、行列号 |
| `test_dsl_executor.py` | 32 | 18 个算子的输出、null 处理、窗口边界 |
| `test_dsl_executor_extended.py` | 10 | corr / ts_argmax / decay_linear 等边界 |
| `test_engine.py` | 13 | 端到端：top_n / long-short / 持仓 / rebalance |
| `test_storage_smoke.py` | 5 | DB 迁移、symbols 插入、查询 |

### 10.2 测试策略

- 不 mock 数据库（用临时 SQLite 文件 + 真实迁移）
- 用极小的合成 OHLCV 数据（3-5 只股票 × 10-30 天）跑端到端
- 错误路径都有用例（语法错 / 字段不存在 / 算子参数错 / 窗口非法）

---

## 十一、演进历程

### Phase 1：基础框架

FastAPI + Vue 3 + Naive UI 起步；HTTP Basic Auth；公网部署 `0.0.0.0:8001`；uvicorn workers=2 + GZip。

### Phase 2：存储层

SQLite WAL 元数据库 + Parquet 缓存；schema 版本化；APScheduler in-process 每日增量；A 股 + 美股各 50+ 只样本。

### Phase 3：DSL + 回测

递归下降 parser；18 算子 + 字段白名单；三层防前视偏差；T+0 信号 T+1 结算；80+ 测试。

### Phase 4：LiteAI 流式 Agent

首页改为 LiteAI；SSE 流式（started / thinking / thinking_text / tool_call_* / final_message / done）；OpenAI + Anthropic 双协议流式调用；DeepSeek-reasoner `reasoning_content` 拆分渲染。

### Phase 5：性能优化

vite manualChunks 切 6 个 vendor chunk；`unplugin-vue-components` 按需导入 Naive UI；主入口 1.6 MB → 19 KB；`/assets/*` Cache-Control immutable。

### Phase 6：UI 升级 + 主题系统 + 会话保存

JS 直写 CSS vars 主题切换（绕过 NGlobalStyle race）；设计令牌系统（shadow / focus-ring / brand-grad / surface-1/2/3）；卡片 hover lift + glow；会话历史 schema v4 + per-user CRUD；智能滚动 + jump-to-bottom 按钮；Markdown 紧凑段距。

### Phase 7：扩股票池 + 交易成本 + 多空

新 universe `cn:csi300`（akshare 实时拉成分）+ `us:nasdaq100`；DSL `cost: NUMBER` + `select: top N bottom M`；engine PnL = long_ret − short_ret + turnover-based 双边成本；holdings_history 用 `L:`/`S:` 区分多空；LiteAI 默认推荐 `cost: 0.001`。

### Phase 8：移动端适配 + 小程序规划

AppLayout 768px 以下 sider 变 drawer + hamburger 按钮 + 遮罩；所有 data view（Symbols / Strategies / Backtests）mobile 用卡片列表替代表格；filter 三件套窄屏纵向占满；Dashboard / SymbolDetail / DataOps 整体堆叠 + 字号收紧；K 线 / 净值曲线 ECharts 自适应。

`docs/06-miniprogram.md` 锁定微信小程序方案（uni-app + Vue 3，V1 范围：登录 / 聊天 / 策略 / 回测，SSE → WebSocket 适配，HTTP Basic Auth 复用）。**待启动信号**。

---

## 十二、待办与展望

### 12.1 数据扩池数据未补齐

`cn:csi300` 和 `us:nasdaq100` 的 universe 配置已经写入 `app/data/__init__.py`，但实际 Parquet 数据未拉到（背景拉取时碰到 akshare 后端的东方财富/Sina API 连续 RemoteDisconnected，腾讯云到这两家的网络问题）。

**下一步**：
- 用 DataOps 页面手动重试 fetch（前端按钮已就绪）
- 或在本地网络（VPN / 代理）跑 fetch 脚本后 rsync 上去
- 不影响现有 `cn:sample` + `cn:hs50` + `us:sample` + `us:sp50` 共 ~140 只的回测

### 12.2 微信小程序（已规划）

`docs/06-miniprogram.md` 锁定：uni-app + Vue 3，复用现有 REST 后端，SSE 通过新加 `/api/ai/chat/ws` WebSocket endpoint 适配。**等启动信号**。

### 12.3 潜在方向

| 方向 | 价值 | 工作量 |
|---|---|---|
| 因子组合 / 加权 | 高（多因子是实战核心） | 大（DSL 扩 + UI） |
| 行业 / 市值中性化 | 高（消除 beta 暴露） | 中 |
| IC / IR / 分层回测 | 高（因子评价标准化） | 中 |
| 基本面数据集成 | 中（财报 / 估值因子） | 大（新数据源） |
| 实盘信号推送 | 中（每日运行 + 邮件 / 微信） | 中 |
| 批量参数扫描 | 中（grid search 多组合一次跑） | 中 |
| 风险归因 | 中（Brinson / FF 分解） | 中 |
| 期货 / 加密扩展 | 低（当前 universe 够） | 大 |

按"研究价值 / 实现成本"排序，下一阶段建议优先 **行业中性化 + IC/IR + 因子组合**。

---

## 附录

### A. 关键性能数字

| 指标 | 当前值 |
|---|---|
| 主入口 JS（gzip） | 19 KB |
| 首屏总下载（gzip） | ~80 KB |
| 后端 API 平均响应 | 2-7 ms（已 cached 的） |
| 单次回测耗时（cn:hs50 + monthly + 3 年） | ~150 ms |
| 单次 LLM 工具调用循环 | 5-60 s（取决于模型） |
| SSE 首字节延迟 | < 500 ms |
| 测试运行时间 | 1.2 s（114 用例） |

### B. 代码规模（行数）

| 模块 | 行数 |
|---|---|
| `app/` Python 后端 | ~3800 |
| `app/dsl/` DSL 解析执行 | ~800 |
| `app/engine/` 回测引擎 | ~430 |
| `app/ai/` LiteAI agent | ~700 |
| `frontend/src/views/` | ~3500 |
| `frontend/src/components/` | ~900 |
| `tests/` | ~1200 |
| `docs/` | ~1200（含小程序规划） |

### C. 版本

- Quant Lite 主版本：0.1.0
- DB schema 版本：v4
- Parquet schema 版本：v1
- 前端构建 hash：动态（每次 build 变）
