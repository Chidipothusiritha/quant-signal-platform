"""
dags/edgar_dag.py

Runs weekly on Sunday at 2am UTC.
Pulls new 10-K and 10-Q filings from SEC EDGAR.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingestion.fetch_edgar import run_edgar_ingestion

default_args = {
    "owner":            "quant-platform",
    "depends_on_past":  False,
    "retries":          1,
    "retry_delay":      timedelta(minutes=10),
    "email_on_failure": False,
}

with DAG(
    dag_id="edgar_filings_weekly",
    description="Pull 10-K and 10-Q filings from SEC EDGAR",
    schedule="0 2 * * 0",          # Sunday 2am UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["ingestion", "edgar", "nlp"],
) as dag:

    ingest_task = PythonOperator(
        task_id="fetch_edgar_filings",
        python_callable=run_edgar_ingestion,
        op_kwargs={"max_filings_per_symbol": 8, "rate_limit_sleep": 0.5},
    )