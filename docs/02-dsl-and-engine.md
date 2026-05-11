# DSL 与回测引擎

## DSL 语法

```
factor IDENT = expr
strategy {
  universe:  IDENT:IDENT     # cn:sample | cn:hs50 | cn:csi300 | us:sample | us:sp50 | us:nasdaq100
  signal:    IDENT
  select:    top NUMBER                  # 仅多头：选信号 top N 等权
  # 或:    top NUMBER bottom NUMBER     # 多空：top N 做多 + bottom M 做空
  rebalance: daily | weekly | monthly
  cost:      NUMBER          # 可选，单边成本（如 0.001 = 10 bps），默认 0
  start:     YYYY-MM-DD       # 可选
  end:       YYYY-MM-DD       # 可选
}

expr = NUMBER | IDENT | -expr | expr (+|-|*|/) expr | OPERATOR(arg, ...)
```

### 18 个算子

| 类别 | 算子 | 第 N 个参数为窗口 |
|---|---|---|
| 时序窗口 | `delay(x, n)`、`ma(x, n)`、`std(x, n)`、`sum(x, n)`、`max_ts(x, n)`、`min_ts(x, n)` | n |
| 时序排序/位置 | `ts_argmax(x, n)`、`ts_argmin(x, n)`、`ts_rank(x, n)`、`decay_linear(x, n)` | n |
| 时序双参 | `corr(x, y, n)` | n |
| 时序单参 | `returns(x)` | — |
| 横截面 | `rank(x)`、`zscore(x)` | — |
| 数学 | `abs(x)`、`log(x)`、`sign(x)` | — |

### 字段白名单

`open / high / low / close / volume / amount / turnover_rate / market_cap`

字段和算子都白名单制；不在白名单的引用 → parser 直接拒。窗口必须**非负整数常量**（不允许变量或负数），堵死前视偏差的第一道门。

## 三层防前视偏差

```
1. Parser 检查：delay(x, n) 的 n 必须 >= 0 的整数常量
2. Executor 执行：所有时序算子用 .shift(n) 拿 t-n 时刻的值
3. Engine 结算：next_ret(s, t) = close(s, t+1) / close(s, t) - 1
                即 t 日选股，用 t+1 日 close 算 t→t+1 的收益
```

## 编译流程

```
DSL 字符串
    │
    ▼  app/dsl/lexer.py
Token 流
    │
    ▼  app/dsl/parser.py（递归下降）
AST（FactorDef / StrategyDef / Expr）
    │
    ▼  app/dsl/whitelist.py 校验字段 + 算子
合法 AST
    │
    ▼  app/dsl/executor.py
Polars 表达式 (pl.Expr)
    │
    ▼  pl.LazyFrame.select(pl.col(...).over("symbol"))
因子 DataFrame
```

## 回测引擎

`app/engine/backtest.py`：

1. **加载 universe**：从 Parquet 读所有 symbol，pivot 成 `(date, symbol) → ohlcv`
2. **计算信号**：DSL 因子 → 每日每股票一个数 → 全 universe 一张 wide table
3. **rebalance 切片**：按 `daily/weekly/monthly` 在 trading_calendar 上取调仓日
4. **选股**：每个调仓日按 signal 降序取 top N 做多；如设了 `bottom M` 则取信号末尾 M 只做空
5. **组合收益**：当日 PnL = 多头等权收益 − 空头等权收益（仅多头时空头收益为 0）
6. **结算**：用 t+1 日 close 算收益（防前视）
7. **成本**：每次 rebalance 算 `turnover_one_way = 1 − |old ∩ new| / max(|old|,|new|)`，扣 `turnover × cost × 2`（双边）
8. **指标**：cum_return、annual_return、sharpe、max_drawdown、win_rate
9. **基准**：同 universe 等权全持（始终 long-only），得到对照曲线

输出：`nav_curve` / `benchmark_curve` / `metrics` / `benchmark_metrics` / `excess_return` / `total_cost`（累计扣除的成本比例）。

### Long-short 与成本组合示例

```
factor mom = delay(close,1) / delay(close,20) - 1
strategy {
  universe:  cn:hs50
  signal:    mom
  select:    top 5 bottom 5    # 多 top 5 + 空 bottom 5
  rebalance: monthly
  cost:      0.001              # 单边 10 bps
  start:     2022-01-01
  end:       2024-12-31
}
```

实测：累计 17.13% vs 基准 12.12%（超额 5pp），累计扣成本 6.0%。

## 测试

`tests/` 下 80+ 用例：
- `test_dsl_parser.py`：30 个 parser case，含错误恢复
- `test_dsl_executor.py`：32 个 executor case
- `test_dsl_executor_extended.py`：10 个边界算子
- `test_engine.py`：13 个 engine 端到端
- `test_storage_smoke.py`：5 个 storage 冒烟

```bash
pytest -q
```
