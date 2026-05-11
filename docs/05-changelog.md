# 开发历程

按 phase 倒序排列。

## Phase 8：移动端适配 + 小程序规划

- **AppLayout 移动端 drawer**：< 768px 时 sider 隐藏，topbar 加 hamburger 按钮，点击滑出 sider + 遮罩，菜单选中后自动关闭
- **topbar 紧凑**：小屏隐藏用户名只剩头像，padding 收紧，标题截断
- **Lab.vue 移动端**：chat-thread 65vh→55vh，气泡 max-width 92%，字号/padding 收紧，detail-row 限高 140px
- **Settings 移动端**：model-row-head 改纵向布局，input 占满宽
- **全局 form-row**：< 768px 自动改纵向，label 不占固定宽度
- **小程序 docs**：`docs/06-miniprogram.md` 锁定 uni-app + Vue 3 技术栈，V1 范围（登录/聊天/策略/回测），SSE → WebSocket 适配方案，分阶段实施，**待启动信号**

## Phase 7：扩股票池 + 交易成本 + 多空

- **新 universe**：`cn:csi300`（沪深 300 全成分，akshare 实时拉）+ `us:nasdaq100`（100 只主流科技/消费/医药/工业）
- **成本模型**：`cost: NUMBER` DSL 字段，每次 rebalance 按 turnover 双边扣 `turnover_one_way * cost * 2`；`total_cost` 单独返回累计拖累
- **Long-short**：`select: top N bottom M` 语法，多头 top N + 空头 bottom M，PnL = long_ret − short_ret，benchmark 始终 long-only
- **holdings_history 标识**：多头 `L:cn/600519`，空头 `S:cn/000001`
- **前端**：回测结果区头部新增策略类型 + 成本拖累标识
- **AI 同步**：LiteAI system prompt 更新，知道新 universe、long-short、cost 字段，默认推荐 `cost: 0.001`

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
