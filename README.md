# Quant Signal Platform

End-to-end long-short equity strategy platform built on 30 S&P 500 stocks.

## Architecture
- **Layer 1** — Daily OHLCV ingestion via yfinance + SEC EDGAR 10-K/10-Q filings (PostgreSQL, Apache Airflow)
- **Layer 2** — Signal engine: momentum (20d/60d), mean reversion (z-score, RSI), volatility regime classification
- **Layer 3** — Vectorized backtester with transaction costs, Sharpe ratio, max drawdown, hit rate
- **Layer 4** — Live Streamlit dashboard with signal rankings, backtest curve, and per-symbol deep dive

## Results
| Strategy | Sharpe | Ann. Return | Max Drawdown |
|---|---|---|---|
| Monthly rebalance, Top5/Bottom5 | **0.82** | 19.42% | -31.49% |
| Weekly rebalance, Top5/Bottom5 | 0.03 | 0.81% | -28.23% |
| Weekly rebalance, Top8/Bottom8 | -0.06 | -1.26% | -21.53% |

Signal decay analysis: monthly rebalance outperforms weekly by 26x Sharpe,
confirming the composite signal has low-frequency persistence (~20-60 day horizon).

## Stack
Python · PostgreSQL · Apache Airflow · NumPy · Pandas · FastAPI · Streamlit · Plotly · Docker

## Run locally
```bash
docker compose up -d
pip install -r requirements.txt
PYTHONPATH=. python ingestion/fetch_market_data.py
PYTHONPATH=. python signals/technical.py
PYTHONPATH=. streamlit run api/dashboard.py
```
