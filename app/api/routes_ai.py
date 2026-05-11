"""AI 模块 API：agent 对话（含工具调用 + SSE 流式）+ 会话历史。"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import ai, db
from app.ai.config import load_config
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    text: str = Field(..., description="自然语言请求")
    model_id: Optional[str] = Field(default=None)


def _resolve_model(model_id: str | None):
    cfg = load_config()
    model = cfg.get(model_id)
    if model is None:
        raise HTTPException(503, "未配置任何模型；先去『设置』页添加一个")
    if not model.api_key:
        raise HTTPException(503, f"模型 {model.label!r} 的 API key 未配置")
    return model


# ─── 非流式（保留兼容）─────────────────────────────────────

@router.post("/ai/chat")
async def post_chat(req: ChatRequest, user: str = Depends(get_current_user)):
    model = _resolve_model(req.model_id)
    result = await asyncio.to_thread(ai.chat, req.text, model, user)
    return {**result, "triggered_by": user}


# ─── 流式 SSE ───────────────────────────────────────────────

@router.post("/ai/chat/stream")
async def stream_chat(req: ChatRequest, user: str = Depends(get_current_user)):
    """Server-Sent Events 流：每个事件一行 `data: {json}\\n\\n`。

    事件类型：
    - started / thinking / thinking_text / tool_call_start / tool_call_end
    - final_message / done / error
    """
    model = _resolve_model(req.model_id)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    SENTINEL = object()

    def on_event(event: dict) -> None:
        # 从 worker 线程被调用，线程安全地丢到 queue
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def producer():
        try:
            result = await asyncio.to_thread(ai.chat, req.text, model, user, on_event)
            await queue.put({"type": "done", "result": {**result, "triggered_by": user}})
        except Exception as e:
            logger.exception("stream chat failed")
            await queue.put({"type": "error", "error": str(e)})
        finally:
            await queue.put(SENTINEL)

    async def event_gen():
        asyncio.create_task(producer())
        last_heartbeat = loop.time()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                # 心跳：每 10s 发个注释，防代理超时
                yield ": heartbeat\n\n"
                continue
            if event is SENTINEL:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁止 nginx buffer
            "Connection": "keep-alive",
        },
    )


@router.get("/ai/status")
def ai_status(_user: str = Depends(get_current_user)):
    cfg = load_config()
    model = cfg.get(None)
    if model is None or not model.api_key:
        return {"enabled": False, "models": [], "default_model_id": ""}
    return {
        "enabled": True,
        "default_model_id": cfg.default_model_id,
        "models": [
            {"id": m.id, "label": m.label, "format": m.format, "model_id": m.model_id,
             "configured": bool(m.api_key)}
            for m in cfg.models
        ],
    }


# ─── 会话历史（per-user）────────────────────────────────────


def _make_title(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = (m.get("text") or "").strip().replace("\n", " ")
            return (t[:30] + "…") if len(t) > 30 else (t or "新会话")
    return "新会话"


class SessionCreate(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    title: Optional[str] = None


class SessionUpdate(BaseModel):
    messages: Optional[list[dict]] = None
    title: Optional[str] = None


@router.get("/ai/sessions")
def list_sessions(user: str = Depends(get_current_user)):
    return {"sessions": db.chat_session_list(user, limit=50)}


@router.post("/ai/sessions")
def create_session(req: SessionCreate, user: str = Depends(get_current_user)):
    sid = secrets.token_urlsafe(9)
    title = req.title or _make_title(req.messages)
    db.chat_session_create(sid, user, title, req.messages)
    return {"id": sid, "title": title}


@router.get("/ai/sessions/{sid}")
def get_session(sid: str, user: str = Depends(get_current_user)):
    s = db.chat_session_get(sid, user)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.put("/ai/sessions/{sid}")
def update_session(sid: str, req: SessionUpdate, user: str = Depends(get_current_user)):
    if req.messages is None and req.title is None:
        raise HTTPException(400, "messages 和 title 至少给一个")
    # 如果改 messages 但没给 title，且当前 title 是默认值，重新生成
    title = req.title
    if title is None and req.messages is not None:
        cur = db.chat_session_get(sid, user)
        if cur and (cur["title"] == "新会话" or cur["title"].endswith("…")):
            new_title = _make_title(req.messages)
            if new_title != cur["title"]:
                title = new_title
    ok = db.chat_session_update(sid, user, messages=req.messages, title=title)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


@router.delete("/ai/sessions/{sid}")
def delete_session(sid: str, user: str = Depends(get_current_user)):
    ok = db.chat_session_delete(sid, user)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"ok": True}
