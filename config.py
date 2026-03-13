from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent


def load_dotenv(path: str | Path = PROJECT_ROOT / ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

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
                    os.environ.setdefault(key, value)
    except OSError:
        pass


load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.example")

try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError as exc:
    raise RuntimeError("DATABASE_URL environment variable is required") from exc


AZURE_TIMEOUT_SECONDS = float(os.environ.get("AZURE_TIMEOUT_SECONDS", "30"))
AZURE_POOL_TIMEOUT = float(os.environ.get("AZURE_POOL_TIMEOUT", "15"))
TELEMETRY_LOG_PATH = Path(
    os.environ.get("TELEMETRY_LOG_PATH", str(PROJECT_ROOT / "system_status_temperature_log.csv"))
).expanduser()
TELEMETRY_LOG_HEADERS = [
    "timestamp",
    "temperature_c",
    "heater_on",
    "kill_state",
]
TELEMETRY_LOG_LOCK = threading.Lock()
PORT = int(os.environ.get("PORT", "5001"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
RUN_DB_INIT = os.environ.get("RUN_DB_INIT", "0") == "1"

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
