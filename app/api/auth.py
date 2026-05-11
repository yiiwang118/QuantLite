"""HTTP Basic Auth：从 users.yaml 读用户，bcrypt 校验 + 60 秒内存缓存。"""
from __future__ import annotations

import hashlib
import logging
import time
from functools import lru_cache
from pathlib import Path
from threading import Lock

import bcrypt
import yaml
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

logger = logging.getLogger(__name__)
security = HTTPBasic()

# 用一个真实 bcrypt hash 作为"用户不存在"的占位，防 timing attack
_DUMMY_HASH: bytes = bcrypt.hashpw(b"dummy-for-timing-mitigation", bcrypt.gensalt())

# 认证结果缓存：bcrypt 慢（~100ms），缓存 60s 大幅降低单次请求延迟
# 缓存 key 是 sha256(username + ":" + password)，不存明文
# 每个 worker 进程一份，无需跨进程同步
_AUTH_CACHE: dict[str, tuple[str, float]] = {}
_AUTH_CACHE_TTL_SECONDS = 60
_AUTH_CACHE_LOCK = Lock()


def _cache_key(credentials: HTTPBasicCredentials) -> str:
    raw = f"{credentials.username}:{credentials.password}".encode()
    return hashlib.sha256(raw).hexdigest()


def _cache_get(key: str) -> str | None:
    with _AUTH_CACHE_LOCK:
        entry = _AUTH_CACHE.get(key)
        if entry is None:
            return None
        username, expire = entry
        if time.time() >= expire:
            del _AUTH_CACHE[key]
            return None
        return username


def _cache_put(key: str, username: str) -> None:
    with _AUTH_CACHE_LOCK:
        _AUTH_CACHE[key] = (username, time.time() + _AUTH_CACHE_TTL_SECONDS)
        # 简单清理：缓存过大时清掉过期项
        if len(_AUTH_CACHE) > 256:
            now = time.time()
            for k, (_, exp) in list(_AUTH_CACHE.items()):
                if exp <= now:
                    del _AUTH_CACHE[k]


@lru_cache(maxsize=1)
def _load_users() -> dict[str, dict]:
    path = Path(settings.users_yaml)
    if not path.exists():
        logger.warning(f"users.yaml not found at {path}; auth will reject all")
        return {}
    data = yaml.safe_load(path.read_text())
    out = {}
    for u in data.get("users", []):
        out[u["username"]] = {
            "password_hash": u["password_hash"].encode(),
            "display_name": u.get("display_name", u["username"]),
        }
    return out


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    # 缓存命中 → 直接返回，省下 bcrypt 的 ~100ms
    key = _cache_key(credentials)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    users = _load_users()
    user = users.get(credentials.username)
    if user is None:
        # 用真实 bcrypt 调用消化时间，避免泄漏用户名是否存在
        bcrypt.checkpw(credentials.password.encode(), _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not bcrypt.checkpw(credentials.password.encode(), user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    _cache_put(key, credentials.username)
    return credentials.username
