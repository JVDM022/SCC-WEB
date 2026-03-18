from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict
from urllib.parse import urlsplit

import requests
from flask import current_app, has_app_context

from config import AZURE_TIMEOUT_SECONDS, get_env
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


def _looks_like_placeholder(value: str) -> bool:
    markers = (
        "your-function-app",
        "your-function-key",
        "yourstorageaccount",
        "your-storage-account-key",
        "/absolute/path/",
    )
    return any(marker in value for marker in markers)


def required_env(name: str) -> str:
    value = get_env(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    if ("<" in value and ">" in value) or _looks_like_placeholder(value):
        raise RuntimeError(f"{name} is not configured")
    return value


def describe_relay_target(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"


def azure_json_request(method: str, url: str, payload: Dict[str, Any] | None = None) -> tuple[Any, int]:
    target = describe_relay_target(url)
    try:
        response = requests.request(method, url, json=payload, timeout=AZURE_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Azure relay is unavailable for {target}") from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = {"raw": response.text}

    if response.status_code >= 400:
        message = f"Azure relay returned {response.status_code} for {target}"
        if response.status_code == 404:
            message += ". Check the Azure Function route/key and restart the app if you recently changed .env."
        if body not in ({}, {"raw": ""}, ""):
            message += f": {body}"
        raise RuntimeError(message)
    return body, response.status_code


_TEMPERATURE_VALUE_RE = r"[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)"


def _extract_labeled_temperature(line: str) -> str | None:
    patterns = (
        rf"\btemp(?:erature)?\b\s*[:=]\s*({_TEMPERATURE_VALUE_RE})(?:\s*(?:°|deg(?:rees)?)\s*[cf])?",
        rf"\btemp(?:erature)?\b\s+({_TEMPERATURE_VALUE_RE})(?:\s*(?:°|deg(?:rees)?)\s*[cf])?",
    )
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def parse_serial_telemetry_line(line: str) -> Dict[str, Any]:
    fields: Dict[str, str] = {}
    for part in line.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key:
            fields[key] = value

    extracted_temperature = _extract_labeled_temperature(line)
    if extracted_temperature is not None:
        fields["temp"] = extracted_temperature

    if "heat" not in fields:
        match = re.search(r"\bheat(?:er)?\s*=\s*([A-Za-z0-9_-]+)", line, flags=re.IGNORECASE)
        if match:
            fields["heat"] = match.group(1)

    if "motor" not in fields:
        match = re.search(r"\bmotor(?:_on)?\s*=\s*([A-Za-z0-9_-]+)", line, flags=re.IGNORECASE)
        if match:
            fields["motor"] = match.group(1)

    if "kill" not in fields:
        match = re.search(r"\bkill(?:_state|ed)?\s*=\s*([A-Za-z0-9_-]+)", line, flags=re.IGNORECASE)
        if match:
            fields["kill"] = match.group(1)

    uptime_value = fields.get("uptime") or fields.get("uptime_s") or fields.get("uptime_seconds")
    uptime_seconds = coerce_uptime_seconds(uptime_value)
    temperature = coerce_float(fields.get("temp") or fields.get("temperature"))
    heater_on = coerce_bool(fields.get("heat") or fields.get("heater") or fields.get("heater_on"))
    motor_on = coerce_bool(fields.get("motor") or fields.get("motor_on"))
    kill_state = coerce_bool(fields.get("kill") or fields.get("kill_state") or fields.get("killed"))
    system_on = coerce_bool(
        fields.get("system_on") or fields.get("system") or fields.get("relay_on") or fields.get("on")
    )

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
    }


def coerce_uptime_seconds(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))

    text = str(value).strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    total = 0
    found = False
    for amount, unit in re.findall(r"(\d+)\s*([dhms])", text):
        found = True
        count = int(amount)
        if unit == "d":
            total += count * 86400
        elif unit == "h":
            total += count * 3600
        elif unit == "m":
            total += count * 60
        elif unit == "s":
            total += count
    return total if found else None


def load_heater_telemetry() -> Dict[str, Any]:
    url = required_env("AZ_TELEMETRY_URL")
    body, _ = azure_json_request("GET", url)
    parsed: Dict[str, Any] = {}
    source_timestamp: Any = None

    if isinstance(body, dict):
        temperature = coerce_float(first_payload_value(body, ["temperature", "temp", "temperature_c"]))
        if temperature is None:
            raw_value = first_payload_value(body, ["raw", "telemetry", "line", "message"])
            if isinstance(raw_value, str):
                parsed = parse_serial_telemetry_line(raw_value)
        else:
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
        source_timestamp = first_payload_value(body, ["ts", "timestamp", "fetched_at"])

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
        raise RuntimeError("Telemetry response is not a supported format")

    if parsed.get("system_on") is None:
        if parsed.get("kill_state") is True:
            parsed["system_on"] = False
        elif parsed.get("kill_state") is False:
            parsed["system_on"] = True
        elif parsed.get("heater_on") is not None or parsed.get("temperature") is not None:
            parsed["system_on"] = True

    error = ""
    if parsed.get("temperature") is None and source_timestamp in (0, "0", "", None):
        error = "No telemetry sample has been posted to the Azure relay yet"
    elif parsed.get("temperature") is None:
        error = "Azure relay returned telemetry without a temperature value"

    return {
        "temperature": parsed.get("temperature"),
        "heater_on": parsed.get("heater_on"),
        "motor_on": parsed.get("motor_on"),
        "kill_state": parsed.get("kill_state"),
        "system_on": parsed.get("system_on"),
        "uptime_seconds": parsed.get("uptime_seconds"),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_timestamp": source_timestamp,
        "error": error,
    }


def load_heater_telemetry_safe() -> Dict[str, Any]:
    try:
        telemetry = load_heater_telemetry()
    except Exception as exc:
        _logger().exception("Failed to load heater telemetry")
        return {
            "temperature": None,
            "heater_on": None,
            "motor_on": None,
            "kill_state": None,
            "system_on": None,
            "uptime_seconds": None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": str(exc),
        }
    try:
        append_telemetry_log_sample(telemetry)
    except Exception:
        _logger().exception("Failed to append telemetry log sample")
    telemetry["error"] = str(telemetry.get("error") or "")
    return telemetry


def send_heater_command(value: Any) -> Dict[str, Any]:
    url = required_env("AZ_COMMAND_URL")
    body, status = azure_json_request("POST", url, payload={"type": "KILL", "value": value})
    return {"status": status, "response": body}
