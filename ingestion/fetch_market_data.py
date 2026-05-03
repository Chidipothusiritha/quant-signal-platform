"""
ingestion/fetch_market_data.py

Pulls OHLCV daily data from yfinance for all active symbols
and upserts into ohlcv_daily. Designed to be called by Airflow
or run standalone for backfill.
"""

import logging
import time
from datetime import date, timedelta

import yfinance as yf
import pandas as pd

from db.db_client import get_conn, execute_many, execute_one, log_run

logger = logging.getLogger(__name__)

UPSERT_SQL = """
    INSERT INTO ohlcv_daily
        (symbol, date, open, high, low, close, adj_close, volume)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol, date) DO UPDATE SET
        open      = EXCLUDED.open,
        high      = EXCLUDED.high,
        low       = EXCLUDED.low,
        close     = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close,
        volume    = EXCLUDED.volume
"""


def get_active_symbols() -> list[str]:
    """Return all active symbols from the symbols table."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM symbols WHERE active = TRUE ORDER BY symbol")
            return [row[0] for row in cur.fetchall()]


def get_last_date(symbol: str) -> date:
    """Return the most recent date we have data for, or 2 years ago if none."""
    result = execute_one(
        "SELECT MAX(date) FROM ohlcv_daily WHERE symbol = %s", (symbol,)
    )
    if result and result[0]:
        return result[0] + timedelta(days=1)
    return date.today() - timedelta(days=730)  # 2-year backfill


def fetch_symbol(symbol: str, start: date, end: date) -> int:
    """
    Download OHLCV data for one symbol between start and end dates.
    Returns number of rows inserted.
    """
    logger.info(f"Fetching {symbol} from {start} to {end}")
    try:
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            progress=False,
        )

        if df.empty:
            logger.warning(f"No data returned for {symbol}")
            return 0

        # yfinance returns MultiIndex columns when downloading one ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        rows = [
            (
                symbol,
                row["date"].date() if hasattr(row["date"], "date") else row["date"],
                float(row["open"])   if pd.notna(row["open"])   else None,
                float(row["high"])   if pd.notna(row["high"])   else None,
                float(row["low"])    if pd.notna(row["low"])    else None,
                float(row["close"])  if pd.notna(row["close"])  else None,
                float(row["adj_close"]) if pd.notna(row["adj_close"]) else None,
                int(row["volume"])   if pd.notna(row["volume"]) else None,
            )
            for _, row in df.iterrows()
        ]

        inserted = execute_many(UPSERT_SQL, rows)
        logger.info(f"{symbol}: upserted {len(rows)} rows")
        return len(rows)

    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        raise


def run_market_data_ingestion(
    symbols: list[str] | None = None,
    end_date: date | None = None,
    rate_limit_sleep: float = 0.5,
) -> dict:
    """
    Main entry point called by the Airflow DAG.

    Args:
        symbols:           List of tickers to process. Defaults to all active.
        end_date:          End date for data pull. Defaults to today.
        rate_limit_sleep:  Seconds to sleep between tickers (avoids yfinance rate limits).

    Returns:
        Summary dict with total rows inserted and any failures.
    """
    if symbols is None:
        symbols = get_active_symbols()
    if end_date is None:
        end_date = date.today()

    summary = {"total_rows": 0, "success": [], "failed": []}

    for symbol in symbols:
        start_date = get_last_date(symbol)

        if start_date >= end_date:
            logger.info(f"{symbol}: already up to date, skipping")
            log_run("market_data_dag", "fetch_ohlcv", symbol, "skipped")
            continue

        try:
            rows = fetch_symbol(symbol, start_date, end_date)
            summary["total_rows"] += rows
            summary["success"].append(symbol)
            log_run("market_data_dag", "fetch_ohlcv", symbol, "success", rows)
        except Exception as e:
            summary["failed"].append(symbol)
            log_run("market_data_dag", "fetch_ohlcv", symbol, "failed",
                    error_msg=str(e))

        time.sleep(rate_limit_sleep)

    logger.info(
        f"Ingestion complete — {len(summary['success'])} succeeded, "
        f"{len(summary['failed'])} failed, {summary['total_rows']} total rows"
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_market_data_ingestion()
    print(result)