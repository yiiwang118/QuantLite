"""AI 配置：多模型列表 + 默认模型。

配置存在 SQLite `settings` 表的 `ai.config` 键里，值是 JSON：

{
  "models": [
    {
      "id": "uuid-or-slug",
      "label": "DeepSeek V4 Pro",
      "format": "openai" | "anthropic",
      "api_key": "sk-...",
      "model_id": "deepseek-v4-pro",
      "base_url": "https://api.deepseek.com"
    },
    ...
  ],
  "default_model_id": "uuid-or-slug"
}

api_key 在 GET 返回时做 mask。POST 时 "***" 或空字符串表示保持原值。
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from app import db


CONFIG_KEY = "ai.config"


@dataclass
class ModelConfig:
    id: str
    label: str
    format: str           # "openai" | "anthropic"
    api_key: str
    model_id: str
    base_url: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "format": self.format,
            "api_key": self.api_key, "model_id": self.model_id,
            "base_url": self.base_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        return cls(
            id=d["id"],
            label=d.get("label") or d["id"],
            format=d.get("format") or "openai",
            api_key=d.get("api_key") or "",
            model_id=d.get("model_id") or "",
            base_url=d.get("base_url") or "",
        )


@dataclass
class AIConfig:
    models: list[ModelConfig] = field(default_factory=list)
    default_model_id: str = ""

    def to_dict(self) -> dict:
        return {
            "models": [m.to_dict() for m in self.models],
            "default_model_id": self.default_model_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AIConfig":
        return cls(
            models=[ModelConfig.from_dict(m) for m in d.get("models", [])],
            default_model_id=d.get("default_model_id", ""),
        )

    def get(self, model_id: str | None = None) -> ModelConfig | None:
        if not self.models:
            return None
        target_id = model_id or self.default_model_id
        if not target_id:
            return self.models[0]  # fallback to first
        for m in self.models:
            if m.id == target_id:
                return m
        return None


def mint_id() -> str:
    return secrets.token_hex(6)


def load_config() -> AIConfig:
    """从 SQLite 读取（兼容老的散装 settings）。"""
    raw = db.get_setting(CONFIG_KEY)
    if raw:
        try:
            return AIConfig.from_dict(json.loads(raw))
        except Exception:
            pass
    # 兜底：尝试从老的散装设置迁移
    return _migrate_legacy() or AIConfig()


def save_config(cfg: AIConfig, updated_by: str) -> None:
    db.set_setting(CONFIG_KEY, json.dumps(cfg.to_dict(), ensure_ascii=False), updated_by)


def _migrate_legacy() -> AIConfig | None:
    """老格式（散装 ai.anthropic.api_key 等）→ 新多模型格式。"""
    legacy = db.get_settings_prefix("ai.")
    if not legacy:
        return None
    models: list[ModelConfig] = []
    anth_key = legacy.get("ai.anthropic.api_key")
    if anth_key:
        models.append(ModelConfig(
            id=mint_id(),
            label="Anthropic Claude (legacy)",
            format="anthropic",
            api_key=anth_key,
            model_id=legacy.get("ai.anthropic.model") or "claude-3-5-haiku-20241022",
            base_url=legacy.get("ai.anthropic.base_url") or "",
        ))
    oai_key = legacy.get("ai.openai.api_key")
    if oai_key:
        models.append(ModelConfig(
            id=mint_id(),
            label="OpenAI (legacy)",
            format="openai",
            api_key=oai_key,
            model_id=legacy.get("ai.openai.model") or "gpt-4o-mini",
            base_url=legacy.get("ai.openai.base_url") or "",
        ))
    if not models:
        return None
    return AIConfig(models=models, default_model_id=models[0].id)


def merge_update(
    existing: AIConfig,
    incoming: dict,
    placeholder: str = "***",
) -> AIConfig:
    """根据 POST 来的新配置合并：
    - incoming["models"] 给的每个项里，api_key == "" 或 "***" 都表示保留旧值
    - 通过 id 匹配；不存在 id 视为新增；旧 id 不在 incoming 里则删除
    """
    by_id = {m.id: m for m in existing.models}
    new_models: list[ModelConfig] = []
    for m in incoming.get("models", []):
        mid = m.get("id") or mint_id()
        old = by_id.get(mid)
        api_key = m.get("api_key", "")
        # 保留旧值的两种情形
        if (api_key == "" or api_key == placeholder) and old:
            api_key = old.api_key
        new_models.append(ModelConfig(
            id=mid,
            label=m.get("label") or "Untitled",
            format=m.get("format") or "openai",
            api_key=api_key,
            model_id=m.get("model_id") or "",
            base_url=m.get("base_url") or "",
        ))
    default_id = incoming.get("default_model_id") or ""
    valid_ids = {m.id for m in new_models}
    if default_id not in valid_ids:
        default_id = new_models[0].id if new_models else ""
    return AIConfig(models=new_models, default_model_id=default_id)


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) < 10:
        return "***"
    return value[:4] + "..." + value[-4:]


def masked_view(cfg: AIConfig) -> dict:
    return {
        "models": [
            {
                "id": m.id,
                "label": m.label,
                "format": m.format,
                "api_key_set": bool(m.api_key),
                "api_key_masked": mask(m.api_key),
                "model_id": m.model_id,
                "base_url": m.base_url,
            }
            for m in cfg.models
        ],
        "default_model_id": cfg.default_model_id,
    }
