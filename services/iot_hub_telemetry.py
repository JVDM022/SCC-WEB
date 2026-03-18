from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
import tempfile
from typing import Any, Dict

from flask import current_app, has_app_context

from config import (
    IOTHUB_DEFAULT_DEVICE_ID,
    IOTHUB_EVENTHUB_CONNECTION_STRING,
    IOTHUB_EVENTHUB_CONSUMER_GROUP,
)
from services.pacific_time import format_pacific_timestamp, pacific_now
from services.azure_relay import coerce_uptime_seconds, parse_serial_telemetry_line
from services.telemetry import coerce_bool, coerce_float, first_payload_value

try:
    from azure.eventhub import EventHubConsumerClient, TransportType
except Exception as exc:  # pragma: no cover - import depends on deployment environment
    EventHubConsumerClient = None
    TransportType = None
    _EVENTHUB_IMPORT_ERROR = exc
else:
    _EVENTHUB_IMPORT_ERROR = None


_LATEST_TELEMETRY_LOCK = threading.Lock()
_LATEST_TELEMETRY: Dict[str, Any] | None = None
_LAST_CONSUMER_ERROR = ""
_LAST_EVENT_AT = ""
_CONSUMER_THREAD: threading.Thread | None = None
_TELEMETRY_CACHE_PATH = Path(tempfile.gettempdir()) / "scc_iothub_latest_telemetry.json"


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


def iot_hub_telemetry_configured() -> bool:
    return bool(IOTHUB_EVENTHUB_CONNECTION_STRING.strip())


def _eventhub_sdk_available() -> bool:
    return EventHubConsumerClient is not None


def _mapping_value(mapping: Dict[Any, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None

    for key in keys:
        for candidate in (key, key.encode("utf-8")):
            if candidate in mapping:
                value = mapping[candidate]
                if value is not None and value != "":
                    return value
    return None


def _extract_event_device_id(event: Any) -> str:
    system_properties = getattr(event, "system_properties", None)
    candidate = _mapping_value(
        system_properties,
        "iothub-connection-device-id",
        "connection-device-id",
        "device-id",
    )
    if candidate is None:
        properties = getattr(event, "properties", None)
        candidate = _mapping_value(
            properties,
            "deviceId",
            "device_id",
            "device-id",
        )
    return str(candidate or "").strip()


def _decode_event_body(event: Any) -> str:
    try:
        return str(event.body_as_str(encoding="UTF-8") or "").strip()
    except TypeError:
        try:
            return str(event.body_as_str("UTF-8") or "").strip()
        except Exception:
            pass
    except Exception:
        pass

    chunks: list[bytes] = []
    body_iterable = getattr(event, "body", None)
    if body_iterable is None:
        return ""

    try:
        for chunk in body_iterable:
            if isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(bytes(chunk))
    except TypeError:
        return ""

    return b"".join(chunks).decode("utf-8", errors="replace").strip()


def _normalize_iot_hub_payload(body: Any, *, fallback_source_timestamp: Any = None) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    source_timestamp: Any = fallback_source_timestamp

    if isinstance(body, dict):
        raw_value = first_payload_value(body, ["raw", "telemetry", "line", "message"])
        if isinstance(raw_value, str):
            parsed = parse_serial_telemetry_line(raw_value)

        temperature = coerce_float(first_payload_value(body, ["temperature", "temp", "temperature_c"]))
        if parsed.get("temperature") is None:
            parsed["temperature"] = temperature

        heater_on = coerce_bool(first_payload_value(body, ["heat", "heater_on", "heaterOn", "heater"]))
        motor_on = coerce_bool(first_payload_value(body, ["motor", "motor_on", "motorOn"]))
        kill_state = coerce_bool(first_payload_value(body, ["kill", "kill_state", "killed"]))
        system_on = coerce_bool(
            first_payload_value(body, ["system_on", "systemOn", "system", "relay_on", "on"])
        )
        uptime_seconds = coerce_uptime_seconds(
            first_payload_value(body, ["uptime_seconds", "uptime_s", "uptime"])
        )
        source_timestamp = first_payload_value(body, ["ts", "timestamp", "fetched_at"]) or source_timestamp

        if "temperature" not in parsed:
            parsed["temperature"] = temperature
        if parsed.get("heater_on") is None:
            parsed["heater_on"] = heater_on
        if parsed.get("motor_on") is None:
            parsed["motor_on"] = motor_on
        if parsed.get("kill_state") is None:
            parsed["kill_state"] = kill_state
        if parsed.get("system_on") is None:
            parsed["system_on"] = system_on
        if parsed.get("uptime_seconds") is None:
            parsed["uptime_seconds"] = uptime_seconds
    elif isinstance(body, str):
        parsed = parse_serial_telemetry_line(body)
        parsed.setdefault("heater_on", None)
        parsed.setdefault("motor_on", None)
        parsed.setdefault("kill_state", None)
        parsed.setdefault("system_on", None)
        parsed.setdefault("uptime_seconds", None)
    else:
        raise RuntimeError("IoT Hub telemetry event is not a supported format")

    if parsed.get("system_on") is None:
        if parsed.get("kill_state") is True:
            parsed["system_on"] = False
        elif parsed.get("kill_state") is False:
            parsed["system_on"] = True
        elif parsed.get("heater_on") is not None or parsed.get("temperature") is not None:
            parsed["system_on"] = True

    error = ""
    if parsed.get("temperature") is None and source_timestamp in (0, "0", "", None):
        error = "No IoT Hub telemetry sample has been received yet"
    elif parsed.get("temperature") is None:
        error = "IoT Hub telemetry did not include a temperature value"

    return {
        "temperature": parsed.get("temperature"),
        "heater_on": parsed.get("heater_on"),
        "motor_on": parsed.get("motor_on"),
        "kill_state": parsed.get("kill_state"),
        "system_on": parsed.get("system_on"),
        "uptime_seconds": parsed.get("uptime_seconds"),
        "fetched_at": format_pacific_timestamp(pacific_now()),
        "source_timestamp": source_timestamp,
        "error": error,
    }


def _decode_payload_from_body(body_text: str) -> Any:
    if not body_text:
        return ""

    try:
        return json.loads(body_text)
    except ValueError:
        return body_text


def _write_latest_telemetry_cache(telemetry: Dict[str, Any]) -> None:
    temp_path = _TELEMETRY_CACHE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(telemetry), encoding="utf-8")
    temp_path.replace(_TELEMETRY_CACHE_PATH)


def _read_latest_telemetry_cache() -> Dict[str, Any] | None:
    try:
        payload = json.loads(_TELEMETRY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _store_latest_telemetry(event: Any) -> None:
    global _LATEST_TELEMETRY, _LAST_CONSUMER_ERROR, _LAST_EVENT_AT

    body_text = _decode_event_body(event)
    if not body_text:
        return

    device_id = _extract_event_device_id(event)
    target_device_id = IOTHUB_DEFAULT_DEVICE_ID.strip().lower()
    if target_device_id and device_id and device_id.lower() != target_device_id:
        return

    payload = _decode_payload_from_body(body_text)
    enqueued_time = getattr(event, "enqueued_time", None)
    fallback_source_timestamp = enqueued_time.isoformat() if enqueued_time is not None else None
    telemetry = _normalize_iot_hub_payload(payload, fallback_source_timestamp=fallback_source_timestamp)
    telemetry["device_id"] = device_id or IOTHUB_DEFAULT_DEVICE_ID

    with _LATEST_TELEMETRY_LOCK:
        _LATEST_TELEMETRY = telemetry
        _LAST_EVENT_AT = format_pacific_timestamp(pacific_now())
        _LAST_CONSUMER_ERROR = ""

    try:
        _write_latest_telemetry_cache(telemetry)
    except Exception:
        _logger().exception("Failed to write IoT Hub telemetry cache")


def _on_event(partition_context: Any, event: Any) -> None:
    _store_latest_telemetry(event)


def _consume_forever() -> None:
    global _LAST_CONSUMER_ERROR

    while True:
        try:
            client = EventHubConsumerClient.from_connection_string(
                conn_str=IOTHUB_EVENTHUB_CONNECTION_STRING,
                consumer_group=IOTHUB_EVENTHUB_CONSUMER_GROUP,
                transport_type=TransportType.AmqpOverWebsocket,
            )
            with client:
                client.receive(
                    on_event=_on_event,
                    starting_position="@latest",
                )
        except Exception as exc:
            _LAST_CONSUMER_ERROR = str(exc)
            _logger().exception("IoT Hub Event Hub telemetry consumer stopped")
            time.sleep(5)


def ensure_iot_hub_telemetry_consumer() -> None:
    global _CONSUMER_THREAD, _LAST_CONSUMER_ERROR

    if not iot_hub_telemetry_configured():
        raise RuntimeError("IOTHUB_EVENTHUB_CONNECTION_STRING is not configured")
    if not _eventhub_sdk_available():
        raise RuntimeError(f"azure-eventhub is not installed: {_EVENTHUB_IMPORT_ERROR}")

    with _LATEST_TELEMETRY_LOCK:
        if _CONSUMER_THREAD is not None and _CONSUMER_THREAD.is_alive():
            return

        _LAST_CONSUMER_ERROR = ""
        _CONSUMER_THREAD = threading.Thread(
            target=_consume_forever,
            name="iothub-telemetry-consumer",
            daemon=True,
        )
        _CONSUMER_THREAD.start()


def iot_hub_telemetry_status_summary(*, start_listener: bool = False) -> Dict[str, Any]:
    last_error = ""

    if start_listener and iot_hub_telemetry_configured() and _eventhub_sdk_available():
        try:
            ensure_iot_hub_telemetry_consumer()
        except Exception as exc:
            last_error = str(exc)

    with _LATEST_TELEMETRY_LOCK:
        latest = dict(_LATEST_TELEMETRY or {})
        last_error = str(_LAST_CONSUMER_ERROR or last_error)
        thread_alive = _CONSUMER_THREAD is not None and _CONSUMER_THREAD.is_alive()
        last_event_at = _LAST_EVENT_AT

    return {
        "configured": iot_hub_telemetry_configured(),
        "sdk_available": _eventhub_sdk_available(),
        "consumer_group": IOTHUB_EVENTHUB_CONSUMER_GROUP,
        "listening": thread_alive,
        "last_event_at": last_event_at,
        "last_error": last_error,
        "latest_device_id": latest.get("device_id"),
    }


def load_iot_hub_telemetry() -> Dict[str, Any]:
    ensure_iot_hub_telemetry_consumer()

    with _LATEST_TELEMETRY_LOCK:
        latest = dict(_LATEST_TELEMETRY or {})
        last_error = _LAST_CONSUMER_ERROR

    if not latest:
        latest = dict(_read_latest_telemetry_cache() or {})

    if latest:
        latest["fetched_at"] = format_pacific_timestamp(pacific_now())
        latest["error"] = str(latest.get("error") or "")
        return latest

    if last_error:
        raise RuntimeError(f"IoT Hub telemetry consumer error: {last_error}")
    raise RuntimeError("No IoT Hub telemetry sample has been received yet")


def load_iot_hub_telemetry_safe() -> Dict[str, Any]:
    try:
        telemetry = load_iot_hub_telemetry()
    except Exception as exc:
        message = str(exc)
        if "No IoT Hub telemetry sample has been received yet" not in message:
            _logger().exception("Failed to load IoT Hub telemetry")
        return {
            "temperature": None,
            "heater_on": None,
            "motor_on": None,
            "kill_state": None,
            "system_on": None,
            "uptime_seconds": None,
            "fetched_at": format_pacific_timestamp(pacific_now()),
            "source_timestamp": None,
            "error": message,
        }

    telemetry["error"] = str(telemetry.get("error") or "")
    return telemetry
