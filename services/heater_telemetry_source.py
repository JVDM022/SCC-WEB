from __future__ import annotations

from services.azure_relay import send_heater_command as send_azure_relay_command
from services.iot_hub import iot_hub_status_summary, invoke_direct_method
from services.iot_hub_telemetry import iot_hub_telemetry_configured, load_iot_hub_telemetry_safe
from services.azure_relay import load_heater_telemetry_safe as load_azure_relay_telemetry_safe
from services.telemetry_store import load_latest_telemetry_safe


def send_heater_command(value):
    hub_status = iot_hub_status_summary()
    if hub_status.get("configured"):
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
        }

    return send_azure_relay_command(value)


def load_heater_telemetry_safe():
    stored = load_latest_telemetry_safe()
    if stored.get("temperature") is not None:
        return stored

    if iot_hub_telemetry_configured():
        live_iot_hub = load_iot_hub_telemetry_safe()
        if live_iot_hub.get("temperature") is not None:
            return live_iot_hub

    relay = load_azure_relay_telemetry_safe()
    if relay.get("temperature") is not None:
        return relay

    return stored
