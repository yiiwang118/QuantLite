"""SQLite 元数据库。

Phase 1：symbols / trading_calendar
Phase 5（占位）：strategies / backtests

v2 schema：symbols 加 rows / min_date / max_date / size_bytes 四列，
避免每次列表 API 都读 Parquet 头。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

CURRENT_DB_VERSION = 3


SCHEMA_V1_FRESH = """
CREATE TABLE IF NOT EXISTS symbols (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    list_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_fetched_at TEXT,
    rows INTEGER NOT NULL DEFAULT 0,
    min_date TEXT,
    max_date TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (market, symbol)
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    market TEXT NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (market, date)
);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    dsl TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER,
    dsl TEXT NOT NULL,
    params TEXT NOT NULL,
    metrics TEXT NOT NULL,
    nav_curve TEXT NOT NULL,
    duration_ms INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_backtests_strategy ON backtests(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtests_created ON backtests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtests_created_by ON backtests(created_by);
CREATE INDEX IF NOT EXISTS idx_strategies_created_by ON strategies(created_by);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by TEXT NOT NULL
);
"""


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """给 symbols 表加 rows / min_date / max_date / size_bytes 四列。"""
    for col, ddl in [
        ("rows", "INTEGER NOT NULL DEFAULT 0"),
        ("min_date", "TEXT"),
        ("max_date", "TEXT"),
        ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE symbols ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """加 settings 表（KV store）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_by TEXT NOT NULL
        );
    """)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(settings.quant_db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """初始化数据库（幂等）。版本不匹配走自动迁移。"""
    Path(settings.quant_db).parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(SCHEMA_V1_FRESH)
            conn.execute(f"PRAGMA user_version = {CURRENT_DB_VERSION}")
        elif version == 1:
            _migrate_v1_to_v2(conn)
            _migrate_v2_to_v3(conn)
            conn.execute(f"PRAGMA user_version = {CURRENT_DB_VERSION}")
        elif version == 2:
            _migrate_v2_to_v3(conn)
            conn.execute(f"PRAGMA user_version = {CURRENT_DB_VERSION}")
        elif version == CURRENT_DB_VERSION:
            pass
        elif version > CURRENT_DB_VERSION:
            raise RuntimeError(
                f"DB schema version {version} > code version {CURRENT_DB_VERSION}; "
                "upgrade code or restore from older backup."
            )
        else:
            raise RuntimeError(
                f"unsupported DB version {version}; manual migration needed"
            )


# ─── symbols 表 ──────────────────────────────────────────────

def upsert_symbol(
    market: str,
    symbol: str,
    name: str,
    list_date: str | None = None,
    status: str = "active",
    last_fetched_at: str | None = None,
    rows: int | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    size_bytes: int | None = None,
) -> None:
    """新增或更新 symbol 元信息 + 缓存统计。None 字段不覆盖现有值。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO symbols
                (market, symbol, name, list_date, status, last_fetched_at,
                 rows, min_date, max_date, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, symbol) DO UPDATE SET
                name = excluded.name,
                list_date = COALESCE(excluded.list_date, symbols.list_date),
                status = excluded.status,
                last_fetched_at = COALESCE(excluded.last_fetched_at, symbols.last_fetched_at),
                rows = COALESCE(excluded.rows, symbols.rows),
                min_date = COALESCE(excluded.min_date, symbols.min_date),
                max_date = COALESCE(excluded.max_date, symbols.max_date),
                size_bytes = COALESCE(excluded.size_bytes, symbols.size_bytes)
            """,
            (market, symbol, name, list_date, status, last_fetched_at,
             rows, min_date, max_date, size_bytes),
        )


def update_symbol_stats(
    market: str,
    symbol: str,
    rows: int,
    min_date: str | None,
    max_date: str | None,
    size_bytes: int,
    last_fetched_at: str | None = None,
) -> None:
    """只更新 cache 统计 + 最后抓取时间。"""
    last_fetched_at = last_fetched_at or _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE symbols
            SET rows = ?, min_date = ?, max_date = ?, size_bytes = ?, last_fetched_at = ?
            WHERE market = ? AND symbol = ?
            """,
            (rows, min_date, max_date, size_bytes, last_fetched_at, market, symbol),
        )


def get_symbol(market: str, symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM symbols WHERE market = ? AND symbol = ?",
            (market, symbol),
        ).fetchone()
        return dict(row) if row else None


def list_symbols(market: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if market:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE market = ? ORDER BY market, symbol",
                (market,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM symbols ORDER BY market, symbol"
            ).fetchall()
        return [dict(r) for r in rows]


# ─── trading_calendar 表 ────────────────────────────────────

def upsert_calendar(market: str, dates: list[str]) -> int:
    if not dates:
        return 0
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO trading_calendar (market, date) VALUES (?, ?)",
            [(market, d) for d in dates],
        )
        return conn.total_changes


def list_calendar(market: str, start: str | None = None, end: str | None = None) -> list[str]:
    with get_conn() as conn:
        if start and end:
            rows = conn.execute(
                "SELECT date FROM trading_calendar WHERE market = ? AND date BETWEEN ? AND ? ORDER BY date",
                (market, start, end),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date FROM trading_calendar WHERE market = ? ORDER BY date",
                (market,),
            ).fetchall()
        return [r[0] for r in rows]


# ─── strategies 表 ──────────────────────────────────────────

def save_strategy(name: str, dsl: str, created_by: str) -> int:
    """新增或更新（按 name UNIQUE）。返回 strategy id。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM strategies WHERE name = ?", (name,)
        ).fetchone()
        if row:
            sid = row["id"]
            conn.execute(
                """UPDATE strategies
                   SET dsl = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (dsl, sid),
            )
            return sid
        cur = conn.execute(
            """INSERT INTO strategies (name, dsl, created_by)
               VALUES (?, ?, ?)""",
            (name, dsl, created_by),
        )
        return cur.lastrowid


def get_strategy(strategy_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
        ).fetchone()
        return dict(row) if row else None


def get_strategy_by_name(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM strategies WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None


def list_strategies() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM strategies ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_strategy(strategy_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
        return cur.rowcount > 0


# ─── backtests 表 ───────────────────────────────────────────

def save_backtest(
    *,
    strategy_id: int | None,
    dsl: str,
    params: str,        # JSON
    metrics: str,       # JSON
    nav_curve: str,     # JSON
    duration_ms: int,
    created_by: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO backtests
               (strategy_id, dsl, params, metrics, nav_curve,
                duration_ms, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (strategy_id, dsl, params, metrics, nav_curve,
             duration_ms, created_by),
        )
        return cur.lastrowid


def get_backtest(backtest_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT b.*, s.name AS strategy_name
               FROM backtests b
               LEFT JOIN strategies s ON b.strategy_id = s.id
               WHERE b.id = ?""",
            (backtest_id,),
        ).fetchone()
        return dict(row) if row else None


def list_backtests(limit: int = 50) -> list[dict]:
    """按时间倒序列回测记录；不带 nav_curve（payload 大），需要时再 get_backtest。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT b.id, b.strategy_id, s.name AS strategy_name,
                      b.dsl, b.params, b.metrics, b.duration_ms,
                      b.created_by, b.created_at
               FROM backtests b
               LEFT JOIN strategies s ON b.strategy_id = s.id
               ORDER BY b.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_backtest(backtest_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM backtests WHERE id = ?", (backtest_id,))
        return cur.rowcount > 0


# ─── settings 表（KV 存储，给 AI 配置等运行时改动用）───────

def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def get_settings_prefix(prefix: str) -> dict[str, str]:
    """按前缀批量取，prefix 包含末尾的 '.'。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE ?",
            (prefix + "%",),
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str, updated_by: str) -> None:
    """upsert。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_by)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = datetime('now'),
                updated_by = excluded.updated_by
            """,
            (key, value, updated_by),
        )


def delete_setting(key: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return cur.rowcount > 0


# ─── 全局统计 ───────────────────────────────────────────────

def db_stats() -> dict[str, Any]:
    """概览页用，所有数字从 DB 一次查出来。"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS symbols_total,
                   COALESCE(SUM(rows), 0) AS rows_total,
                   COALESCE(SUM(size_bytes), 0) AS size_bytes_total
            FROM symbols
        """).fetchone()
        symbols_total = row["symbols_total"]
        rows_total = row["rows_total"]
        size_bytes_total = row["size_bytes_total"]

        by_market_rows = conn.execute("""
            SELECT market, COUNT(*) AS symbols, COALESCE(SUM(rows), 0) AS rows,
                   COALESCE(SUM(size_bytes), 0) AS size_bytes
            FROM symbols GROUP BY market
        """).fetchall()
        by_market = {
            r["market"]: {
                "symbols": r["symbols"],
                "rows": r["rows"],
                "size_bytes": r["size_bytes"],
            }
            for r in by_market_rows
        }

        calendar_total = conn.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0]
        calendar_by_market = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT market, COUNT(*) FROM trading_calendar GROUP BY market"
            ).fetchall()
        }
        strategies_total = conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]
        backtests_total = conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0]
    return {
        "symbols_total": symbols_total,
        "rows_total": rows_total,
        "size_bytes_total": size_bytes_total,
        "symbols_by_market": by_market,
        "calendar_total": calendar_total,
        "calendar_by_market": calendar_by_market,
        "strategies_total": strategies_total,
        "backtests_total": backtests_total,
    }
