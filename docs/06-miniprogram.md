# 微信小程序规划

> 状态：**规划中，未实施**。等 web 端稳定后启动。本文档锁定技术选型、架构、范围、阶段。

## 目标

让团队在手机上用 LiteAI 跑回测、看历史。**纯查询 + 对话场景**，不做编辑器。重度操作（DSL 编辑、模型配置、数据拉取）仍走 web 端。

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
- UI 库用 [uni-ui](https://uniapp.dcloud.net.cn/component/uniui/uni-ui.html) 或 [uview-plus](https://uview-plus.jiangruyi.com/)，不强求 Naive UI

## 架构

```
            ┌──────────────────────────────┐
            │   FastAPI Backend (现有)       │
            │   /api/ai/chat/stream         │
            │   /api/ai/sessions            │
            │   /api/strategies             │
            │   /api/backtests              │
            │   /api/dsl/validate           │
            └────────▲────────┬─────────────┘
                     │        │
                     │        │
   ┌─────────────────┴┐    ┌─┴────────────────────┐
   │   Web 前端       │    │   小程序 (uni-app)    │
   │   Vue 3 + Naive  │    │   Vue 3 + uni-ui      │
   │   重度操作        │    │   查询 + 聊天          │
   └──────────────────┘    └───────────────────────┘
```

**后端零改动起步**：完整复用现有 REST + SSE endpoints。鉴权也直接用 HTTP Basic Auth，小程序登录页就是用户名密码输入。

如果后续想接入微信原生登录，再加 `POST /api/wx/login { code }` 一个 endpoint，用 `wx.login()` 拿 code 换 backend session token。这是 V2 的事，**V1 先用 Basic Auth**。

## 范围（V1）

### 包含

| 页面 | 功能 |
|---|---|
| 登录 | 用户名 + 密码 → 存 Basic Auth header 到 storage |
| 首页（LiteAI） | 聊天 + 流式输出 + 工具调用展示 + 历史会话切换 |
| 策略库 | 列表 + 详情（DSL 只读） |
| 回测历史 | 列表 + 详情（指标 + 净值曲线） |

### 不包含

- DSL 编辑器（在手机敲代码体验差，让 LiteAI 帮写就行）
- 数据操作页（手动拉数据）
- AI 模型配置（敏感 + 复杂，web 配好就够）
- K 线 / 复杂图表（小屏体验差）

## 关键技术点

### 1. SSE 流式

小程序 `wx.request` 不支持 SSE。两个方案：

- **方案 A**：用 `wx.connectSocket` 走 WebSocket。后端要新加 `/api/ai/chat/ws` endpoint
- **方案 B**：HTTP 长轮询。后端把每个事件分批返回（不流畅）

**选 A**：后端 WS endpoint 实现复用现有 `on_event` 回调，工作量小。

### 2. Markdown 渲染

uni-app 可以用 [towxml](https://github.com/sbfkcel/towxml) 或 [zaml](https://github.com/zhanghua000/zaml)。`marked + dompurify` 在小程序里跑不了（没 DOM）。

### 3. ECharts

`echarts-for-weixin` 官方支持。但小屏 K 线意义不大，V1 只画净值曲线（简单 line chart）。

### 4. 主题

小程序也支持 light/dark。`wx.getSystemInfoSync().theme` 或 `wx.onThemeChange`。沿用 web 端的 CSS variable 思路。

### 5. 鉴权 storage

```
wx.setStorageSync('auth', { username, basicHeader })
```

每次请求 `header: { Authorization: 'Basic xxx' }`。401 → 跳回登录页。

## 实施阶段

| 阶段 | 目标 | 工作量预估 |
|---|---|---|
| Phase A | 脚手架 + 登录 + LiteAI 聊天 PoC（WS 流式） | ~3 天 |
| Phase B | 历史会话切换、策略列表、回测查看 | ~2 天 |
| Phase C | UI 打磨、错误处理、上线流程（小程序备案 + 审核） | ~3 天 |

## 启动条件

**当下不做**。先满足：

- [ ] Web 端核心交互稳定（LiteAI 流式、回测、会话）
- [ ] 小程序备案 / AppID 准备就绪
- [ ] 用户有移动端使用诉求（团队成员实际反馈）

用户说"等我指示再做" → **本文档锁定方案，待启动信号**。

## 目录约定

未来实施时建议目录结构：

```
quant-lite/
├── app/                ← 后端（不动）
├── frontend/           ← Web 前端（不动）
└── miniprogram/        ← 小程序
    ├── pages/
    │   ├── login/
    │   ├── lab/        ← LiteAI 聊天
    │   ├── strategies/
    │   └── backtests/
    ├── api/            ← 复制 frontend/src/api/client.ts 改适配
    ├── components/
    └── manifest.json
```
