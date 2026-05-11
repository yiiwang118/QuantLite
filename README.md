# Quant Lite

一个小团队（10-20 人）用的量化策略研究 + 回测平台。自然语言 → DSL → 回测 → 报告，一条龙。

- **多市场**：A 股 + 美股，统一的因子 DSL，单次定义跨市场跑
- **18 个算子的 DSL**：时序窗口、横截面、数学运算；纯 Polars 表达式编译执行
- **AI Agent（LiteAI）**：自然语言描述策略 → 自动生成 DSL、校验、跑回测、解释结果。流式输出思考过程 + 工具调用全程可见（类似 Claude Code 的体验）
- **多模型**：每个模型可自取 label，支持 OpenAI 兼容 / Anthropic 两种 API 格式（DeepSeek、Moonshot、GPT、Claude 等都能配）
- **回测引擎**：T+1 结算、等权持仓、benchmark 对比、夏普 / 最大回撤 / 超额收益；三层防前视偏差
- **数据自动调度**：APScheduler in-process 每日开盘前增量拉数据
- **公网可访问**：HTTP Basic Auth、uvicorn workers、GZip、长效静态资源缓存

## 技术栈

后端 FastAPI + Polars + SQLite (WAL) + APScheduler；
前端 Vue 3 + Vite + Naive UI + ECharts + Pinia + vue-i18n。

## 快速开始

```bash
# 后端
uv venv -p 3.10 && source .venv/bin/activate
uv pip install -e ".[dev]"

# 配 Auth
cp users.yaml.example users.yaml
python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"
# 把哈希填进 users.yaml

# 配环境
cp .env.example .env

# 启动
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

```bash
# 前端
cd frontend
npm install
npm run dev      # 开发模式 → http://localhost:5173
npm run build    # 生产构建 → frontend/dist/，FastAPI 自动挂载到 /
```

## 生产部署

```bash
bash scripts/start_server.sh   # 后台起 uvicorn workers=2，写 /tmp/quant-lite.pid
bash scripts/stop_server.sh
```

环境变量见 `.env.example`，主要看 `HOST/PORT/USERS_YAML/DATA_CACHE_DIR/QUANT_DB`。

## DSL 速览

```
factor mom20 = delay(close, 1) / delay(close, 20) - 1
factor signal = zscore(mom20) - 0.5 * zscore(std(returns(close), 20))

strategy {
  universe:  cn:hs50
  signal:    signal
  select:    top 5
  rebalance: weekly
  start:     2022-01-01
  end:       2024-12-31
}
```

支持算子：`delay / ma / std / sum / max_ts / min_ts / ts_argmax / ts_argmin / ts_rank / decay_linear / corr / returns / rank / zscore / abs / log / sign` 等 18 个。窗口必须为非负整数常量，字段限于白名单 — 三层防前视偏差检查（parser / executor / engine）。

## 项目结构

```
quant-lite/
├── app/
│   ├── main.py              FastAPI 入口 + 静态挂载（长缓存）
│   ├── config.py            pydantic-settings
│   ├── db.py                SQLite WAL：symbols / calendar / strategies / backtests / settings
│   ├── scheduler.py         APScheduler 每日增量拉数据
│   ├── data/                A 股 + 美股数据源
│   ├── dsl/                 词法 / 解析 / 白名单 / 执行
│   ├── engine/              回测引擎 + benchmark
│   ├── ai/
│   │   ├── agent.py         Agent 主循环（流式 + tool calling）
│   │   ├── tools.py         4 个工具：validate_dsl / run_backtest / list_universes / list_saved_strategies
│   │   └── config.py        多模型配置（存 SQLite settings）
│   └── api/                 routes_data / routes_backtest / routes_ai / routes_settings + auth
├── frontend/
│   └── src/
│       ├── views/           Lab（AI 首页）+ Dashboard / Symbols / Strategies / Backtests / DataOps / Settings
│       ├── components/      AppLayout / NavCurveChart / KLineChart / Markdown / ...
│       ├── i18n/            zh + en
│       └── style.css        语义化 CSS 变量（单一 dark 主题）
├── tests/                   pytest（80+ 用例，parser/executor/engine/storage）
├── scripts/                 start_server.sh / stop_server.sh（PID + nohup）
├── pyproject.toml
├── users.yaml.example       Basic Auth 用户模板
└── .env.example             环境变量模板
```

## 测试

```bash
pytest -q
```

## 协议

MIT
