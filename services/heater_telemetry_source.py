from __future__ import annotations

from config import TELEMETRY_STALE_SECONDS
from services.iot_hub import iot_hub_status_summary, invoke_direct_method
from services.iot_hub_telemetry import iot_hub_telemetry_configured, load_iot_hub_telemetry_safe
from services.azure_relay import load_heater_telemetry_safe as load_azure_relay_telemetry_safe
from services.telemetry_store import load_latest_telemetry_safe, telemetry_is_fresh


def _stale_telemetry_message(telemetry):
    last_sample = telemetry.get("stored_at") or telemetry.get("source_timestamp") or "an unknown time"
    age_seconds = telemetry.get("age_seconds")
    if age_seconds is None:
        return f"Telemetry is stale. Last sample was recorded at {last_sample}."
    return (
        f"Telemetry is stale. Last sample was {age_seconds}s ago at {last_sample}. "
        f"Expected updates within {TELEMETRY_STALE_SECONDS}s."
    )


def send_heater_command(value):
    hub_status = iot_hub_status_summary()
    if not hub_status.get("configured"):
        raise RuntimeError(
            "Heater shutdown control requires IoT Hub direct methods. "
            "Configure IOTHUB_CONNECTION_STRING and IOTHUB_DEFAULT_DEVICE_ID."
        )

    numeric_value = 1 if bool(value) else 0
    response = invoke_direct_method(
        "KILL",
        {"value": numeric_value},
        connect_timeout_in_seconds=5,
        response_timeout_in_seconds=15,
    )
    return {
        "status": response.get("status", 200),
        "response": response,
        "transport": "iot_hub_direct_method",
        "requested_action": "shutdown" if numeric_value == 1 else "resume",
    }


def load_heater_telemetry_safe():
    stored = load_latest_telemetry_safe()
    if stored.get("temperature") is not None and telemetry_is_fresh(stored):
        return stored

    if iot_hub_telemetry_configured():
        live_iot_hub = load_iot_hub_telemetry_safe()
        if live_iot_hub.get("temperature") is not None:
            return live_iot_hub

    relay = load_azure_relay_telemetry_safe()
    if relay.get("temperature") is not None:
        return relay

    if stored.get("temperature") is not None:
        stale = dict(stored)
        stale["stale"] = True
        stale["error"] = _stale_telemetry_message(stale)
        return stale

    return stored
