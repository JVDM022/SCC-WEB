from __future__ import annotations

import csv
import io
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import TELEMETRY_LOG_HEADERS, TELEMETRY_LOG_PATH
from db import get_db_pool
from psycopg2.extras import Json, RealDictCursor
from services.pacific_time import format_pacific_timestamp


_FLOAT_TOKEN_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)")
_TELEMETRY_HISTORY_LOCK = threading.Lock()
_TELEMETRY_HISTORY_READY = False

_TELEMETRY_HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS heater_telemetry_history (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    temperature_c DOUBLE PRECISION,
    heat INTEGER,
    motor INTEGER,
    kill_state INTEGER,
    system_on INTEGER,
    uptime_seconds INTEGER,
    source_timestamp TEXT,
    device_id TEXT,
    raw_payload JSONB
)
"""


def _parse_float_text(text: str) -> float | None:
    normalized = text.strip().replace("−", "-")
    if not normalized:
        return None

    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif normalized.count(",") == 1 and "." not in normalized:
        normalized = normalized.replace(",", ".")

    try:
        return float(normalized)
    except ValueError:
        return None


def coerce_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    direct = _parse_float_text(text)
    if direct is not None:
        return direct

    match = _FLOAT_TOKEN_RE.search(text)
    if not match:
        return None
    return _parse_float_text(match.group(0))


def coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "online", "enabled", "active"}:
        return True
    if text in {"0", "false", "no", "off", "offline", "disabled", "inactive"}:
        return False
    return None


def first_payload_value(payload: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def bool_to_log_value(value: Any) -> str:
    normalized = coerce_bool(value)
    if normalized is True:
        return "1"
    if normalized is False:
        return "0"
    return ""


def _with_db(work):
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


def _parse_logged_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_history_row(telemetry: Dict[str, Any], *, recorded_at: Any = None) -> Dict[str, Any]:
    temperature = coerce_float(telemetry.get("temperature"))
    uptime_value = telemetry.get("uptime_seconds")
    uptime_seconds = None
    if uptime_value not in (None, ""):
        try:
            uptime_seconds = int(float(uptime_value))
        except (TypeError, ValueError):
            uptime_seconds = None

    return {
        "recorded_at": _parse_logged_timestamp(recorded_at or telemetry.get("timestamp")),
        "temperature_c": temperature,
        "heat": None if telemetry.get("heater_on") is None else (1 if coerce_bool(telemetry.get("heater_on")) else 0),
        "motor": None if telemetry.get("motor_on") is None else (1 if coerce_bool(telemetry.get("motor_on")) else 0),
        "kill_state": None if telemetry.get("kill_state") is None else (1 if coerce_bool(telemetry.get("kill_state")) else 0),
        "system_on": None if telemetry.get("system_on") is None else (1 if coerce_bool(telemetry.get("system_on")) else 0),
        "uptime_seconds": uptime_seconds,
        "source_timestamp": str(telemetry.get("source_timestamp") or ""),
        "device_id": str(telemetry.get("device_id") or ""),
        "raw_payload": Json(telemetry),
    }


def _csv_row_from_history(row: Dict[str, Any]) -> Dict[str, str]:
    return {
        "timestamp": format_pacific_timestamp(row.get("recorded_at")),
        "temperature_c": "" if row.get("temperature_c") is None else f"{float(row['temperature_c']):.4f}",
        "heat": bool_to_log_value(row.get("heat")),
        "motor": bool_to_log_value(row.get("motor")),
        "kill_state": bool_to_log_value(row.get("kill_state")),
    }


def _load_legacy_telemetry_rows() -> List[Dict[str, Any]]:
    if not TELEMETRY_LOG_PATH.exists():
        return []

    try:
        with TELEMETRY_LOG_PATH.open("r", newline="", encoding="utf-8") as log_file:
            reader = csv.DictReader(log_file)
            return [dict(row) for row in reader]
    except OSError:
        return []


def ensure_telemetry_log_history() -> None:
    global _TELEMETRY_HISTORY_READY

    if _TELEMETRY_HISTORY_READY:
        return

    with _TELEMETRY_HISTORY_LOCK:
        if _TELEMETRY_HISTORY_READY:
            return

        legacy_rows = _load_legacy_telemetry_rows()

        def _prepare(conn) -> None:
            with conn.cursor() as cursor:
                cursor.execute(_TELEMETRY_HISTORY_SCHEMA_SQL)
                if not legacy_rows:
                    return

                for row in legacy_rows:
                    telemetry = {
                        "temperature": row.get("temperature_c"),
                        "heater_on": coerce_bool(row.get("heat")),
                        "motor_on": coerce_bool(row.get("motor")),
                        "kill_state": coerce_bool(row.get("kill_state")),
                        "source_timestamp": row.get("timestamp"),
                    }
                    normalized = _normalize_history_row(telemetry, recorded_at=row.get("timestamp"))
                    cursor.execute(
                        """
                        INSERT INTO heater_telemetry_history (
                            recorded_at,
                            temperature_c,
                            heat,
                            motor,
                            kill_state,
                            system_on,
                            uptime_seconds,
                            source_timestamp,
                            device_id,
                            raw_payload
                        )
                        SELECT
                            %(recorded_at)s,
                            %(temperature_c)s,
                            %(heat)s,
                            %(motor)s,
                            %(kill_state)s,
                            %(system_on)s,
                            %(uptime_seconds)s,
                            %(source_timestamp)s,
                            %(device_id)s,
                            %(raw_payload)s
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM heater_telemetry_history
                            WHERE recorded_at = %(recorded_at)s
                              AND temperature_c IS NOT DISTINCT FROM %(temperature_c)s
                              AND heat IS NOT DISTINCT FROM %(heat)s
                              AND motor IS NOT DISTINCT FROM %(motor)s
                              AND kill_state IS NOT DISTINCT FROM %(kill_state)s
                              AND source_timestamp IS NOT DISTINCT FROM %(source_timestamp)s
                        )
                        """,
                        normalized,
                    )

        _with_db(_prepare)
        _TELEMETRY_HISTORY_READY = True


def ensure_telemetry_log_file() -> None:
    ensure_telemetry_log_history()


def append_telemetry_log_sample(telemetry: Dict[str, Any]) -> None:
    temperature = telemetry.get("temperature")
    if temperature is None:
        return

    ensure_telemetry_log_history()
    normalized = _normalize_history_row(
        {
            **telemetry,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )

    def _insert(conn) -> None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO heater_telemetry_history (
                    recorded_at,
                    temperature_c,
                    heat,
                    motor,
                    kill_state,
                    system_on,
                    uptime_seconds,
                    source_timestamp,
                    device_id,
                    raw_payload
                ) VALUES (
                    %(recorded_at)s,
                    %(temperature_c)s,
                    %(heat)s,
                    %(motor)s,
                    %(kill_state)s,
                    %(system_on)s,
                    %(uptime_seconds)s,
                    %(source_timestamp)s,
                    %(device_id)s,
                    %(raw_payload)s
                )
                """,
                normalized,
            )

    _with_db(_insert)


def telemetry_log_sample_count() -> int:
    ensure_telemetry_log_history()

    def _count(conn) -> int:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM heater_telemetry_history")
            return int(cursor.fetchone()[0] or 0)

    return _with_db(_count)


def read_telemetry_log_csv() -> tuple[str, int]:
    ensure_telemetry_log_history()

    def _load(conn) -> List[Dict[str, Any]]:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT recorded_at, temperature_c, heat, motor, kill_state
                FROM heater_telemetry_history
                ORDER BY recorded_at ASC, id ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    rows = _with_db(_load)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=TELEMETRY_LOG_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow(_csv_row_from_history(row))
    return output.getvalue(), len(rows)
