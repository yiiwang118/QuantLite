"""Smoke tests：不依赖网络，只验证存储层契约。"""
from __future__ import annotations

import os
import tempfile

import polars as pl
import pytest


@pytest.fixture(autouse=True)
def isolated_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # settings 是模块级单例，要重新读
    from app import config
    config.settings.data_cache_dir = tmp_path / "data_cache"
    config.settings.quant_db = tmp_path / "quant.db"
    config.settings.users_yaml = tmp_path / "users.yaml"
    yield


def test_init_creates_skeleton():
    from app.data import loader
    meta = loader.init_storage()
    assert meta["schema_version"] == 1
    assert "cn" in meta["markets"]
    assert "us" in meta["markets"]
    assert (loader._data_dir() / "daily" / "cn").exists()
    assert (loader._data_dir() / "daily" / "us").exists()
    assert (loader._data_dir() / ".lock").exists()


def test_db_init_idempotent():
    from app import db
    db.init_db()
    db.init_db()  # 二次调用应无副作用
    stats = db.db_stats()
    assert stats["symbols_total"] == 0


def test_universe_schema_constants():
    from app.data import (
        MARKETS,
        SAMPLE_CN_UNIVERSE,
        SAMPLE_US_UNIVERSE,
        UNIVERSE_COLUMNS,
    )
    assert "cn" in MARKETS and "us" in MARKETS
    assert len(SAMPLE_CN_UNIVERSE) == 10
    assert len(SAMPLE_US_UNIVERSE) == 10
    assert "AAPL" in SAMPLE_US_UNIVERSE
    assert UNIVERSE_COLUMNS == (
        "date", "market", "symbol", "open", "high", "low", "close", "volume", "amount"
    )


def test_load_universe_empty_returns_correct_schema():
    from app.data import loader
    loader.init_storage()
    df = loader.load_universe([("cn", "999999")])
    # 没数据但 schema 要对
    assert df.columns == [
        "date", "market", "symbol", "open", "high", "low", "close", "volume", "amount"
    ]
    assert df.height == 0


def test_get_universe_parsing():
    from app.data import get_universe
    items = get_universe("cn:sample")
    assert all(m == "cn" for m, _ in items)
    assert len(items) == 10
    items_us = get_universe("us:sample")
    assert all(m == "us" for m, _ in items_us)
    with pytest.raises(ValueError):
        get_universe("hk:sample")
