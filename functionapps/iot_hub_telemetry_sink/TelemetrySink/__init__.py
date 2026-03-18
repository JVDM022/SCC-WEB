from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import azure.functions as func
import psycopg2
from psycopg2.extras import Json


SCHEMA_SQL = """
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


def _parse_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _parse_bool(value: Any) -> bool | None:
    if value is None or value == "":
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


def _parse_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _event_device_id(event: func.EventHubEvent) -> str:
    metadata = getattr(event, "metadata", None)
    if isinstance(metadata, dict):
        normalized = {str(key).lower(): value for key, value in metadata.items()}
        for key in (
            "iothub-connection-device-id",
            "iothub_connection_device_id",
            "connection-device-id",
            "device-id",
            "deviceid",
        ):
            value = normalized.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _normalize_payload(payload: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    temperature = _parse_float(payload.get("temp") or payload.get("temperature") or payload.get("temperature_c"))
    heater_on = _parse_bool(payload.get("heat") or payload.get("heater_on") or payload.get("heater"))
    motor_on = _parse_bool(payload.get("motor") or payload.get("motor_on"))
    kill_state = _parse_bool(payload.get("kill") or payload.get("kill_state") or payload.get("killed"))
    system_on = _parse_bool(payload.get("system_on") or payload.get("systemOn") or payload.get("on"))
    uptime_seconds = _parse_int(payload.get("uptime_s") or payload.get("uptime_seconds") or payload.get("uptime"))
    source_timestamp = payload.get("ts") or payload.get("timestamp") or payload.get("source_timestamp")

    if system_on is None:
        if kill_state is True:
            system_on = False
        elif kill_state is False:
            system_on = True
        elif heater_on is not None or temperature is not None:
            system_on = True

    return {
        "temperature": temperature,
        "heater_on": heater_on,
        "motor_on": motor_on,
        "kill_state": kill_state,
        "system_on": system_on,
        "uptime_seconds": uptime_seconds,
        "source_timestamp": "" if source_timestamp in (None, "") else str(source_timestamp),
        "device_id": device_id,
        "raw_payload": payload,
    }


def _connect_db():
    database_url = os.environ["DATABASE_URL"]
    connect_timeout = int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "15") or "15")
    return psycopg2.connect(dsn=database_url, connect_timeout=connect_timeout)


def _upsert_latest_telemetry(telemetry: Dict[str, Any]) -> None:
    with _connect_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
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
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                (
                    1,
                    telemetry.get("temperature"),
                    _bool_to_int(telemetry.get("heater_on")),
                    _bool_to_int(telemetry.get("motor_on")),
                    _bool_to_int(telemetry.get("kill_state")),
                    _bool_to_int(telemetry.get("system_on")),
                    telemetry.get("uptime_seconds"),
                    telemetry.get("source_timestamp"),
                    telemetry.get("device_id"),
                    Json(telemetry.get("raw_payload") or {}),
                ),
            )


def main(event: func.EventHubEvent) -> None:
    expected_device_id = str(os.environ.get("TELEMETRY_DEVICE_ID", "") or "").strip().lower()
    device_id = _event_device_id(event) or expected_device_id
    if expected_device_id and device_id and device_id.lower() != expected_device_id:
        logging.info("Skipping telemetry for device %s", device_id)
        return

    body_text = event.get_body().decode("utf-8", errors="replace").strip()
    if not body_text:
        logging.warning("Received empty telemetry event body")
        return

    try:
        payload = json.loads(body_text)
    except ValueError:
        logging.warning("Telemetry event body is not valid JSON: %s", body_text)
        return

    if not isinstance(payload, dict):
        logging.warning("Telemetry payload is not a JSON object: %r", payload)
        return

    telemetry = _normalize_payload(payload, device_id=device_id)
    if telemetry.get("temperature") is None:
        logging.warning("Telemetry payload missing temperature: %s", body_text)
        return

    _upsert_latest_telemetry(telemetry)
    logging.info(
        "Stored telemetry for %s: temp=%s uptime=%s",
        telemetry.get("device_id") or "unknown-device",
        telemetry.get("temperature"),
        telemetry.get("uptime_seconds"),
    )
