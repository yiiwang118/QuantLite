"""美股数据源（akshare）。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import akshare as ak
import polars as pl

from . import with_retry

logger = logging.getLogger(__name__)

# akshare 美股需要带交易所前缀的 symbol，比如 "106.AAPL"。
# 跑一次 stock_us_spot_em 把 symbol → 带前缀代码缓存起来。
_SYMBOL_CACHE: dict[str, str] = {}


@with_retry(max_attempts=3, base_delay=3.0)
def _load_symbol_map() -> None:
    df = ak.stock_us_spot_em()
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            code = str(row["代码"])
            if "." in code:
                ticker = code.split(".", 1)[1]
                _SYMBOL_CACHE[ticker] = code


# 知名美股的 prefix 兜底字典（避免每次拉数都过 stock_us_spot_em，那个接口很慢且容易掐连接）
_KNOWN_PREFIXES: dict[str, str] = {
    "AAPL": "105.AAPL",
    "MSFT": "105.MSFT",
    "GOOGL": "105.GOOGL",
    "GOOG": "105.GOOG",
    "AMZN": "105.AMZN",
    "META": "105.META",
    "NVDA": "105.NVDA",
    "TSLA": "105.TSLA",
    "JPM": "106.JPM",
    "V": "106.V",
    "UNH": "106.UNH",
    "BRK.A": "106.BRK_A",
    "JNJ": "106.JNJ",
    "WMT": "106.WMT",
    "PG": "106.PG",
    "MA": "106.MA",
    "HD": "106.HD",
    "BAC": "106.BAC",
    "ORCL": "106.ORCL",
    "ADBE": "105.ADBE",
    "NFLX": "105.NFLX",
    "INTC": "105.INTC",
    "AMD": "105.AMD",
}


def _resolve_full_symbol(symbol: str) -> str:
    """把 'AAPL' 解析为 '105.AAPL'（akshare 内部代码）。"""
    if symbol in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[symbol]
    if symbol in _KNOWN_PREFIXES:
        _SYMBOL_CACHE[symbol] = _KNOWN_PREFIXES[symbol]
        return _SYMBOL_CACHE[symbol]
    # 不在已知列表则去查 spot_em（成本高，可能失败）
    try:
        _load_symbol_map()
    except Exception as e:
        logger.warning(f"_load_symbol_map failed: {e}; falling back to 105.{symbol}")
    if symbol not in _SYMBOL_CACHE:
        _SYMBOL_CACHE[symbol] = f"105.{symbol}"
    return _SYMBOL_CACHE[symbol]


_EMPTY_SCHEMA = {
    "date": pl.Date, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
    "close": pl.Float64, "volume": pl.Int64, "amount": pl.Float64,
}


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_EMPTY_SCHEMA)


@with_retry(max_attempts=3, base_delay=2.0)
def _fetch_daily_em(symbol: str, start: date, end: date) -> pl.DataFrame:
    """东财（split-adjusted，含 amount）。"""
    full_symbol = _resolve_full_symbol(symbol)
    df = ak.stock_us_hist(
        symbol=full_symbol, period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    if df is None or df.empty:
        return _empty()
    rename_map = {
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "成交额": "amount",
    }
    df = df.rename(columns=rename_map)[list(rename_map.values())]
    return pl.from_pandas(df).with_columns(
        pl.col("date").cast(pl.Date),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
        pl.col("amount").cast(pl.Float64),
    ).sort("date")


@with_retry(max_attempts=3, base_delay=2.0)
def _fetch_daily_sina(symbol: str, start: date, end: date) -> pl.DataFrame:
    """新浪（split-adjusted，没有 amount，用 close*volume 估算）。"""
    df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
    if df is None or df.empty:
        return _empty()
    # stock_us_daily 没有 start_date/end_date 参数，要本地裁剪
    pdf = pl.from_pandas(df).with_columns(
        pl.col("date").cast(pl.Date),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
    )
    pdf = pdf.filter(
        (pl.col("date") >= start) & (pl.col("date") <= end)
    )
    # amount = close * volume（粗估）
    pdf = pdf.with_columns(
        (pl.col("close") * pl.col("volume").cast(pl.Float64)).alias("amount")
    ).select(list(_EMPTY_SCHEMA.keys()))
    return pdf.sort("date")


def fetch_daily(symbol: str, start: date, end: date) -> pl.DataFrame:
    """拉美股日频数据。东财失败降级到新浪。"""
    try:
        return _fetch_daily_em(symbol, start, end)
    except Exception as e:
        logger.warning(f"em failed for us:{symbol}: {e}; falling back to sina")
        return _fetch_daily_sina(symbol, start, end)


def fetch_calendar(start: date, end: date) -> list[date]:
    """美股交易日历。akshare 没有现成接口，用 NYSE 标准节假日近似（V1 用粗略版）。

    简单做法：返回工作日 - 美股节假日。如果未来要精确，换 pandas_market_calendars。
    """
    from datetime import date as _date

    # 简化：所有工作日都算交易日。后面 fetch_daily 会自然产生空白
    # （拉到的数据里就没那一天），上层用"交易日 = Parquet 中实际出现的日期"derive 也可以。
    # 这里返回工作日近似。
    out = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # 周一到周五
            out.append(cur)
        cur = cur + timedelta(days=1)
    return out


_US_INFO_CACHE: dict[str, dict] = {}

# 已知美股的简单 name 字典（避免每次都打 stock_us_spot_em）
_KNOWN_US_NAMES = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc. Class A", "GOOG": "Alphabet Inc. Class C",
    "AMZN": "Amazon.com Inc.", "META": "Meta Platforms Inc.",
    "NVDA": "NVIDIA Corporation", "TSLA": "Tesla Inc.",
    "JPM": "JPMorgan Chase & Co.", "V": "Visa Inc.",
    "UNH": "UnitedHealth Group Inc.", "JNJ": "Johnson & Johnson",
    "WMT": "Walmart Inc.", "PG": "Procter & Gamble Co.",
    "MA": "Mastercard Inc.", "HD": "Home Depot Inc.",
    "BAC": "Bank of America Corp.", "ORCL": "Oracle Corporation",
    "ADBE": "Adobe Inc.", "NFLX": "Netflix Inc.",
    "INTC": "Intel Corporation", "AMD": "Advanced Micro Devices Inc.",
}


def fetch_symbol_info(symbol: str) -> dict | None:
    """美股元信息：name（轻量版，优先用本地字典）。"""
    if symbol in _US_INFO_CACHE:
        return _US_INFO_CACHE[symbol]
    if symbol in _KNOWN_US_NAMES:
        info = {"name": _KNOWN_US_NAMES[symbol], "list_date": None, "status": "active"}
        _US_INFO_CACHE[symbol] = info
        return info
    # 兜底：用 spot_em 查（可能失败）
    try:
        df = ak.stock_us_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row["代码"])
                if "." in code:
                    ticker = code.split(".", 1)[1]
                    _US_INFO_CACHE[ticker] = {
                        "name": str(row.get("名称", ticker)),
                        "list_date": None,
                        "status": "active",
                    }
        return _US_INFO_CACHE.get(symbol, {"name": symbol, "list_date": None, "status": "active"})
    except Exception as e:
        logger.warning(f"fetch_symbol_info failed for us:{symbol}: {e}")
        return {"name": symbol, "list_date": None, "status": "active"}
