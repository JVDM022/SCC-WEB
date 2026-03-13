from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict

import requests
from flask import current_app, has_app_context

from config import AZURE_TIMEOUT_SECONDS
from services.telemetry import (
    append_telemetry_log_sample,
    coerce_bool,
    coerce_float,
    first_payload_value,
)


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    if "<" in value and ">" in value:
        raise RuntimeError(f"{name} is not configured")
    return value


def azure_json_request(method: str, url: str, payload: Dict[str, Any] | None = None) -> tuple[Any, int]:
    try:
        response = requests.request(method, url, json=payload, timeout=AZURE_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError("Azure relay is unavailable") from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = {"raw": response.text}

    if response.status_code >= 400:
        raise RuntimeError(f"Azure relay returned {response.status_code}: {body}")
    return body, response.status_code


def load_heater_telemetry() -> Dict[str, Any]:
    url = required_env("AZ_TELEMETRY_URL")
    body, _ = azure_json_request("GET", url)
    if not isinstance(body, dict):
        raise RuntimeError("Telemetry response is not a JSON object")

    temperature = coerce_float(first_payload_value(body, ["temperature", "temp", "temperature_c"]))
    heater_on = coerce_bool(first_payload_value(body, ["heater_on", "heaterOn", "heater", "on"]))
    kill_state = coerce_bool(first_payload_value(body, ["kill", "kill_state", "killed"]))
    source_timestamp = first_payload_value(body, ["ts", "timestamp", "fetched_at"])

    if temperature is None and source_timestamp in (0, "0", "", None):
        raise RuntimeError("No telemetry sample has been posted to the Azure relay yet")

    return {
        "temperature": temperature,
        "heater_on": heater_on,
        "kill_state": kill_state,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_timestamp": source_timestamp,
    }


def load_heater_telemetry_safe() -> Dict[str, Any]:
    try:
        telemetry = load_heater_telemetry()
    except Exception as exc:
        _logger().exception("Failed to load heater telemetry")
        return {
            "temperature": None,
            "heater_on": None,
            "kill_state": None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": str(exc),
        }
    try:
        append_telemetry_log_sample(telemetry)
    except Exception:
        _logger().exception("Failed to append telemetry log sample")
    telemetry["error"] = ""
    return telemetry


def send_heater_command(value: Any) -> Dict[str, Any]:
    url = required_env("AZ_COMMAND_URL")
    body, status = azure_json_request("POST", url, payload={"type": "KILL", "value": value})
    return {"status": status, "response": body}
