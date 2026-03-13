from __future__ import annotations

import csv
from datetime import datetime
from typing import Any, Dict, List

from config import TELEMETRY_LOG_HEADERS, TELEMETRY_LOG_LOCK, TELEMETRY_LOG_PATH


def coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    if value is True:
        return "1"
    if value is False:
        return "0"
    return ""


def ensure_telemetry_log_file() -> None:
    TELEMETRY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TELEMETRY_LOG_PATH.exists():
        return
    with TELEMETRY_LOG_PATH.open("w", newline="", encoding="utf-8") as log_file:
        writer = csv.DictWriter(log_file, fieldnames=TELEMETRY_LOG_HEADERS)
        writer.writeheader()


def append_telemetry_log_sample(telemetry: Dict[str, Any]) -> None:
    temperature = telemetry.get("temperature")
    if temperature is None:
        return

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "temperature_c": f"{float(temperature):.4f}",
        "heater_on": bool_to_log_value(telemetry.get("heater_on")),
        "kill_state": bool_to_log_value(telemetry.get("kill_state")),
    }
    with TELEMETRY_LOG_LOCK:
        ensure_telemetry_log_file()
        with TELEMETRY_LOG_PATH.open("a", newline="", encoding="utf-8") as log_file:
            writer = csv.DictWriter(log_file, fieldnames=TELEMETRY_LOG_HEADERS)
            writer.writerow(row)


def telemetry_log_sample_count() -> int:
    if not TELEMETRY_LOG_PATH.exists():
        return 0
    with TELEMETRY_LOG_LOCK:
        with TELEMETRY_LOG_PATH.open("r", encoding="utf-8") as log_file:
            row_count = sum(1 for _ in log_file)
    return max(0, row_count - 1)
