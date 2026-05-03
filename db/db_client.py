import os
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Connection pool — reused across tasks in the same process
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            dbname=os.getenv("POSTGRES_DB", "quant_platform"),
            user=os.getenv("POSTGRES_USER", "quant"),
            password=os.getenv("POSTGRES_PASSWORD", "quantpass"),
        )
        logger.info("PostgreSQL connection pool initialized")
    return _pool


@contextmanager
def get_conn():
    """Context manager: borrow a connection, auto-return on exit."""
    conn_pool = _get_pool()
    conn = conn_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn_pool.putconn(conn)


def execute_many(sql: str, rows: list[tuple]) -> int:
    """Bulk insert with executemany. Returns number of rows inserted."""
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            return cur.rowcount


def execute_one(sql: str, params: tuple = None):
    """Execute a single statement and return fetchone result."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            try:
                return cur.fetchone()
            except psycopg2.ProgrammingError:
                return None


def log_run(dag_id: str, task_id: str, symbol: str,
            status: str, rows_inserted: int = 0, error_msg: str = None):
    """Write an entry to ingestion_log for audit tracking."""
    sql = """
        INSERT INTO ingestion_log
            (dag_id, task_id, symbol, status, rows_inserted, error_msg)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    execute_many(sql, [(dag_id, task_id, symbol, status, rows_inserted, error_msg)])