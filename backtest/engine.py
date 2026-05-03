"""
backtest/engine.py
Layer 3 — Vectorized Backtester
"""

import logging
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)


def get_engine():
    user     = os.getenv("POSTGRES_USER", "quant")
    password = os.getenv("POSTGRES_PASSWORD", "quantpass")
    host     = os.getenv("POSTGRES_HOST", "localhost")
    port     = os.getenv("POSTGRES_PORT", "5432")
    db       = os.getenv("POSTGRES_DB", "quant_platform")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}")


def load_data():
    user     = os.getenv("POSTGRES_USER", "quant")
    password = os.getenv("POSTGRES_PASSWORD", "quantpass")
    host     = os.getenv("POSTGRES_HOST", "localhost")
    port     = os.getenv("POSTGRES_PORT", "5432")
    db       = os.getenv("POSTGRES_DB", "quant_platform")
    engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}")
    query = """
        SELECT o.symbol, o.date, o.adj_close, s.composite_score
        FROM ohlcv_daily o
        JOIN signal_features s ON o.symbol = s.symbol AND o.date = s.date
        ORDER BY o.date ASC
    """
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    df["date"] = pd.to_datetime(df["date"])
    engine.dispose()
    return df


def run_backtest(top_n=5, bottom_n=5, transaction_cost=0.001, rebalance_freq="W"):
    df = load_data()
    prices  = df.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    signals = df.pivot(index="date", columns="symbol", values="composite_score").sort_index()
    fwd_returns = prices.pct_change().shift(-1)

    # Snap rebalance dates to actual trading dates using asof
    raw_rebal = signals.resample(rebalance_freq).last().dropna(how="all").index
    trading_dates = signals.index
    rebal_dates = set()
    for d in raw_rebal:
        idx = trading_dates.searchsorted(d, side="right") - 1
        if idx >= 0:
            rebal_dates.add(trading_dates[idx])

    all_returns = []
    prev_weights = pd.Series(0.0, index=prices.columns)
    current_weights = pd.Series(0.0, index=prices.columns)

    for date in prices.index[:-1]:
        if date in rebal_dates:
            scores = signals.loc[date].dropna()
            if len(scores) >= top_n + bottom_n:
                longs  = scores.nlargest(top_n).index
                shorts = scores.nsmallest(bottom_n).index
                new_weights = pd.Series(0.0, index=prices.columns)
                new_weights[longs]  =  1.0 / top_n
                new_weights[shorts] = -1.0 / bottom_n
                turnover = (new_weights - prev_weights).abs().sum() / 2
                cost = turnover * transaction_cost
                prev_weights = new_weights.copy()
                current_weights = new_weights.copy()
            else:
                cost = 0.0
        else:
            cost = 0.0

        day_ret = fwd_returns.loc[date].fillna(0)
        port_ret = float((current_weights * day_ret).sum()) - cost
        all_returns.append(port_ret)

    port = pd.Series(all_returns, index=prices.index[:-1]).dropna()
    ann_return   = port.mean() * 252
    ann_vol      = port.std() * np.sqrt(252)
    sharpe       = ann_return / ann_vol if ann_vol > 0 else 0
    cum          = (1 + port).cumprod()
    max_drawdown = ((cum - cum.cummax()) / cum.cummax()).min()
    hit_rate     = (port > 0).mean()
    total_return = cum.iloc[-1] - 1

    return {
        "sharpe_ratio":     round(float(sharpe), 4),
        "ann_return_pct":   round(float(ann_return) * 100, 2),
        "ann_vol_pct":      round(float(ann_vol) * 100, 2),
        "max_drawdown_pct": round(float(max_drawdown) * 100, 2),
        "hit_rate_pct":     round(float(hit_rate) * 100, 2),
        "total_return_pct": round(float(total_return) * 100, 2),
        "trading_days":     len(port),
        "cum_returns":      cum,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    print("\n=== Weekly Rebalance | Top5 Long / Bottom5 Short ===")
    r = run_backtest(top_n=5, bottom_n=5, rebalance_freq="W")
    print(f"\n{'Metric':<25} {'Value':>10}")
    print("-" * 37)
    print(f"{'Sharpe Ratio':<25} {r['sharpe_ratio']:>10.4f}")
    print(f"{'Ann. Return':<25} {r['ann_return_pct']:>9.2f}%")
    print(f"{'Ann. Volatility':<25} {r['ann_vol_pct']:>9.2f}%")
    print(f"{'Max Drawdown':<25} {r['max_drawdown_pct']:>9.2f}%")
    print(f"{'Hit Rate':<25} {r['hit_rate_pct']:>9.2f}%")
    print(f"{'Total Return':<25} {r['total_return_pct']:>9.2f}%")
    print(f"{'Trading Days':<25} {r['trading_days']:>10}")

    print("\n=== Monthly Rebalance | Top5 Long / Bottom5 Short ===")
    r2 = run_backtest(top_n=5, bottom_n=5, rebalance_freq="ME")
    print(f"Sharpe: {r2['sharpe_ratio']}  |  "
          f"Return: {r2['ann_return_pct']}%  |  "
          f"Max DD: {r2['max_drawdown_pct']}%")

    print("\n=== Weekly Rebalance | Top8 Long / Bottom8 Short ===")
    r3 = run_backtest(top_n=8, bottom_n=8, rebalance_freq="W")
    print(f"Sharpe: {r3['sharpe_ratio']}  |  "
          f"Return: {r3['ann_return_pct']}%  |  "
          f"Max DD: {r3['max_drawdown_pct']}%")