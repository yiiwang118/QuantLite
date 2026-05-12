# 微信小程序规划

> 状态：**规划中，未实施**。等 web 端稳定后启动。本文档锁定技术选型、架构、范围、阶段。

## 目标

让团队**在手机上完整使用 Quant Lite**，与 web 端功能对齐。小程序不是 web 的精简版，而是同一个研究台的另一个入口。研究员出差、通勤路上也能查回测、跟 LiteAI 对话、看数据、调整设置。

## 技术选型

### 候选

| 方案 | 优势 | 劣势 |
|---|---|---|
| **uni-app**（Vue 3） | 跟现 web 同栈，Vue 知识复用，一次代码多端编译（小程序/H5/App） | 性能比原生略低，部分 Naive UI 组件无法用 |
| Taro（React/Vue） | 跨端能力强、社区活跃 | 团队主栈是 Vue，迁移成本 |
| 原生小程序（WXML） | 性能最好，文档完善 | 代码零复用，新栈维护成本 |

### 决策：uni-app + Vue 3

- 跟 `frontend/` 栈一致（Vue 3 + TS）
- 工具调用、SSE、状态管理逻辑可直接搬
- 后期想出 H5 / App 也省力
- UI 库用 [uview-plus](https://uview-plus.jiangruyi.com/)（组件全 + 同时支持 dark/light），或 [uni-ui](https://uniapp.dcloud.net.cn/component/uniui/uni-ui.html) 官方更精简

## 架构

```
            ┌──────────────────────────────┐
            │   FastAPI Backend (现有)       │
            │   完整 REST + SSE/WS 复用      │
            └────────▲────────┬─────────────┘
                     │        │
   ┌─────────────────┴┐    ┌─┴────────────────────┐
   │   Web 前端       │    │   小程序 (uni-app)    │
   │   Vue 3 + Naive  │    │   Vue 3 + uview-plus  │
   │   桌面/平板       │    │   手机 + 全功能         │
   └──────────────────┘    └───────────────────────┘
```

**后端基本零改动**，只多加一个 WebSocket endpoint 用于 SSE 适配（小程序原生 `wx.request` 不支持 SSE 流式）。

## 范围（V1 全功能对齐 web）

小程序必须覆盖 web 的全部 8 个页面：

| 页面 | 功能 | web 等价物 |
|---|---|---|
| **登录** | 用户名 + 密码 → 存 Basic Auth 凭证 | `LoginDialog.vue` |
| **LiteAI** | 聊天 + 流式输出 + 工具调用展示 + DSL 编辑（textarea） + 回测结果可视化 + 会话历史切换 | `Lab.vue` |
| **概览（Dashboard）** | 全局 KPI 卡片、市场快照 + sparkline、详细对比表、存储元信息 | `Dashboard.vue` |
| **股票列表** | 市场过滤 + 搜索 + 卡片视图（market/symbol/sparkline/缓存信息）+ 分页 + 跳详情 | `Symbols.vue`（直接复用 mobile 卡片设计） |
| **股票详情** | summary 指标 + K 线图（echarts-for-weixin）+ 元信息 + 日线表（横滑） | `SymbolDetail.vue` |
| **策略库** | 卡片列表 + 打开/删除 + 跳 LiteAI 实验 | `Strategies.vue` |
| **回测历史 + 详情** | 卡片列表（含 3 列指标）+ 点击进详情（净值曲线 + 指标 + 持仓） | `Backtests.vue` + `Lab.vue?backtest_id=X` |
| **数据操作** | 命名 universe 拉取按钮、定时任务状态、立即跑、操作日志 | `DataOps.vue` |
| **设置** | AI 多模型管理（add / edit / delete / test / 默认模型选择）+ API key 输入（隐藏） | `Settings.vue` |

### 不需要的简化

只在以下地方做小屏简化：
- DSL 编辑器：手机不便长篇打代码 → 主要靠 LiteAI 生成，textarea 是兜底
- ECharts 图：保持但高度收紧（K 线 320px、净值 360px）
- 表格：用卡片视图替代（web 端 mobile 已做过同样的 pattern，直接复用）

## 关键技术点

### 1. SSE 流式 → WebSocket

小程序 `wx.request` 不支持 SSE。后端加一个：

```
POST /api/ai/chat/ws   # 新增 WebSocket endpoint
```

实现复用现有 agent 的 `on_event` 回调：把事件序列化为 JSON 后通过 WS 推送。前端用 `uni.connectSocket()` 接收。

事件结构跟 SSE 完全一致（started / thinking / thinking_text / tool_call_* / final_message / done / error），前端处理逻辑可以从 `frontend/src/api/client.ts` 的 `streamChat` 直接搬。

### 2. Markdown 渲染

`marked + DOMPurify` 在小程序里跑不了（没 DOM）。换 [towxml](https://github.com/sbfkcel/towxml) 或 [zaml](https://github.com/zhanghua000/zaml)，输出 WXML AST 直接渲染。同样支持代码块、表格、blockquote（推理过程用的）。

### 3. ECharts

[echarts-for-weixin](https://github.com/ecomfe/echarts-for-weixin) 官方支持，uni-app 有 [uniapp-echarts](https://github.com/ecomfe/echarts-for-weixin/tree/master/uniapp) 包装。

K 线、净值曲线、Sparkline 三个 chart 组件需要分别封装。**ECharts 颜色配置直接从 CSS 变量读**这套方案在小程序里不工作（小程序无 `:root`），改成主题模式参数注入：

```js
function chartTheme(isDark) {
  return isDark ? darkColors : lightColors
}
```

### 4. DSL 编辑器

无 Monaco / CodeMirror。用 `<textarea>` + 单色 mono 字体 + 简单的语法高亮（首字段着色：`factor` / `strategy` / `top` / `bottom` / `cost` / `rebalance` 等关键字）。可选：长按调出"插入算子"快捷面板（18 个算子按钮一键插入）。

实际场景上 LiteAI 帮写为主，用户只是看 + 微调。

### 5. 主题

小程序也支持 light/dark。`wx.getSystemInfoSync().theme` + `wx.onThemeChange()`。沿用 web 端的 CSS variable 思路——但小程序 WXSS 不能直接 `var()`，要用：

```scss
// 用 sass 变量 + theme 类
.card {
  background: var(--card-bg);
}
.theme-dark .card { --card-bg: #0e1124; }
.theme-light .card { --card-bg: #ffffff; }
```

把 web 的 `theme-vars.ts` 改成 sass mixin。

### 6. 鉴权 storage

```js
uni.setStorageSync('auth', { username, basicHeader })
```

每次请求 `header: { Authorization: 'Basic xxx' }`。401 → 跳登录页。

后端零改动，复用现有 HTTP Basic Auth。

### 7. KeepAlive 模式

uni-app pages 默认 stack 模式（pageshow / pagehide），切换 tab 时不销毁 —— 跟 web 端的 KeepAlive 等价。`onShow()` 等价于 web 的 `onActivated()`，用来在切回时刷新 AI 模型 / 会话历史 / 策略库。

### 8. 文件结构

`miniprogram/` 独立目录，跟 `frontend/` 平行：

```
quant-lite/
├── app/                ← 后端（基本不动，加 WS endpoint）
├── frontend/           ← Web 前端
└── miniprogram/        ← 小程序
    ├── pages/
    │   ├── login/
    │   ├── lab/                ← LiteAI
    │   ├── dashboard/
    │   ├── symbols/
    │   ├── symbol-detail/
    │   ├── strategies/
    │   ├── backtests/
    │   ├── data-ops/
    │   └── settings/
    ├── components/
    │   ├── markdown.vue        ← towxml 封装
    │   ├── kline-chart.vue     ← echarts 封装
    │   ├── nav-chart.vue
    │   ├── sparkline.vue
    │   └── chat-message.vue
    ├── api/
    │   ├── client.js           ← 复用 frontend/src/api/client.ts 思路
    │   └── ws-chat.js          ← WebSocket 适配
    ├── store/                  ← pinia
    ├── theme/
    │   └── theme-vars.scss
    ├── i18n/                   ← 复用 zh.ts / en.ts
    └── manifest.json
```

## 实施阶段

| 阶段 | 目标 | 工作量预估 |
|---|---|---|
| Phase A | 脚手架 + 登录 + 主框架（tabBar 5 个 + 二级页路由）+ 主题切换 | ~2 天 |
| Phase B | LiteAI 聊天 PoC：WebSocket 流式 + 工具调用展示 + Markdown 渲染 + 会话历史 | ~4 天 |
| Phase C | DSL 编辑器（textarea + 关键字着色）+ 回测结果可视化（指标卡 + 净值曲线 echarts） | ~3 天 |
| Phase D | Dashboard / Symbols 列表 + 详情（含 K 线）/ Strategies / Backtests 卡片视图 | ~3 天 |
| Phase E | DataOps（拉取按钮 + 定时任务状态 + 日志）+ Settings（AI 模型 CRUD + test）| ~2 天 |
| Phase F | 移动端 UX 打磨、错误处理、空态、性能优化（chunk 拆分 / 预加载）| ~2 天 |
| Phase G | 微信备案 + 上线流程（小程序后台审核、icon、隐私协议）| ~3 天 |

**总计 ~19 天**（约 3-4 周专人开发，对应 1.5 个 sprint）。

后端工作量：加 `/api/ai/chat/ws` WebSocket endpoint，约 0.5 天。

## 启动条件

**当下不做**。先满足：

- [ ] Web 端核心交互稳定（LiteAI 流式、回测、会话）
- [ ] 小程序备案 / AppID 准备就绪
- [ ] 团队有移动端高频使用诉求（不只是"试试看"）
- [ ] 至少分配一人 3-4 周专注开发

用户说"等我指示再做" → **本文档锁定方案，待启动信号**。

## 风险与权衡

| 风险 | 影响 | 缓解 |
|---|---|---|
| 小程序审核拒绝（金融类敏感）| 上线不了 | 提前查 [类目要求](https://developers.weixin.qq.com/miniprogram/product/material.html)，主营改成"工具/效率"避开金融监管，宣传词避开"投资建议" |
| AI API key 存储敏感 | 用户输入泄漏 | 密码框 + 后端 mask + storage 加密；考虑改为只读模式（key 只在 web 设，小程序不允许改） |
| WS 长连接断网 | 流式中断 | 心跳 + 重连，断了重发 last_message_id 续传（需要后端配合标记位置） |
| K 线大量数据卡顿 | 体验差 | 默认只拉 90 天，按需"加载更多"；ECharts `lazyUpdate` + 数据抽样 |
| 小屏长 prompt 输入难 | 用户挫败 | 提供常用 prompt 快捷按钮（"hs50 动量 top 3"、"低波动复合"等）+ 语音转文字接入 |

## 数据流（与 web 端等价）

```
用户在小程序聊天："写一个 csi300 动量 top 5 跑回测"
    │
    ▼  WebSocket /api/ai/chat/ws
后端 ai.chat() 启动 worker 线程
    │
    ├─ 流式 emit thinking_text → WS → 小程序 textarea 逐字渲染
    ├─ tool_call_start "validate_dsl"  → WS → 工具气泡（旋转 icon）
    ├─ tool_call_end → WS → 气泡变 ✓
    ├─ tool_call_start "run_backtest" → ...
    ├─ tool_call_end → 气泡 ✓ + 缓存 backtest_result
    ├─ final_message → assistant 文字（Markdown 渲染）
    └─ done → 全部完成，写回 DSL textarea + 显示 nav-chart 组件

小程序 onShow() 拉 GET /api/ai/sessions → 右侧会话历史
点击历史 → GET /api/ai/sessions/{id} → 填回 messages
```

## 与 web 端的同步策略

- **后端逻辑**：完全复用，零改动起步
- **共享**：DSL 语法、API 协议、设计令牌（颜色/间距/字号）、i18n 文案
- **不共享**：
  - 渲染（Naive UI ≠ uview-plus）
  - 流式协议（SSE vs WebSocket，事件结构对齐）
  - 图表组件（echarts vs echarts-for-weixin，API 一致但导入方式不同）
- **更新节奏**：web 端先发版，小程序 catch up（DSL 加新算子时小程序的 prompt hint 也要同步）
