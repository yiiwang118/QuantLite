# 开发历程

按 phase 倒序排列。

## Phase 6：UI 升级 + 主题系统 + 会话保存

- **JS 直写 CSS vars 主题切换**：放弃 `:root.dark/.light` class cascade，改为 `documentElement.style.setProperty` 直写 inline。绕过 Naive UI `<NGlobalStyle />` 注入冲突
- **设计令牌系统**：统一 `--shadow-sm/md/lg/glow`、`--focus-ring`、`--brand-grad`、`--surface-1/2/3/deep`，全局组件都从 var 取色
- **卡片 hover lift + glow**：所有 `n-card` 自动阴影 + hover 微抬起 + primary 按钮渐变 + glow
- **会话历史（per-user）**：DB schema v4 加 `chat_sessions` 表，4 个 CRUD endpoint，前端右侧栏列表 + 自动保存 + hover 删除
- **智能滚动**：监听 chat-thread scroll，用户上滑停止 auto-scroll，离开底部出 jump-to-bottom 按钮
- **Markdown 段距紧凑**：thinking 区域段间从 8px → 4px

## Phase 5：性能优化

- **拆 vendor chunks**：vite manualChunks 切 6 个独立 chunk（vue / naive / echarts / i18n / md / icons / utils）
- **Naive UI 按需导入**：`unplugin-vue-components` + `NaiveUiResolver` 替代 `app.use(naive)`
- **主入口 1.6 MB → 19 KB**（95% 缩小）
- **静态资源长缓存**：`CachedStaticFiles` 给 `/assets/*` 加 `Cache-Control: immutable`

## Phase 4：LiteAI 流式 Agent

- **首页改为 LiteAI**：聊天 + DSL 编辑 + 回测结果合一
- **流式 SSE**：`/api/ai/chat/stream` 推 `started / thinking / thinking_text / tool_call_* / final_message / done / error` 事件
- **LLM 流式调用**：OpenAI `stream=True` + Anthropic `messages.stream()`，按 chunk 实时 emit `thinking_text`
- **DeepSeek-reasoner**：拆 `reasoning_content`（思考链）单独渲染为 blockquote；后续调用必须回传
- **4 个工具**：`validate_dsl / run_backtest / list_universes / list_saved_strategies`
- **多模型**：每个模型独立 label + format + endpoint，OpenAI 兼容 + Anthropic 双协议
- **AgentContext**：把完整 backtest 结果存起来给前端用，给 LLM 的只是裁剪版

## Phase 3：DSL + 回测引擎（A2 + A3）

- **DSL parser**：递归下降，支持 18 算子 + 字段白名单 + 三层防前视偏差
- **Polars 执行**：DSL 编译成 `pl.Expr`，over("symbol") 实现 panel data 算子
- **回测引擎**：universe + signal + rebalance + benchmark 对照
- **指标**：cum_return / annual_return / sharpe / max_drawdown / win_rate / excess_return
- **80+ 测试**

## Phase 2：存储层 + 数据拉取

- **SQLite WAL**：元数据库，schema 版本化
- **Parquet 缓存**：A 股 + 美股各 50+ 只样本，单只 5 年 < 100 KB
- **APScheduler**：每日开盘前增量拉数据
- **HS50 调整**：600837 海通证券 → 601088 中国神华（前者合并退市）

## Phase 1：基础框架 + 部署

- FastAPI + Vue 3 + Naive UI 起步
- HTTP Basic Auth + 60s cache
- 公网部署 `http://152.136.209.150:8001`
- uvicorn workers=2 + GZip

## 设计原则

- **不要写 PDF**：架构选型基于本项目场景（10-20 人小团队、多市场、AI 辅助），不拿"PDF 这么写"当理由
- **小团队 ≠ 个人项目**：从一开始就考虑并发、共享、Auth
- **三层防前视偏差**：parser / executor / engine 各一层，纵深防御
- **数据库迁移幂等**：`PRAGMA user_version` 链式迁移，老 DB 自动升级
