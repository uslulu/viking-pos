"""
Каждый поток получает своё собственное соединение с БД.
Это решает ошибку "Connection is busy" при параллельных запросах из QThread.
"""
import pyodbc
import threading
import time
from typing import Optional

_lock = threading.Lock()
_conn_params: dict = {}
_local = threading.local()  # у каждого потока своё соединение
_PING_AFTER = 60  # сек простоя, после которых соединение проверяется перед запросом


def connect(server: str, database: str) -> bool:
    global _conn_params
    with _lock:
        _conn_params = {"server": server, "database": database}
    # Проверяем соединение в главном потоке
    try:
        conn = _make_connection()
        conn.close()
        return True
    except Exception as e:
        print(f"Connection error: {e}")
        return False


def _make_connection() -> pyodbc.Connection:
    p = _conn_params
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={p['server']};"
        f"DATABASE={p['database']};"
        f"Trusted_Connection=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)


def _get_conn() -> pyodbc.Connection:
    """Возвращает соединение для текущего потока, создаёт если нет."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _make_connection()
        _local.conn = conn
    elif time.monotonic() - getattr(_local, "used", 0) > _PING_AFTER:
        # После простоя проверяем что соединение живо
        try:
            conn.execute("SELECT 1")
        except:
            try:
                conn.close()
            except:
                pass
            conn = _make_connection()
            _local.conn = conn
    _local.used = time.monotonic()
    return conn


def fetch_all(sql: str, params=None) -> list:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or [])
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        cursor.close()


def fetch_one(sql: str, params=None) -> Optional[dict]:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or [])
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        cursor.close()


def execute(sql: str, params=None) -> int:
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or [])
        conn.commit()
        return cursor.rowcount
    except:
        conn.rollback()
        raise
    finally:
        cursor.close()


def close():
    conn = getattr(_local, "conn", None)
    if conn:
        try:
            conn.close()
        except:
            pass
        _local.conn = None
