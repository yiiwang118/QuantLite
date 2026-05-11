"""LLM Agent：调 LLM + 工具循环。

两家 provider 都支持原生 tool calling：
- Anthropic Messages API：messages.tools / response.content[].type == "tool_use"
- OpenAI Chat Completions：tools=[...] / message.tool_calls

可选的 on_event 回调接收实时事件（用于 SSE 流式展示进度）：
  - {"type": "started", "model": {...}}
  - {"type": "thinking", "iteration": n}
  - {"type": "tool_call_start", "id": ..., "name": ..., "input": {...}, "iteration": n}
  - {"type": "tool_call_end", "id": ..., "name": ..., "result": {...}, "iteration": n}
  - {"type": "final_message", "text": "..."}
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from app.ai.config import ModelConfig
from app.ai.tools import (
    AgentContext,
    execute_tool,
    tools_for_anthropic,
    tools_for_openai,
)
from app.dsl import whitelist as wl

logger = logging.getLogger(__name__)


def _emit(on_event: Callable[[dict], None] | None, event: dict) -> None:
    if on_event:
        try:
            on_event(event)
        except Exception:
            logger.exception("on_event callback failed")


# ─── System prompt（运行时拼接） ─────────────────────────

def _system_prompt() -> str:
    fields = ", ".join(sorted(wl.FIELDS))
    return f"""你是 Quant Lite 的量化研究助手 / Agent。理解用户的自然语言请求，能写 DSL、能调用工具帮用户验证 / 跑回测 / 查信息。

# DSL 语法（用户的策略代码）

```
factor IDENT = expr            # 定义因子
strategy {{
    universe:  IDENT:IDENT     # cn:sample | cn:hs50 | us:sample | us:sp50
    signal:    IDENT
    select:    top NUMBER
    rebalance: daily | weekly | monthly
    start:     YYYY-MM-DD      # 可选
    end:       YYYY-MM-DD      # 可选
}}

expr = NUMBER | IDENT | -expr | expr (+|-|*|/) expr | OPERATOR(arg, ...)
```

# 字段白名单
{fields}

# 算子白名单（{len(wl.OPERATORS)} 个）

时序窗口（第 2 参数必须**非负整数常量**）：
- delay(x, n), ma(x, n), std(x, n), sum(x, n), max_ts(x, n), min_ts(x, n)
- ts_argmax(x, n)：窗口最大值的位置（0=最旧）
- ts_argmin(x, n)：最小值位置
- ts_rank(x, n)：当前值在窗口的百分位 [0, 1]
- decay_linear(x, n)：线性递减加权均值

时序双参 + 窗口（第 3 参数是窗口）：
- corr(x, y, n)：滚动皮尔逊相关

时序单参：returns(x)

横截面：rank(x), zscore(x)
数学：abs(x), log(x), sign(x)

# 规则
- 字段/算子只能用白名单里的
- 窗口必须是**非负整数常量**（5、20、60），不能负数/小数/变量
- factor 先定义后引用；signal 必须是已定义的 factor
- universe 只能是 cn:sample / cn:hs50 / us:sample / us:sp50

# 工具

你有 4 个工具：
- `validate_dsl(dsl)`：校验 DSL 语法。生成 DSL 后**必先调用一次**。
- `run_backtest(dsl)`：跑回测，返回策略 vs 基准的指标对照。用户说"跑一下/回测/看效果"时调用。
- `list_universes()`：查可用股票池。用户问"有哪些 universe"时调用。
- `list_saved_strategies()`：查已保存策略。

# 工作流程

1. 用户给一句话需求 → 你写一份 DSL
2. 调用 `validate_dsl` 确认无语法错误
3. 如果用户要求跑回测，调用 `run_backtest`
4. 用中文总结结果：策略 cum_return X%、夏普 Y、最大回撤 Z%、vs 基准超额 W pp

# 重要

- 用中文回答用户
- 工具返回有 `ok: false` 错误时，**根据错误信息修正 DSL 再试一次**
- 不要无脑跑回测——除非用户明确要求或在"自动开始"语境下
- 输出的 DSL **必须**至少包含 factor 定义；如果用户只问知识（"什么是动量"）不要硬写 DSL
- 简短，不啰嗦
"""


_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _system_prompt()
    return _SYSTEM_PROMPT


# ─── Anthropic 适配器（流式） ─────────────────────────────

def _run_anthropic(text: str, model: ModelConfig, ctx: AgentContext,
                   on_event: Callable | None = None,
                   max_iters: int = 6) -> dict:
    import anthropic
    kw: dict[str, Any] = {"api_key": model.api_key}
    if model.base_url:
        kw["base_url"] = model.base_url
    client = anthropic.Anthropic(**kw)

    messages: list[dict] = [{"role": "user", "content": text}]
    tools = tools_for_anthropic()
    last_text = ""

    for iter_n in range(max_iters):
        _emit(on_event, {"type": "thinking", "iteration": iter_n})

        text_buf = ""
        with client.messages.stream(
            model=model.model_id,
            max_tokens=2048,
            system=_get_system_prompt(),
            tools=tools,
            messages=messages,
        ) as stream:
            for ev in stream:
                t = getattr(ev, "type", None)
                if t == "content_block_delta":
                    delta = getattr(ev, "delta", None)
                    if delta and getattr(delta, "type", "") == "text_delta":
                        text_buf += delta.text
                        _emit(on_event, {
                            "type": "thinking_text", "text": text_buf, "iteration": iter_n,
                        })
            final = stream.get_final_message()

        if text_buf:
            last_text = text_buf

        tool_uses = [b for b in final.content if getattr(b, "type", "") == "tool_use"]

        if final.stop_reason != "tool_use" or not tool_uses:
            _emit(on_event, {"type": "final_message", "text": last_text})
            return {"ok": True, "message": last_text}

        messages.append({"role": "assistant", "content": final.content})

        tool_results = []
        for tu in tool_uses:
            _emit(on_event, {
                "type": "tool_call_start", "id": tu.id, "name": tu.name,
                "input": dict(tu.input), "iteration": iter_n,
            })
            result = execute_tool(tu.name, dict(tu.input), ctx)
            ctx.tool_log.append({
                "name": tu.name, "input": dict(tu.input), "result": result,
                "iteration": iter_n,
            })
            _emit(on_event, {
                "type": "tool_call_end", "id": tu.id, "name": tu.name,
                "result": result, "iteration": iter_n,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": tool_results})

    _emit(on_event, {"type": "final_message", "text": last_text})
    return {"ok": False, "error": f"达到最大迭代轮数 ({max_iters})", "message": last_text}


# ─── OpenAI 适配器（流式） ────────────────────────────────

def _compose_thinking(reasoning: str, content: str) -> str:
    """把 reasoning_content（思考链）和 content（要说的话）拼成一段展示文本。"""
    parts: list[str] = []
    if reasoning:
        parts.append("> 推理过程：\n>\n> " + reasoning.replace("\n", "\n> "))
    if content:
        parts.append(content)
    return "\n\n".join(parts)


def _run_openai(text: str, model: ModelConfig, ctx: AgentContext,
                on_event: Callable | None = None,
                max_iters: int = 6) -> dict:
    from openai import OpenAI
    kw: dict[str, Any] = {"api_key": model.api_key}
    if model.base_url:
        kw["base_url"] = model.base_url
    client = OpenAI(**kw)

    messages: list[dict] = [
        {"role": "system", "content": _get_system_prompt()},
        {"role": "user", "content": text},
    ]
    tools = tools_for_openai()
    last_text = ""

    for iter_n in range(max_iters):
        _emit(on_event, {"type": "thinking", "iteration": iter_n})

        stream = client.chat.completions.create(
            model=model.model_id,
            messages=messages,
            tools=tools,
            max_tokens=2048,
            stream=True,
        )

        content_buf = ""
        reasoning_buf = ""
        tool_calls_acc: list[dict] = []  # 按 index 累积
        finish_reason: str | None = None

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # DeepSeek-reasoner 的 reasoning_content（思考链）— 先于 content 流出
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_buf += rc
                _emit(on_event, {
                    "type": "thinking_text",
                    "text": _compose_thinking(reasoning_buf, content_buf),
                    "iteration": iter_n,
                })

            # 普通 content（最终要说的话）
            if delta.content:
                content_buf += delta.content
                _emit(on_event, {
                    "type": "thinking_text",
                    "text": _compose_thinking(reasoning_buf, content_buf),
                    "iteration": iter_n,
                })

            # tool_calls 是分片来的，按 index 拼接
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    while len(tool_calls_acc) <= idx:
                        tool_calls_acc.append({
                            "id": None, "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                    cur = tool_calls_acc[idx]
                    if tc.id:
                        cur["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            cur["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            cur["function"]["arguments"] += tc.function.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # 这一轮 LLM 产出的可见文字（reasoning + content）
        rendered = _compose_thinking(reasoning_buf, content_buf)
        if rendered:
            last_text = rendered

        # 没工具要调 → 结束
        valid_tcs = [t for t in tool_calls_acc if t.get("id") and t["function"]["name"]]
        if finish_reason != "tool_calls" or not valid_tcs:
            # 最终消息只回 content（不带"推理过程"前缀，避免重复展示）
            _emit(on_event, {"type": "final_message", "text": content_buf or last_text})
            return {"ok": True, "message": content_buf or last_text}

        # 把 assistant message + 工具调用累积进 messages
        asst_msg: dict[str, Any] = {
            "role": "assistant",
            "content": content_buf or "",
            "tool_calls": [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["function"]["name"],
                              "arguments": t["function"]["arguments"]}}
                for t in valid_tcs
            ],
        }
        if reasoning_buf:
            asst_msg["reasoning_content"] = reasoning_buf
        messages.append(asst_msg)

        for tc in valid_tcs:
            try:
                params = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                params = {}
            _emit(on_event, {
                "type": "tool_call_start", "id": tc["id"], "name": tc["function"]["name"],
                "input": params, "iteration": iter_n,
            })
            result = execute_tool(tc["function"]["name"], params, ctx)
            ctx.tool_log.append({
                "name": tc["function"]["name"], "input": params, "result": result,
                "iteration": iter_n,
            })
            _emit(on_event, {
                "type": "tool_call_end", "id": tc["id"], "name": tc["function"]["name"],
                "result": result, "iteration": iter_n,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

    _emit(on_event, {"type": "final_message", "text": last_text})
    return {"ok": False, "error": f"达到最大迭代轮数 ({max_iters})", "message": last_text}


# ─── 对外入口 ────────────────────────────────────────────

def chat(text: str, model: ModelConfig, user: str,
         on_event: Callable[[dict], None] | None = None) -> dict:
    """跑一轮 agent 对话。on_event 接收实时事件用于 SSE 流式。"""
    if not text.strip():
        return {"ok": False, "error": "请输入内容"}
    if not model.api_key:
        return {"ok": False, "error": f"模型 {model.label!r} 的 API key 未配置"}

    _emit(on_event, {
        "type": "started",
        "model": {"id": model.id, "label": model.label, "model_id": model.model_id, "format": model.format},
    })

    t0 = time.time()
    ctx = AgentContext(user=user)
    try:
        if model.format == "anthropic":
            result = _run_anthropic(text, model, ctx, on_event=on_event)
        elif model.format == "openai":
            result = _run_openai(text, model, ctx, on_event=on_event)
        else:
            return {"ok": False, "error": f"不支持的 format: {model.format!r}"}
    except Exception as e:
        logger.exception("agent run failed")
        err = {
            "ok": False,
            "error": f"LLM 调用失败: {e}",
            "tool_calls": ctx.tool_log,
            "duration_ms": int((time.time() - t0) * 1000),
        }
        _emit(on_event, {"type": "error", "error": err["error"]})
        return err

    return {
        **result,
        "tool_calls": ctx.tool_log,
        "dsl": ctx.final_dsl,
        "backtest_result": ctx.backtest_result_full,
        "duration_ms": int((time.time() - t0) * 1000),
        "model": {"id": model.id, "label": model.label, "model_id": model.model_id},
    }
