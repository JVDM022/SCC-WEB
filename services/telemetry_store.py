from __future__ import annotations

import threading
from typing import Any, Callable, Dict

from psycopg2.extras import Json, RealDictCursor

from config import TELEMETRY_STALE_SECONDS
from db import get_db_pool
from services.azure_relay import coerce_uptime_seconds
from services.pacific_time import format_pacific_timestamp, pacific_now, parse_timestamp
from services.telemetry import coerce_bool, coerce_float


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS heater_telemetry_latest (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    temperature_c DOUBLE PRECISION,
    heat INTEGER,
    motor INTEGER,
    kill_state INTEGER,
    system_on INTEGER,
    uptime_seconds INTEGER,
    source_timestamp TEXT,
    device_id TEXT,
    raw_payload JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _with_db(work: Callable[[Any], Any]) -> Any:
    conn = get_db_pool().getconn()
    try:
        result = work(conn)
        conn.commit()
        return result
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        get_db_pool().putconn(conn)


def ensure_telemetry_store_schema() -> None:
    global _SCHEMA_READY

    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        def _create(conn) -> None:
            with conn.cursor() as cursor:
                cursor.execute(_SCHEMA_SQL)

        _with_db(_create)
        _SCHEMA_READY = True


def _bool_to_int(value: Any) -> int | None:
    normalized = coerce_bool(value)
    if normalized is None:
        return None
    return 1 if normalized else 0


def _row_to_telemetry(row: Dict[str, Any]) -> Dict[str, Any]:
    updated_at = row.get("updated_at")
    now = pacific_now()
    fetched_at = format_pacific_timestamp(now)
    stored_at = format_pacific_timestamp(updated_at)
    updated_at_dt = parse_timestamp(updated_at)
    age_seconds = None
    if updated_at_dt is not None:
        age_seconds = max(0, int((now - updated_at_dt.astimezone(now.tzinfo)).total_seconds()))

    return {
        "temperature": coerce_float(row.get("temperature_c")),
        "heater_on": coerce_bool(row.get("heat")),
        "motor_on": coerce_bool(row.get("motor")),
        "kill_state": coerce_bool(row.get("kill_state")),
        "system_on": coerce_bool(row.get("system_on")),
        "uptime_seconds": coerce_uptime_seconds(row.get("uptime_seconds")),
        "source_timestamp": row.get("source_timestamp"),
        "device_id": row.get("device_id"),
        "stored_at": stored_at,
        "fetched_at": fetched_at,
        "age_seconds": age_seconds,
        "stale": age_seconds is None or age_seconds > TELEMETRY_STALE_SECONDS,
        "error": "",
    }


def upsert_latest_telemetry(telemetry: Dict[str, Any]) -> None:
    ensure_telemetry_store_schema()

    normalized = {
        "temperature_c": coerce_float(telemetry.get("temperature")),
        "heat": _bool_to_int(telemetry.get("heater_on")),
        "motor": _bool_to_int(telemetry.get("motor_on")),
        "kill_state": _bool_to_int(telemetry.get("kill_state")),
        "system_on": _bool_to_int(telemetry.get("system_on")),
        "uptime_seconds": coerce_uptime_seconds(telemetry.get("uptime_seconds")),
        "source_timestamp": str(telemetry.get("source_timestamp") or ""),
        "device_id": str(telemetry.get("device_id") or ""),
        "raw_payload": Json(telemetry),
    }

    def _upsert(conn) -> None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO heater_telemetry_latest (
                    id,
                    temperature_c,
                    heat,
                    motor,
                    kill_state,
                    system_on,
                    uptime_seconds,
                    source_timestamp,
                    device_id,
                    raw_payload,
                    updated_at
                ) VALUES (1, %(temperature_c)s, %(heat)s, %(motor)s, %(kill_state)s, %(system_on)s,
                          %(uptime_seconds)s, %(source_timestamp)s, %(device_id)s, %(raw_payload)s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    temperature_c = EXCLUDED.temperature_c,
                    heat = EXCLUDED.heat,
                    motor = EXCLUDED.motor,
                    kill_state = EXCLUDED.kill_state,
                    system_on = EXCLUDED.system_on,
                    uptime_seconds = EXCLUDED.uptime_seconds,
                    source_timestamp = EXCLUDED.source_timestamp,
                    device_id = EXCLUDED.device_id,
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = NOW()
                """,
                normalized,
            )

    _with_db(_upsert)


def load_latest_telemetry() -> Dict[str, Any]:
    ensure_telemetry_store_schema()

    def _load(conn) -> Dict[str, Any] | None:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM heater_telemetry_latest WHERE id = 1")
            row = cursor.fetchone()
            return dict(row) if row is not None else None

    row = _with_db(_load)
    if row is None:
        raise RuntimeError("No telemetry sample has been stored yet")
    return _row_to_telemetry(row)


def load_latest_telemetry_safe() -> Dict[str, Any]:
    try:
        return load_latest_telemetry()
    except Exception as exc:
        return {
            "temperature": None,
            "heater_on": None,
            "motor_on": None,
            "kill_state": None,
            "system_on": None,
            "uptime_seconds": None,
            "source_timestamp": None,
            "device_id": "",
            "stored_at": "",
            "fetched_at": format_pacific_timestamp(pacific_now()),
            "age_seconds": None,
            "stale": True,
            "error": str(exc),
        }


def telemetry_is_fresh(telemetry: Dict[str, Any], *, max_age_seconds: int = TELEMETRY_STALE_SECONDS) -> bool:
    age_seconds = telemetry.get("age_seconds")
    if age_seconds is None:
        return False
    try:
        return int(age_seconds) <= max_age_seconds
    except (TypeError, ValueError):
        return False
