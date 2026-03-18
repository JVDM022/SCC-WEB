from __future__ import annotations

import csv
import re
from datetime import datetime
from typing import Any, Dict, List

from config import TELEMETRY_LOG_HEADERS, TELEMETRY_LOG_LOCK, TELEMETRY_LOG_PATH


_TELEMETRY_LOG_COUNT_CACHE: int | None = None
_TELEMETRY_LOG_COUNT_SIGNATURE: tuple[int, int] | None = None
_FLOAT_TOKEN_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)")


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
    if value is True:
        return "1"
    if value is False:
        return "0"
    return ""


def _normalize_telemetry_log_row(row: Dict[str, Any] | None) -> Dict[str, str]:
    row = {} if row is None else row
    return {
        "timestamp": str(row.get("timestamp") or ""),
        "temperature_c": str(
            row.get("temperature_c") or row.get("temperature") or row.get("temp") or ""
        ),
        "heat": str(
            row.get("heat") or row.get("heater_on") or row.get("heater") or ""
        ),
        "motor": str(
            row.get("motor") or row.get("motor_on") or ""
        ),
        "kill_state": str(
            row.get("kill_state") or row.get("kill") or row.get("killed") or ""
        ),
    }


def _write_telemetry_log_rows(rows: List[Dict[str, Any]]) -> None:
    with TELEMETRY_LOG_PATH.open("w", newline="", encoding="utf-8") as log_file:
        writer = csv.DictWriter(log_file, fieldnames=TELEMETRY_LOG_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_normalize_telemetry_log_row(row))


def ensure_telemetry_log_file() -> None:
    TELEMETRY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not TELEMETRY_LOG_PATH.exists():
        _write_telemetry_log_rows([])
        return

    with TELEMETRY_LOG_PATH.open("r", newline="", encoding="utf-8") as log_file:
        reader = csv.DictReader(log_file)
        if reader.fieldnames == TELEMETRY_LOG_HEADERS:
            return
        rows = list(reader)

    _write_telemetry_log_rows(rows)


def append_telemetry_log_sample(telemetry: Dict[str, Any]) -> None:
    global _TELEMETRY_LOG_COUNT_CACHE, _TELEMETRY_LOG_COUNT_SIGNATURE

    temperature = telemetry.get("temperature")
    if temperature is None:
        return

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "temperature_c": f"{float(temperature):.4f}",
        "heat": bool_to_log_value(telemetry.get("heater_on")),
        "motor": bool_to_log_value(telemetry.get("motor_on")),
        "kill_state": bool_to_log_value(telemetry.get("kill_state")),
    }
    with TELEMETRY_LOG_LOCK:
        ensure_telemetry_log_file()
        with TELEMETRY_LOG_PATH.open("a", newline="", encoding="utf-8") as log_file:
            writer = csv.DictWriter(log_file, fieldnames=TELEMETRY_LOG_HEADERS)
            writer.writerow(row)
        _TELEMETRY_LOG_COUNT_CACHE = None
        _TELEMETRY_LOG_COUNT_SIGNATURE = None


def telemetry_log_signature() -> tuple[int, int] | None:
    try:
        stat = TELEMETRY_LOG_PATH.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def telemetry_log_sample_count() -> int:
    global _TELEMETRY_LOG_COUNT_CACHE, _TELEMETRY_LOG_COUNT_SIGNATURE

    with TELEMETRY_LOG_LOCK:
        if not TELEMETRY_LOG_PATH.exists():
            _TELEMETRY_LOG_COUNT_CACHE = 0
            _TELEMETRY_LOG_COUNT_SIGNATURE = None
            return 0

        signature = telemetry_log_signature()
        if (
            _TELEMETRY_LOG_COUNT_CACHE is not None
            and _TELEMETRY_LOG_COUNT_SIGNATURE == signature
        ):
            return _TELEMETRY_LOG_COUNT_CACHE

        with TELEMETRY_LOG_PATH.open("r", encoding="utf-8") as log_file:
            row_count = sum(1 for _ in log_file)
        count = max(0, row_count - 1)
        _TELEMETRY_LOG_COUNT_CACHE = count
        _TELEMETRY_LOG_COUNT_SIGNATURE = signature
        return count
