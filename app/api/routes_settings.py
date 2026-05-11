"""AI 设置 API：多模型列表。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app import ai
from app.ai import agent as agent_mod
from app.ai.config import load_config, save_config, merge_update, masked_view, ModelConfig
from app.ai.tools import AgentContext
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class ModelIn(BaseModel):
    id: str | None = None             # 新增时不传
    label: str = ""
    format: str = "openai"            # openai | anthropic
    api_key: str = ""                 # "" 或 "***" 表示保留旧值
    model_id: str = ""
    base_url: str = ""


class AIConfigIn(BaseModel):
    models: list[ModelIn]
    default_model_id: str = ""


# ─── 读 ──────────────────────────────────────────────────────

@router.get("/settings/ai")
def get_ai_settings(_user: str = Depends(get_current_user)):
    cfg = load_config()
    return masked_view(cfg)


# ─── 写（替换整个列表）──────────────────────────────────────

@router.post("/settings/ai")
def update_ai_settings(
    req: AIConfigIn = Body(...),
    user: str = Depends(get_current_user),
):
    # 校验
    valid_formats = {"openai", "anthropic"}
    for m in req.models:
        if m.format not in valid_formats:
            raise HTTPException(400, f"format 必须是 {valid_formats}，实际 {m.format!r}")
        if not m.label.strip():
            raise HTTPException(400, "每个模型必须有 label")
        if not m.model_id.strip():
            raise HTTPException(400, f"模型 {m.label!r} 缺 model_id")
    existing = load_config()
    new_cfg = merge_update(existing, req.model_dump())
    save_config(new_cfg, user)
    return masked_view(new_cfg)


# ─── 删一个模型 ─────────────────────────────────────────────

@router.delete("/settings/ai/models/{model_id}")
def delete_model(model_id: str, user: str = Depends(get_current_user)):
    cfg = load_config()
    if not any(m.id == model_id for m in cfg.models):
        raise HTTPException(404, "model not found")
    cfg.models = [m for m in cfg.models if m.id != model_id]
    if cfg.default_model_id == model_id:
        cfg.default_model_id = cfg.models[0].id if cfg.models else ""
    save_config(cfg, user)
    return masked_view(cfg)


# ─── 测试 ────────────────────────────────────────────────────

class AITestRequest(BaseModel):
    # 两种方式：要么按 id 测已配置的，要么直接传完整 model 配置
    model_id: str | None = None
    inline: ModelIn | None = None
    text: str = "买动量最强的 3 只 A 股，每周换仓"


@router.post("/settings/ai/test")
def test_ai(
    req: AITestRequest = Body(default=AITestRequest()),
    user: str = Depends(get_current_user),
):
    """跑一次真实 LLM 调用（带工具）看是否成功。

    - 传 inline 全套字段 → 用临时配置（不入库），适合保存前测试
    - 传 model_id → 用已保存的那个模型
    - 都不传 → 用 default
    """
    if req.inline is not None:
        # 用临时配置（api_key 留空 / *** 时回退到已保存的同 id 的值）
        existing = load_config()
        merged = merge_update(existing, {"models": [req.inline.model_dump()]})
        if not merged.models:
            return {"ok": False, "error": "inline 配置无效"}
        model = merged.models[0]
    else:
        cfg = load_config()
        model = cfg.get(req.model_id)
        if model is None:
            return {"ok": False, "error": "未找到模型；先在设置页添加并保存"}

    result = ai.chat(req.text, model, user=user)
    return {**result, "tested_by": user}
