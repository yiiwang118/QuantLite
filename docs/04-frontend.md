# 前端架构

> Vue 3 + Vite + TypeScript + Naive UI + ECharts + Pinia + vue-i18n。LiteAI 是首页，其他是数据展示页。

## 路由

```
/lab                 LiteAI 首页（聊天 + DSL 编辑 + 回测结果）
/dashboard           概览（symbols / cache / 最近策略）
/symbols             股票列表
/symbols/:m/:s       股票详情（K 线 + 涨跌数据）
/strategies          策略库
/backtests           回测历史
/backtests/:id       回测详情
/data                数据操作（手动拉数据 / 定时任务）
/settings            AI 模型 + 系统设置
```

所有 view 通过 `KeepAlive max=10` 缓存：切回时不重新 mount，瞬间显示。
KeepAlive 下 `onMounted` 只跑一次；切回触发 `onActivated`，用来刷新 AI 模型列表、会话历史、策略库等可能在其他页改过的状态。

## 状态管理

- **Pinia store**：`auth`（用户名 + Basic Auth header）、`data`（symbols 数据缓存）
- **组件本地 state**：Lab 的 chat messages / sessions / selectedModelId，Settings 的 drafts

API 拦截：`api/client.ts` 包了 axios，401 抛 `AuthRequired`，触发 `auth.requireLogin()`。

## 主题系统

**关键设计：CSS variables 用 JS 直接 `setProperty` 写到 documentElement.style**。

为什么不用 CSS class + `:root.dark { ... }`？早期版本踩过坑：
- Naive UI `<NGlobalStyle />` 会运行时注入 `<style>` 到 `<head>`，包括 `body { background-color: var(--xxx) }`
- 这条规则的 source order 比 vite 打包的 style.css 晚，盖掉 body background
- 加上多重 cache/specificity，class race 导致一会 light 一会 dark 不同步

最终方案 `src/theme-vars.ts`：
```ts
const LIGHT_VARS = { '--bg-base': '#f5f6fb', '--card-bg': '#ffffff', ... }
const DARK_VARS = { '--bg-base': '#07081a', '--card-bg': '#0e1124', ... }

export function applyTheme(isDark: boolean) {
  const root = document.documentElement
  for (const [k, v] of Object.entries(isDark ? DARK_VARS : LIGHT_VARS)) {
    root.style.setProperty(k, v)
  }
}
```

inline style 是 CSS 最高优先级，永远赢，杜绝所有 cascade race。也去掉了 `<NGlobalStyle />`，自己掌控 body 样式。

## 性能优化

### Bundle 拆分

`vite.config.ts` 的 `manualChunks` 把 vendor 拆 6 个独立 chunk：
- `vendor-vue`（vue / router / pinia / @vue）
- `vendor-naive`（Naive UI + 内部依赖）
- `vendor-echarts`
- `vendor-i18n`（vue-i18n + @intlify）
- `vendor-md`（marked + dompurify）
- `vendor-icons`（@vicons）
- `vendor-utils`（axios / dayjs）

主入口从 **1.6 MB → 19 KB**（95% 缩小）。各 vendor chunk 独立 hash + immutable cache，浏览器并行下载 + 长效缓存。

### Naive UI 按需

用 `unplugin-vue-components` + `NaiveUiResolver` 自动按需导入，去掉 `app.use(naive)` 全量注册，tree-shaking 生效。

### 静态资源缓存

后端 `app/main.py` 的 `CachedStaticFiles`：给 `/assets/*` 加 `Cache-Control: public, max-age=31536000, immutable`。Vite 出的带 hash 的文件可永久缓存，hash 变 = 文件变。

## 关键交互

### LiteAI 聊天

**流式渲染**：监听 SSE，按事件类型拼装 `ChatMessage` 对象的 `text` / `thinking` / `toolCalls`。Markdown 渲染用 `marked` + `DOMPurify` 防 XSS。

**智能滚动**：监听 `chat-thread` 的 scroll 事件，距底部 < 60px 视为"贴底"。用户向上滑 → 自动滚动停止；流式过程中如果离开底部，右下角浮一个圆形 ↓ 按钮可一键回最新；用户主动发消息 → 强制贴底。

### Markdown 渲染

`Markdown.vue` 紧凑段距：`p` 间 4px，相邻 `p+p` 才 8px，`li > p` 取消 margin。长 thinking 不会因段间距过大而显得稀疏。

### Settings 多模型

每个模型一个 `DraftModel`，drafts 数组里 push 一个就出新行。Card header 右上角固定两个明显的"添加 OpenAI 兼容 / 添加 Anthropic"按钮，确保增加多个模型的入口可见。

## i18n

`vue-i18n` 双语（zh / en），顶部下拉切换。语言切换通过 `setLocale()` 同时改 `i18n.global.locale.value` 和 Naive UI 的 NConfigProvider locale。

## 设计令牌

`style.css` 定义统一令牌（颜色 / 阴影 / 表面层级 / 焦点 ring），所有组件用 `var()`：

```
--bg-base / --card-bg / --surface-1/2/3 / --surface-deep
--text-primary / --text-secondary / --text-muted
--border-soft / --border-strong / --border-accent
--brand / --brand-grad / --accent / --accent-bg-soft / --accent-bg-hover
--success / --danger / --warning / --info（+ -bg 后缀的浅底版本）
--shadow-sm / --shadow-md / --shadow-lg / --shadow-glow / --focus-ring
--chart-axis-* / --chart-tooltip-*
```

dark 和 light 两套值，切主题时 JS 把对应 set 整体写入。

## 组件清单

```
src/components/
├── AppLayout.vue         主框架（sider / topbar / content）
├── LoginDialog.vue       登录弹窗
├── Markdown.vue          marked + DOMPurify 安全渲染
├── MetricCard.vue        指标小卡片
├── StatCard.vue          顶部统计卡片
├── NavCurveChart.vue     净值曲线（ECharts）
├── KLineChart.vue        K 线（ECharts）
└── Sparkline.vue         迷你折线
```

ECharts 颜色全部从 CSS variable 读（`getComputedStyle(documentElement).getPropertyValue('--chart-axis-label')`），主题切换图表自动适配。
