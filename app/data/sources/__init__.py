"""按市场分发的数据源。每个市场一个 source，统一 fetch 接口。"""
from __future__ import annotations

import logging
import time
from datetime import date
from functools import wraps

import polars as pl

logger = logging.getLogger(__name__)


def with_retry(max_attempts: int = 4, base_delay: float = 1.0):
    """指数退避重试。捕获网络异常（akshare 偶尔 RemoteDisconnected）。"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    msg = str(e).lower()
                    transient = (
                        "remotedisconnected" in msg
                        or "connection aborted" in msg
                        or "timed out" in msg
                        or "max retries" in msg
                        or "read timeout" in msg
                    )
                    if not transient or attempt == max_attempts:
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"{fn.__name__} attempt {attempt}/{max_attempts} failed: {e}; retry in {delay}s"
                    )
                    time.sleep(delay)
            raise last_err  # 兜底
        return wrapper
    return deco


from . import cn, us  # noqa: E402  must be after with_retry


class DataSource:
    """每个 source 模块需要实现的接口。"""

    @staticmethod
    def fetch_daily(symbol: str, start: date, end: date) -> pl.DataFrame:
        """拉一只股票的日频数据，schema = UNIVERSE_SCHEMA（除 market 由调用方填）。"""
        raise NotImplementedError

    @staticmethod
    def fetch_calendar(start: date, end: date) -> list[date]:
        """拉交易日历。"""
        raise NotImplementedError

    @staticmethod
    def fetch_symbol_info(symbol: str) -> dict | None:
        """拉单只股票的元信息（name、上市日、状态）。"""
        raise NotImplementedError


def get(market: str):
    """按市场返回 source 模块。"""
    if market == "cn":
        return cn
    if market == "us":
        return us
    raise ValueError(f"unsupported market: {market!r}")
