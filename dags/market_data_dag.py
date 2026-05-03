"""
dags/market_data_dag.py

Runs daily at 6pm ET (after market close).
Pulls OHLCV data for all active symbols.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.fetch_market_data import run_market_data_ingestion

default_args = {
    "owner":            "quant-platform",
    "depends_on_past":  False,
    "retries":          2,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": False,
}

with DAG(
    dag_id="market_data_daily",
    description="Pull daily OHLCV data for all active symbols",
    schedule="0 23 * * 1-5",       # 6pm ET = 23:00 UTC, Mon–Fri
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["ingestion", "market-data"],
) as dag:

    ingest_task = PythonOperator(
        task_id="fetch_ohlcv_all_symbols",
        python_callable=run_market_data_ingestion,
        op_kwargs={"rate_limit_sleep": 0.3},
    )