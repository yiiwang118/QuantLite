# LiteAI Agent

> 自然语言 → DSL → 回测 → 解读，一条龙。流式输出思考过程 + 工具调用全程可见，类似 Claude Code 的体验。

## 设计

LiteAI 是个 **Tool-using LLM Agent**：

```
用户："写一个 hs50 上 20 日动量 top 3 的策略并跑一下回测"
   │
   ▼
LLM 输出 → 工具调用循环（max 6 轮）：
   1. validate_dsl(dsl)        校验语法
   2. run_backtest(dsl)        真跑回测，拿指标
   3. (自然语言总结结果)
```

## 多模型 + 双协议

支持 **OpenAI 兼容**（DeepSeek / Moonshot / GPT / GLM 等）+ **Anthropic Messages**（Claude）。

每个模型在数据库里存 `{id, label, format, api_key, model_id, base_url}`，用户可以自取 label，配多个并切换。配置 JSON 存 SQLite `settings` 表的 `ai.config` key。

API key 在 GET 时 mask（只返回 `sk-...****`），POST 时 `""` 或 `"***"` 表示保留原值，避免改其他字段时不小心覆盖 key。

## 4 个工具

```
validate_dsl(dsl)           → 校验 DSL 语法，返回错误位置
run_backtest(dsl)           → 真跑回测，返回 metrics + nav_curve + benchmark 对照
list_universes()            → 列可用股票池（cn:sample/hs50 + us:sample/sp50）
list_saved_strategies()     → 列已保存策略
```

工具返回给 LLM 的数据**裁剪后再返**（token 贵），完整结果存到 `AgentContext` 给前端取用（比如完整 nav_curve）。

## 流式 SSE

`/api/ai/chat/stream` 返回 `text/event-stream`，每个事件一行 `data: {json}\n\n`：

```
started        → 开始（含选中模型信息）
thinking       → 进入新一轮 LLM 调用（动画占位）
thinking_text  → 当前累积的文字（reasoning + content），增量更新
tool_call_start → 工具调用开始
tool_call_end  → 工具调用结束（带结果）
final_message  → 最后一条 assistant 文字
done           → 整轮完成（含完整 result + tool_log + 回测产物）
error          → 异常
```

后端用 `asyncio.Queue` 把 worker 线程的 `on_event` 回调桥接到 async SSE generator。心跳 10s 一次 `: heartbeat\n\n` 防代理超时。

## LLM 流式调用

**OpenAI 协议**（`client.chat.completions.create(..., stream=True)`）：
- 按 chunk 累积 `delta.content` 和 `delta.reasoning_content`（DeepSeek-reasoner 扩展）
- `delta.tool_calls` 是分片来的，按 `tc.index` 累积 `arguments`
- 每个 chunk 都 emit `thinking_text` 增量到前端，渲染时实时刷新

**Anthropic 协议**（`client.messages.stream(...)`）：
- 监听 `content_block_delta` 事件，`text_delta` 累积到 buffer
- `stream.get_final_message()` 拿完整 message（含 tool_use blocks）

### DeepSeek-reasoner 适配

`reasoning_content`（思考链）是非标准 OpenAI 扩展。两个细节：
1. 流式返回时先于 `content` 出来，单独累积，前端用 `> 推理过程：` blockquote 渲染
2. **必须在后续 API 调用时回传**给模型，否则报错 `The reasoning_content in the thinking mode must be passed back to the API`

## 会话历史

per-user 隔离，自动保存：
- `chat_sessions(id, user, title, messages JSON, created_at, updated_at)`
- 首次发完消息自动 POST `/api/ai/sessions` 创建（title 取首条 user 消息前 30 字）
- 之后每轮 done 后 PUT 整个 messages
- 切换/删除走 GET/DELETE，所有查询都 `WHERE user = ?` 保护

前端右侧栏列出最近 50 条，按 `updated_at DESC` 排序，hover 出删除按钮。

## 系统 prompt

运行时拼装（不写死在文件里），包含：
- DSL 语法
- 字段白名单（从 `wl.FIELDS` 动态注入）
- 算子白名单（从 `wl.OPERATORS` 数）
- 工作流程：先生成 DSL → 必先 `validate_dsl` → 用户要才跑 `run_backtest`
- 中文回答
- "工具返回 ok:false 时根据错误信息修正 DSL 再试一次"（自我修复）
