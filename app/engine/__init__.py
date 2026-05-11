"""回测引擎对外接口。"""
from app.engine.backtest import BacktestResult, run
from app.engine.metrics import compute_metrics

__all__ = ["run", "BacktestResult", "compute_metrics"]
