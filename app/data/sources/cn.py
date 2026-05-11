"""A 股数据源（akshare）。"""
from __future__ import annotations

import logging
from datetime import date

import akshare as ak
import polars as pl

from . import with_retry

logger = logging.getLogger(__name__)


_EMPTY_SCHEMA = {
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "amount": pl.Float64,
}


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_EMPTY_SCHEMA)


def _normalize_em(df) -> pl.DataFrame:
    """东财（stock_zh_a_hist）原始 df → 标准 schema。"""
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


def _normalize_sina(df) -> pl.DataFrame:
    """新浪（stock_zh_a_daily）原始 df → 标准 schema。"""
    keep = ["date", "open", "high", "low", "close", "volume", "amount"]
    df = df[keep]
    return pl.from_pandas(df).with_columns(
        pl.col("date").cast(pl.Date),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
        pl.col("amount").cast(pl.Float64),
    ).sort("date")


def _sina_symbol(symbol: str) -> str:
    """600519 → sh600519，000001 → sz000001。"""
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    if symbol.startswith(("8", "4")):
        return f"bj{symbol}"  # 北交所
    return symbol


@with_retry(max_attempts=3, base_delay=2.0)
def _fetch_daily_em(symbol: str, start: date, end: date) -> pl.DataFrame:
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="hfq",
    )
    return _empty() if df is None or df.empty else _normalize_em(df)


@with_retry(max_attempts=3, base_delay=2.0)
def _fetch_daily_sina(symbol: str, start: date, end: date) -> pl.DataFrame:
    df = ak.stock_zh_a_daily(
        symbol=_sina_symbol(symbol),
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="hfq",
    )
    return _empty() if df is None or df.empty else _normalize_sina(df)


def fetch_daily(symbol: str, start: date, end: date) -> pl.DataFrame:
    """拉 A 股日频后复权数据。东财失败则降级到新浪。"""
    try:
        return _fetch_daily_em(symbol, start, end)
    except Exception as e:
        logger.warning(f"em failed for {symbol}: {e}; falling back to sina")
        return _fetch_daily_sina(symbol, start, end)


@with_retry(max_attempts=3, base_delay=2.0)
def fetch_calendar(start: date, end: date) -> list[date]:
    """A 股交易日历。"""
    df = ak.tool_trade_date_hist_sina()
    if df is None or df.empty:
        return []
    pdf = pl.from_pandas(df)
    # 列名是 trade_date
    col = "trade_date" if "trade_date" in pdf.columns else pdf.columns[0]
    out = pdf.with_columns(pl.col(col).cast(pl.Date)).filter(
        (pl.col(col) >= start) & (pl.col(col) <= end)
    )[col].to_list()
    return sorted(out)


def fetch_symbol_info(symbol: str) -> dict | None:
    """A 股元信息：name + 上市日。"""
    try:
        # 实时行情里有 name 和 list_date；用静态接口更轻
        info = ak.stock_individual_info_em(symbol=symbol)
        if info is None or info.empty:
            return None
        kv = dict(zip(info["item"], info["value"]))
        return {
            "name": kv.get("股票简称") or kv.get("名称") or symbol,
            "list_date": _parse_list_date(kv.get("上市时间")),
            "status": "active",
        }
    except Exception as e:
        logger.warning(f"fetch_symbol_info failed for cn:{symbol}: {e}")
        return None


def _parse_list_date(v) -> str | None:
    """akshare 的上市时间可能是 19980429 / 1998-04-29 / 19980429.0 等。"""
    if v is None:
        return None
    s = str(v).strip().split(".")[0]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s if "-" in s else None
