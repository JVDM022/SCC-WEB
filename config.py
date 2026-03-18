from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent
_FILE_SOURCED_ENV_KEYS: set[str] = set()


def _parse_env_file(path: str | Path) -> Dict[str, str]:
    env_path = Path(path)
    parsed: Dict[str, str] = {}
    if not env_path.exists():
        return parsed

    try:
        with env_path.open("r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key:
                    parsed[key] = value
    except OSError:
        return {}

    return parsed


def load_dotenv(path: str | Path = PROJECT_ROOT / ".env") -> None:
    parsed = _parse_env_file(path)
    for key, value in parsed.items():
        if key in os.environ:
            continue
        os.environ[key] = value
        _FILE_SOURCED_ENV_KEYS.add(key)


def get_env(name: str, default: str | None = None) -> str | None:
    if name in _FILE_SOURCED_ENV_KEYS:
        for candidate in (PROJECT_ROOT / ".env",):
            parsed = _parse_env_file(candidate)
            value = parsed.get(name)
            if value is None:
                continue
            os.environ[name] = value
            return value

    current = os.environ.get(name)
    if current is not None:
        return current

    for candidate in (PROJECT_ROOT / ".env",):
        parsed = _parse_env_file(candidate)
        value = parsed.get(name)
        if value is None:
            continue
        os.environ[name] = value
        _FILE_SOURCED_ENV_KEYS.add(name)
        return value

    return default


def _is_placeholder_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    if "<" in text and ">" in text:
        return True
    return text.startswith("/absolute/path/")


def _resolved_telemetry_log_path() -> Path:
    raw_value = (get_env("TELEMETRY_LOG_PATH", "") or "").strip()
    if _is_placeholder_path(raw_value):
        return (PROJECT_ROOT / "system_status_temperature_log.csv").expanduser()
    return Path(raw_value).expanduser()


load_dotenv(PROJECT_ROOT / ".env")

try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError as exc:
    raise RuntimeError("DATABASE_URL environment variable is required") from exc


AZURE_TIMEOUT_SECONDS = float(get_env("AZURE_TIMEOUT_SECONDS", "30") or "30")
AZURE_POOL_TIMEOUT = float(get_env("AZURE_POOL_TIMEOUT", "15") or "15")
BROADCAST_SOURCE_URL_FALLBACK = (get_env("AZ_TELEMETRY_URL", "") or "").strip()
BROADCAST_ENDPOINT_URL = (get_env("BROADCAST_ENDPOINT_URL", "") or "").strip()
BROADCAST_ENDPOINT_METHOD = (get_env("BROADCAST_ENDPOINT_METHOD", "GET") or "GET").strip().upper() or "GET"
BROADCAST_ENDPOINT_HEADERS_JSON = (get_env("BROADCAST_ENDPOINT_HEADERS_JSON", "") or "").strip()
BROADCAST_ENDPOINT_PAYLOAD_JSON = (get_env("BROADCAST_ENDPOINT_PAYLOAD_JSON", "") or "").strip()
AZURE_STORAGE_CONNECTION_STRING = (get_env("AZURE_STORAGE_CONNECTION_STRING", "") or "").strip()
BROADCAST_BLOB_CONTAINER = (get_env("BROADCAST_BLOB_CONTAINER", "documentation") or "documentation").strip() or "documentation"
BROADCAST_BLOB_PATH_PREFIX = (get_env("BROADCAST_BLOB_PATH_PREFIX", "broadcast") or "broadcast").strip() or "broadcast"
IOTHUB_CONNECTION_STRING = (get_env("IOTHUB_CONNECTION_STRING", "") or "").strip()
IOTHUB_DEFAULT_DEVICE_ID = (get_env("IOTHUB_DEFAULT_DEVICE_ID", "") or "").strip()
IOTHUB_EVENTHUB_CONNECTION_STRING = (get_env("IOTHUB_EVENTHUB_CONNECTION_STRING", "") or "").strip()
IOTHUB_EVENTHUB_CONSUMER_GROUP = (
    get_env("IOTHUB_EVENTHUB_CONSUMER_GROUP", "$Default") or "$Default"
).strip() or "$Default"
IOTHUB_OTA_MAX_EXECUTION_SECONDS = int(
    get_env("IOTHUB_OTA_MAX_EXECUTION_SECONDS", "3600") or "3600"
)
TELEMETRY_LOG_PATH = _resolved_telemetry_log_path()
TELEMETRY_LOG_HEADERS = [
    "timestamp",
    "temperature_c",
    "heat",
    "motor",
    "kill_state",
]
TELEMETRY_LOG_LOCK = threading.Lock()
PORT = int(get_env("PORT", "5001") or "5001")
FLASK_DEBUG = (get_env("FLASK_DEBUG", "0") or "0") == "1"
RUN_DB_INIT = (get_env("RUN_DB_INIT", "0") or "0") == "1"

PHASES = ["Concept", "Developing", "Prototype", "Testing", "Complete"]
PHASE_TO_PERCENT = {
    "Concept": 0,
    "Developing": 25,
    "Prototype": 50,
    "Testing": 75,
    "Complete": 100,
}

CARD_KEYS = ["development_progress", "bom", "documentation", "system_status", "tasks", "risks"]
DOC_TYPE_FILTER_ALL = "__all__"

ENTITY_DEFS: Dict[str, Dict[str, Any]] = {
    "project": {
        "label": "Project Metadata",
        "fields": [
            {"name": "name", "label": "Project name", "input_type": "text"},
        ],
    },
    "bom": {
        "label": "Bill of Materials",
        "fields": [
            {"name": "item", "label": "Item", "input_type": "text"},
            {"name": "part_number", "label": "Part #", "input_type": "text"},
            {"name": "qty", "label": "Qty", "input_type": "number", "step": "1"},
            {"name": "unit_cost", "label": "Unit cost", "input_type": "number", "step": "0.01"},
            {"name": "supplier", "label": "Supplier", "input_type": "text"},
            {"name": "lead_time_days", "label": "Lead time (days)", "input_type": "number", "step": "1"},
            {"name": "status", "label": "Status", "input_type": "text"},
            {"name": "link", "label": "Link", "input_type": "text"},
        ],
    },
    "documentation": {
        "label": "Documentation",
        "fields": [
            {"name": "title", "label": "Title", "input_type": "text"},
            {"name": "doc_type", "label": "Type", "input_type": "text"},
            {"name": "owner", "label": "Owner", "input_type": "text"},
            {"name": "location", "label": "Location", "input_type": "text"},
            {"name": "status", "label": "Status", "input_type": "text"},
        ],
    },
    "system_status": {
        "label": "System Status",
        "fields": [
            {"name": "is_online", "label": "Status", "input_type": "text"},
            {"name": "reason", "label": "Reason / notes", "widget": "textarea"},
            {"name": "estimated_downtime", "label": "Estimated downtime", "input_type": "date"},
        ],
    },
    "tasks": {
        "label": "Tasks",
        "fields": [
            {"name": "task", "label": "Task", "input_type": "text"},
            {"name": "due_date", "label": "Due date", "input_type": "date"},
            {"name": "priority", "label": "Priority", "input_type": "text"},
            {"name": "status", "label": "Status", "input_type": "text"},
        ],
    },
    "risks": {
        "label": "Risks",
        "fields": [
            {"name": "risk", "label": "Risk", "input_type": "text"},
            {"name": "impact", "label": "Impact", "widget": "textarea"},
            {"name": "solution", "label": "Solution", "widget": "textarea"},
            {"name": "status", "label": "Status", "input_type": "text"},
        ],
    },
    "development_log": {
        "label": "Development Log",
        "fields": [
            {"name": "log_date", "label": "Date", "input_type": "date"},
            {"name": "summary", "label": "Summary", "input_type": "text"},
            {"name": "details", "label": "Details", "widget": "textarea"},
        ],
    },
}
