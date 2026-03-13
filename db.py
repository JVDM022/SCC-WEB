from __future__ import annotations

from typing import Any, Dict, List

from flask import g
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config import AZURE_POOL_TIMEOUT, CARD_KEYS, DATABASE_URL


DB_POOL: pool.ThreadedConnectionPool | None = None


def get_db_pool() -> pool.ThreadedConnectionPool:
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL,
            connect_timeout=int(AZURE_POOL_TIMEOUT),
        )
    return DB_POOL


def ensure_column(db, table: str, column: str, col_type: str) -> None:
    with db.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")


def init_db(db) -> None:
    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS project (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            owner TEXT,
            phase TEXT,
            target_release TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bom (
            id BIGSERIAL PRIMARY KEY,
            item TEXT,
            part_number TEXT,
            qty INTEGER,
            unit_cost REAL,
            supplier TEXT,
            lead_time_days INTEGER,
            status TEXT,
            link TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS documentation (
            id BIGSERIAL PRIMARY KEY,
            title TEXT,
            doc_type TEXT,
            owner TEXT,
            location TEXT,
            status TEXT,
            last_updated TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_status (
            id BIGSERIAL PRIMARY KEY,
            is_online INTEGER,
            reason TEXT,
            estimated_downtime TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS development_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            percent INTEGER,
            phase TEXT,
            status_text TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS development_log (
            id BIGSERIAL PRIMARY KEY,
            log_date TEXT,
            summary TEXT,
            details TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS card_state (
            key TEXT PRIMARY KEY,
            position INTEGER,
            pinned INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id BIGSERIAL PRIMARY KEY,
            task TEXT,
            owner TEXT,
            due_date TEXT,
            priority TEXT,
            status TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS risks (
            id BIGSERIAL PRIMARY KEY,
            risk TEXT,
            impact TEXT,
            solution TEXT,
            owner TEXT,
            status TEXT
        )
        """,
    ]

    with db.cursor() as cursor:
        for statement in schema_statements:
            cursor.execute(statement)
        cursor.execute(
            "INSERT INTO project (id, name, owner, phase, target_release) VALUES (1, '', '', '', '') "
            "ON CONFLICT (id) DO NOTHING"
        )

    ensure_column(db, "development_progress", "percent", "INTEGER")
    ensure_column(db, "development_progress", "phase", "TEXT")
    ensure_column(db, "development_progress", "status_text", "TEXT")
    ensure_column(db, "system_status", "is_online", "INTEGER")
    ensure_column(db, "tasks", "due_date", "TEXT")
    ensure_column(db, "tasks", "priority", "TEXT")
    ensure_column(db, "bom", "link", "TEXT")
    ensure_column(db, "risks", "solution", "TEXT")

    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO development_progress (id, percent, phase, status_text) VALUES (1, NULL, '', '') "
            "ON CONFLICT (id) DO NOTHING"
        )
        for position, key in enumerate(CARD_KEYS):
            cursor.execute(
                "INSERT INTO card_state (key, position, pinned) VALUES (%s, %s, 0) "
                "ON CONFLICT (key) DO NOTHING",
                (key, position),
            )

    db.commit()


def _to_postgres_placeholders(query: str) -> str:
    return query.replace("?", "%s")


def get_db():
    if "db" not in g:
        g.db = get_db_pool().getconn()
    return g.db


def close_db(exc: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        try:
            db.rollback()
        except Exception:
            pass
        get_db_pool().putconn(db)


def fetch_one(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> Dict[str, Any] | None:
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None


def fetch_all_rows(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> List[Dict[str, Any]]:
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)
        return [dict(row) for row in cursor.fetchall()]


def execute_sql(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> None:
    with get_db().cursor() as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)
