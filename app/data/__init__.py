"""数据模块的对外常量与 schema 契约。

下游（DSL 执行器、引擎、API、前端）都从这里 import，不要复制副本。
"""
from __future__ import annotations

import polars as pl

# ─── Schema 契约 ─────────────────────────────────────────────

UNIVERSE_SCHEMA: dict[str, pl.DataType] = {
    "date": pl.Date,
    "market": pl.Utf8,
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "amount": pl.Float64,
}
"""所有 OHLCV 长表的固定 schema。下游 import 它做断言。"""

UNIVERSE_COLUMNS: tuple[str, ...] = tuple(UNIVERSE_SCHEMA.keys())

PARQUET_SCHEMA_VERSION = 1
"""schema 版本号；不匹配时报错让用户清缓存。"""


# ─── 市场定义 ────────────────────────────────────────────────

MARKETS: tuple[str, ...] = ("cn", "us")
"""支持的市场。新增市场要更新这里 + 加 source 模块 + 加 universe。"""

MARKET_LABELS: dict[str, str] = {
    "cn": "A 股",
    "us": "美股",
}

MARKET_CURRENCIES: dict[str, str] = {
    "cn": "CNY",
    "us": "USD",
}


# ─── 样本股票池 ──────────────────────────────────────────────

# A 股大盘白马（10 只，快速测试）
SAMPLE_CN_UNIVERSE: tuple[str, ...] = (
    "600519",  # 贵州茅台
    "601318",  # 中国平安
    "000858",  # 五粮液
    "600036",  # 招商银行
    "000333",  # 美的集团
    "601012",  # 隆基绿能
    "600276",  # 恒瑞医药
    "002594",  # 比亚迪
    "601888",  # 中国中免
    "300750",  # 宁德时代
)

# A 股 50 只大盘股（hs300 头部权重股）
HS50_UNIVERSE: tuple[str, ...] = (
    # sample 池里的 10 只
    "600519", "601318", "000858", "600036", "000333",
    "601012", "600276", "002594", "601888", "300750",
    # 新增 40 只大盘股
    "601398",  # 工商银行
    "600028",  # 中国石化
    "601988",  # 中国银行
    "601857",  # 中国石油
    "601628",  # 中国人寿
    "601288",  # 农业银行
    "601658",  # 邮储银行
    "601728",  # 中国电信
    "600030",  # 中信证券
    "600887",  # 伊利股份
    "002475",  # 立讯精密
    "600009",  # 上海机场
    "601066",  # 中信建投
    "600438",  # 通威股份
    "601601",  # 中国太保
    "600585",  # 海螺水泥
    "000725",  # 京东方A
    "600690",  # 海尔智家
    "601225",  # 陕西煤业
    "002714",  # 牧原股份
    "600031",  # 三一重工
    "600196",  # 复星医药
    "601633",  # 长城汽车
    "601881",  # 中国银河
    "000063",  # 中兴通讯
    "601088",  # 中国神华（替代被吸并的海通证券 600837）
    "601668",  # 中国建筑
    "601336",  # 新华保险
    "601169",  # 北京银行
    "600999",  # 招商证券
    "601138",  # 工业富联
    "600547",  # 山东黄金
    "601155",  # 新城控股
    "000651",  # 格力电器
    "600600",  # 青岛啤酒
    "000792",  # 盐湖股份
    "000625",  # 长安汽车
    "600406",  # 国电南瑞
    "002241",  # 歌尔股份
    "600362",  # 江西铜业
)

# 美股 10 只大盘（快速测试）
SAMPLE_US_UNIVERSE: tuple[str, ...] = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "JPM", "V", "UNH",
)

# 美股 50 只大盘股（标普 100 头部权重股，人工精选）
SP50_UNIVERSE: tuple[str, ...] = (
    # sample 池里的 10 只
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "JPM", "V", "UNH",
    # 新增 40 只
    "GOOG", "BRK.B", "XOM", "JNJ", "WMT",
    "PG", "MA", "HD", "AVGO", "CVX",
    "LLY", "ABBV", "KO", "MRK", "PEP",
    "BAC", "COST", "TMO", "ADBE", "MCD",
    "CSCO", "ABT", "CRM", "ACN", "NFLX",
    "AMD", "DHR", "NKE", "TXN", "LIN",
    "INTC", "PFE", "ORCL", "WFC", "DIS",
    "HON", "NEE", "AMGN", "RTX", "COP",
)

# 命名 universe 注册表（前端下拉用）
NAMED_UNIVERSES: dict[str, tuple[str, ...]] = {
    "cn:sample": SAMPLE_CN_UNIVERSE,
    "cn:hs50": HS50_UNIVERSE,
    "us:sample": SAMPLE_US_UNIVERSE,
    "us:sp50": SP50_UNIVERSE,
}


def get_universe(name: str) -> list[tuple[str, str]]:
    """把命名 universe 解析成 [(market, symbol), ...]。

    name 形如 "cn:sample" / "us:sample"。
    """
    if name not in NAMED_UNIVERSES:
        raise ValueError(f"unknown universe: {name!r}, available: {list(NAMED_UNIVERSES)}")
    market = name.split(":", 1)[0]
    if market not in MARKETS:
        raise ValueError(f"unknown market in universe {name!r}: {market!r}")
    return [(market, sym) for sym in NAMED_UNIVERSES[name]]
