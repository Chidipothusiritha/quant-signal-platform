"""
signals/technical.py

Layer 2 — Technical Signal Engine
Computes momentum, mean reversion, and volatility regime signals
from ohlcv_daily and writes results to a signal_features table.
"""

import logging
import numpy as np
import pandas as pd
from db.db_client import get_conn, execute_many, log_run

logger = logging.getLogger(__name__)

CREATE_SIGNAL_TABLE = """
CREATE TABLE IF NOT EXISTS signal_features (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    date            DATE NOT NULL,
    mom_20d         NUMERIC(10,6),
    mom_60d         NUMERIC(10,6),
    mom_20d_rank    NUMERIC(6,4),
    mom_60d_rank    NUMERIC(6,4),
    zscore_20d      NUMERIC(10,6),
    zscore_60d      NUMERIC(10,6),
    rsi_14          NUMERIC(8,4),
    vol_20d         NUMERIC(10,6),
    vol_60d         NUMERIC(10,6),
    vol_regime      VARCHAR(10),
    composite_score NUMERIC(8,4),
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_date ON signal_features(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signal_features(date DESC);
"""

UPSERT_SIGNALS = """
INSERT INTO signal_features (
    symbol, date,
    mom_20d, mom_60d, mom_20d_rank, mom_60d_rank,
    zscore_20d, zscore_60d, rsi_14,
    vol_20d, vol_60d, vol_regime,
    composite_score
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (symbol, date) DO UPDATE SET
    mom_20d         = EXCLUDED.mom_20d,
    mom_60d         = EXCLUDED.mom_60d,
    mom_20d_rank    = EXCLUDED.mom_20d_rank,
    mom_60d_rank    = EXCLUDED.mom_60d_rank,
    zscore_20d      = EXCLUDED.zscore_20d,
    zscore_60d      = EXCLUDED.zscore_60d,
    rsi_14          = EXCLUDED.rsi_14,
    vol_20d         = EXCLUDED.vol_20d,
    vol_60d         = EXCLUDED.vol_60d,
    vol_regime      = EXCLUDED.vol_regime,
    composite_score = EXCLUDED.composite_score,
    computed_at     = NOW()
"""


def load_prices(symbols=None):
    sym_filter = ""
    params = []
    if symbols:
        placeholders = ",".join(["%s"] * len(symbols))
        sym_filter = f"WHERE symbol IN ({placeholders})"
        params = symbols
    query = f"""
        SELECT symbol, date, adj_close
        FROM ohlcv_daily
        {sym_filter}
        ORDER BY date ASC
    """
    with get_conn() as conn:
        df = pd.read_sql(query, conn, params=params or None, parse_dates=["date"])
    prices = df.pivot(index="date", columns="symbol", values="adj_close")
    prices = prices.sort_index()
    logger.info(f"Loaded prices: {prices.shape[0]} dates x {prices.shape[1]} symbols")
    return prices


def compute_momentum(prices):
    mom_20d = prices.pct_change(20)
    mom_60d = prices.pct_change(60)
    mom_20d_rank = mom_20d.rank(axis=1, pct=True)
    mom_60d_rank = mom_60d.rank(axis=1, pct=True)
    return {
        "mom_20d":      mom_20d,
        "mom_60d":      mom_60d,
        "mom_20d_rank": mom_20d_rank,
        "mom_60d_rank": mom_60d_rank,
    }


def compute_mean_reversion(prices):
    ma_20  = prices.rolling(20).mean()
    std_20 = prices.rolling(20).std()
    zscore_20d = (prices - ma_20) / std_20

    ma_60  = prices.rolling(60).mean()
    std_60 = prices.rolling(60).std()
    zscore_60d = (prices - ma_60) / std_60

    delta  = prices.diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta.clip(upper=0)).rolling(14).mean()
    rs     = gain / loss.replace(0, np.nan)
    rsi_14 = 100 - (100 / (1 + rs))

    return {
        "zscore_20d": zscore_20d,
        "zscore_60d": zscore_60d,
        "rsi_14":     rsi_14,
    }


def compute_volatility(prices):
    log_returns = np.log(prices / prices.shift(1))
    vol_20d = log_returns.rolling(20).std() * np.sqrt(252)
    vol_60d = log_returns.rolling(60).std() * np.sqrt(252)

    def classify_regime(vol_series):
        p33 = vol_series.quantile(0.33)
        p66 = vol_series.quantile(0.66)
        return vol_series.apply(
            lambda v: "low" if v <= p33 else ("medium" if v <= p66 else "high")
            if pd.notna(v) else None
        )

    vol_regime = vol_20d.apply(classify_regime, axis=0)
    return {
        "vol_20d":    vol_20d,
        "vol_60d":    vol_60d,
        "vol_regime": vol_regime,
    }


def compute_composite(mom_20d_rank, mom_60d_rank, zscore_20d, rsi_14):
    mom_component = (mom_20d_rank + mom_60d_rank) / 2
    mr_rank       = (-zscore_20d).rank(axis=1, pct=True)
    rsi_rank      = (100 - rsi_14).rank(axis=1, pct=True)
    mr_component  = (mr_rank + rsi_rank) / 2
    composite     = 0.6 * mom_component + 0.4 * mr_component
    return composite


def save_signals(all_signals):
    symbols = all_signals["mom_20d"].columns.tolist()
    dates   = all_signals["mom_20d"].index.tolist()
    rows = []
    for date in dates:
        for symbol in symbols:
            def val(key, d=date, s=symbol):
                v = all_signals[key].loc[d, s]
                return float(v) if pd.notna(v) else None
            def sval(key, d=date, s=symbol):
                v = all_signals[key].loc[d, s]
                return str(v) if pd.notna(v) else None
            rows.append((
                symbol, date.date(),
                val("mom_20d"), val("mom_60d"),
                val("mom_20d_rank"), val("mom_60d_rank"),
                val("zscore_20d"), val("zscore_60d"), val("rsi_14"),
                val("vol_20d"), val("vol_60d"),
                sval("vol_regime"),
                val("composite_score"),
            ))
    execute_many(UPSERT_SIGNALS, rows)
    logger.info(f"Upserted {len(rows)} signal rows")
    return len(rows)


def run_signal_computation(symbols=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_SIGNAL_TABLE)

    prices = load_prices(symbols)

    if prices.empty or prices.shape[0] < 61:
        logger.warning("Not enough price history (need 61+ days)")
        return {"status": "skipped", "reason": "insufficient history"}

    momentum   = compute_momentum(prices)
    mean_rev   = compute_mean_reversion(prices)
    volatility = compute_volatility(prices)
    composite  = compute_composite(
        momentum["mom_20d_rank"],
        momentum["mom_60d_rank"],
        mean_rev["zscore_20d"],
        mean_rev["rsi_14"],
    )

    all_signals = {**momentum, **mean_rev, **volatility, "composite_score": composite}
    rows_written = save_signals(all_signals)
    log_run("signal_dag", "compute_signals", "ALL", "success", rows_written)

    latest_date = prices.index[-1]
    latest = {
        col: float(composite.loc[latest_date, col])
        for col in composite.columns
        if pd.notna(composite.loc[latest_date, col])
    }
    top5    = sorted(latest.items(), key=lambda x: x[1], reverse=True)[:5]
    bottom5 = sorted(latest.items(), key=lambda x: x[1])[:5]

    return {
        "status":        "success",
        "rows_written":  rows_written,
        "as_of":         str(latest_date.date()),
        "top5_signals":  top5,
        "bottom5_signals": bottom5,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_signal_computation()
    print("\n=== Signal Computation Complete ===")
    print(f"Rows written : {result.get('rows_written')}")
    print(f"As of        : {result.get('as_of')}")
    print("\nTop 5 composite signals (strongest buys):")
    for sym, score in result.get("top5_signals", []):
        print(f"  {sym:8s}  {score:.4f}")
    print("\nBottom 5 composite signals (weakest):")
    for sym, score in result.get("bottom5_signals", []):
        print(f"  {sym:8s}  {score:.4f}")