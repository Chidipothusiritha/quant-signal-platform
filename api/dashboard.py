"""
api/dashboard.py
Layer 4 — Streamlit Dashboard
Run with: streamlit run api/dashboard.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv
import psycopg2

load_dotenv()

st.set_page_config(
    page_title="Quant Signal Platform",
    page_icon="📈",
    layout="wide"
)

# ── DB connection ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_signals():
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "quant_platform"),
        user=os.getenv("POSTGRES_USER", "quant"),
        password=os.getenv("POSTGRES_PASSWORD", "quantpass"),
    )
    df = pd.read_sql("""
        SELECT s.symbol, s.date,
               s.composite_score, s.mom_20d, s.mom_60d,
               s.zscore_20d, s.rsi_14, s.vol_20d, s.vol_regime,
               o.adj_close
        FROM signal_features s
        JOIN ohlcv_daily o ON s.symbol = o.symbol AND s.date = o.date
        ORDER BY s.date DESC
    """, conn)
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_backtest():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from backtest.engine import run_backtest
    return run_backtest(top_n=5, bottom_n=5, rebalance_freq="ME")


# ── Layout ────────────────────────────────────────────────────────────────────

st.title("📈 Quant Signal Platform")
st.caption("Long-short equity strategy | S&P 500 universe | Momentum + Mean Reversion")

df = load_signals()
latest_date = df["date"].max()
latest = df[df["date"] == latest_date].sort_values("composite_score", ascending=False)

# ── Row 1: KPI cards ──────────────────────────────────────────────────────────

st.subheader(f"Signal Snapshot — {latest_date.strftime('%b %d, %Y')}")
cols = st.columns(5)
metrics = [
    ("Universe",      f"{df['symbol'].nunique()} stocks",  None),
    ("Top Signal",    latest.iloc[0]["symbol"],             f"score {latest.iloc[0]['composite_score']:.2f}"),
    ("Avg RSI",       f"{latest['rsi_14'].mean():.1f}",    "neutral = 50"),
    ("High Vol Names",f"{(latest['vol_regime']=='high').sum()}", "of 30 symbols"),
    ("Data Points",   f"{len(df):,}",                      "signal rows"),
]
for col, (label, value, delta) in zip(cols, metrics):
    col.metric(label, value, delta)

st.divider()

# ── Row 2: Signal heatmap + backtest curve ────────────────────────────────────

col1, col2 = st.columns([1, 1.6])

with col1:
    st.subheader("Composite Signal Rankings")
    display = latest[["symbol", "composite_score", "mom_20d", "rsi_14", "vol_regime"]].copy()
    display["mom_20d"] = (display["mom_20d"] * 100).round(2)
    display.columns = ["Symbol", "Score", "Mom 20d %", "RSI", "Vol Regime"]
    display = display.reset_index(drop=True)

    def color_score(val):
        if isinstance(val, float):
            if val >= 0.6:  return "background-color: #d4edda; color: #155724"
            if val <= 0.4:  return "background-color: #f8d7da; color: #721c24"
        return ""

    st.dataframe(
        display.style.applymap(color_score, subset=["Score"]),
        use_container_width=True,
        height=500
    )

with col2:
    st.subheader("Strategy Backtest — Cumulative Returns")
    with st.spinner("Running backtest..."):
        bt = load_backtest()

    cum = bt["cum_returns"].reset_index()
    cum.columns = ["date", "cumulative_return"]
    cum["cumulative_return"] = (cum["cumulative_return"] - 1) * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=cum["date"], y=cum["cumulative_return"],
        mode="lines", name="Strategy",
        line=dict(color="#2196F3", width=2),
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.08)"
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig.update_layout(
        yaxis_title="Return (%)",
        xaxis_title="",
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=1.02),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    bcols = st.columns(4)
    bcols[0].metric("Sharpe Ratio",  bt["sharpe_ratio"])
    bcols[1].metric("Ann. Return",   f"{bt['ann_return_pct']}%")
    bcols[2].metric("Max Drawdown",  f"{bt['max_drawdown_pct']}%")
    bcols[3].metric("Hit Rate",      f"{bt['hit_rate_pct']}%")

st.divider()

# ── Row 3: Price + signal chart per symbol ────────────────────────────────────

st.subheader("Symbol Deep Dive")
symbol = st.selectbox("Select symbol", sorted(df["symbol"].unique()), index=0)
sym_df = df[df["symbol"] == symbol].sort_values("date")

fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=sym_df["date"], y=sym_df["adj_close"],
    name="Price", line=dict(color="#333", width=1.5), yaxis="y1"
))
fig2.add_trace(go.Scatter(
    x=sym_df["date"], y=sym_df["composite_score"],
    name="Composite Signal", line=dict(color="#FF5722", width=1.5, dash="dot"),
    yaxis="y2"
))
fig2.update_layout(
    height=350,
    yaxis=dict(title="Price ($)"),
    yaxis2=dict(title="Signal Score", overlaying="y", side="right",
                range=[0, 1], showgrid=False),
    hovermode="x unified",
    margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(orientation="h", y=1.02),
)
st.plotly_chart(fig2, use_container_width=True)

# RSI chart
fig3 = go.Figure()
fig3.add_trace(go.Scatter(
    x=sym_df["date"], y=sym_df["rsi_14"],
    name="RSI 14", line=dict(color="#9C27B0", width=1.5)
))
fig3.add_hline(y=70, line_dash="dash", line_color="red",   annotation_text="Overbought")
fig3.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold")
fig3.update_layout(
    height=200, yaxis_title="RSI",
    margin=dict(l=0, r=0, t=10, b=0),
    yaxis=dict(range=[0, 100])
)
st.plotly_chart(fig3, use_container_width=True)