from __future__ import annotations

from services.azure_relay import send_heater_command
from services.iot_hub_telemetry import iot_hub_telemetry_configured, load_iot_hub_telemetry_safe
from services.azure_relay import load_heater_telemetry_safe as load_azure_relay_telemetry_safe


def load_heater_telemetry_safe():
    if iot_hub_telemetry_configured():
        return load_iot_hub_telemetry_safe()
    return load_azure_relay_telemetry_safe()
