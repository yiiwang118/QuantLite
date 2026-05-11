"""FastAPI 入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app import __version__
from app.api.routes_data import router as data_router
from app.api.routes_backtest import router as backtest_router
from app.api.routes_ai import router as ai_router
from app.api.routes_settings import router as settings_router
from app.config import settings
from app.data import loader
from app import scheduler as sched


class CachedStaticFiles(StaticFiles):
    """Hashed assets are immutable — long cache."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["cache-control"] = "public, max-age=31536000, immutable"
        return resp


logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing storage...")
    loader.init_storage()
    logger.info("Storage ready: %s", loader.cache_overview())
    sched.start_scheduler()
    yield
    sched.stop_scheduler()


app = FastAPI(
    title="Quant Lite",
    version=__version__,
    description="Small-team quant research and backtesting tool",
    lifespan=lifespan,
)

# GZip：JSON 响应能压 3-5 倍
app.add_middleware(GZipMiddleware, minimum_size=512)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API
app.include_router(data_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "version": __version__}


# 前端静态资源（带 ETag + 长缓存）
_dist = Path(settings.frontend_dist)
if _dist.exists():
    # /assets/* 是 Vite 出的带 hash 文件名，可以长缓存
    assets_dir = _dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", CachedStaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # SPA 路由：所有未匹配的 GET 走 index.html（让 vue-router 处理）
        index = _dist / "index.html"
        if full_path.startswith("api/"):
            # 不应该到这（前面 router 已经处理），fallback 兜底
            return {"error": "not found"}
        if full_path and (_dist / full_path).exists() and (_dist / full_path).is_file():
            return FileResponse(_dist / full_path)
        return FileResponse(index)

    logger.info("Frontend mounted from %s", _dist)
else:
    @app.get("/")
    def root_no_frontend():
        return {
            "ok": True,
            "msg": "Quant Lite backend is running. Frontend not built yet.",
            "build_hint": "cd frontend && npm install && npm run build",
            "api_docs": "/docs",
        }
