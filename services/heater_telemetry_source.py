from __future__ import annotations

from services.azure_relay import send_heater_command
from services.iot_hub_telemetry import iot_hub_telemetry_configured, load_iot_hub_telemetry_safe
from services.azure_relay import load_heater_telemetry_safe as load_azure_relay_telemetry_safe
from services.telemetry_store import load_latest_telemetry_safe


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
