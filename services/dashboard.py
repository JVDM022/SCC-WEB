from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from flask import abort, current_app, has_app_context

from config import CARD_KEYS, ENTITY_DEFS, PHASES, PHASE_TO_PERCENT
from db import execute_sql, fetch_all_rows, fetch_one, get_db


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


def fetch_project() -> Dict[str, Any]:
    row = fetch_one("SELECT * FROM project WHERE id = 1")
    if row is None:
        return {"name": "", "phase": ""}
    return row


def fetch_development_progress() -> Dict[str, Any]:
    row = fetch_one("SELECT * FROM development_progress WHERE id = 1")
    if row is None:
        return {"percent": None, "phase": "", "status_text": ""}
    return row


def fetch_all(entity: str) -> List[Dict[str, Any]]:
    if entity == "development_log":
        return fetch_all_rows("SELECT * FROM development_log ORDER BY log_date DESC, id DESC")
    return fetch_all_rows(f"SELECT * FROM {entity} ORDER BY id DESC")


def entity_or_404(entity: str) -> Dict[str, Any]:
    if entity not in ENTITY_DEFS or entity == "project":
        abort(404)
    return ENTITY_DEFS[entity]


def empty_values(fields: List[Dict[str, Any]]) -> Dict[str, str]:
    return {field["name"]: "" for field in fields}


def parse_online_state(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "online"}:
        return 1
    if text in {"0", "false", "no", "off", "offline"}:
        return 0
    return None


def default_values_for(entity: str, fields: List[Dict[str, Any]]) -> Dict[str, str]:
    values = empty_values(fields)
    if entity == "development_log":
        values["log_date"] = datetime.now().strftime("%Y-%m-%d")
    if entity == "tasks":
        values["priority"] = "Medium"
        values["status"] = "Not started"
    if entity == "documentation":
        values["status"] = "Not started"
    if entity == "bom":
        values["status"] = "Not yet purchased"
    if entity == "risks":
        values["status"] = "Ongoing"
    if entity == "system_status":
        values["is_online"] = "1"
    return values


def parse_percent(value: Any) -> float | None:
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, percent))


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def priority_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "high":
        return "pill-danger"
    if text == "low":
        return "pill-success"
    return "pill-warning"


def task_status_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"done", "complete", "completed"}:
        return "pill-success"
    if text in {"in progress", "in-progress", "inprogress"}:
        return "pill-info"
    return "pill-muted"


def normalize_phase(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    for phase in PHASES:
        if text == phase.lower():
            return phase
    return ""


def phase_from_percent(percent: float | None) -> str:
    if percent is None:
        return ""
    nearest = min(PHASE_TO_PERCENT.items(), key=lambda item: abs(percent - item[1]))
    return nearest[0]


def build_development_view() -> Dict[str, Any]:
    row = fetch_development_progress()
    phase = normalize_phase(row.get("phase"))
    if not phase:
        project_phase = normalize_phase(fetch_project().get("phase"))
        if project_phase:
            phase = project_phase
    percent = parse_percent(row.get("percent"))
    if percent is None and phase in PHASE_TO_PERCENT:
        percent = PHASE_TO_PERCENT[phase]
    if percent is not None and not phase:
        phase = phase_from_percent(percent)
    percent_value = int(round(percent)) if percent is not None else 0
    percent_label = f"{percent_value}%" if percent is not None else ""
    return {
        "percent_value": percent_value,
        "percent_label": percent_label,
        "phase": phase,
    }


def build_tasks_view() -> Dict[str, Any]:
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    day_map = {day: [] for day in days}

    tasks = fetch_all("tasks")
    bars: List[Dict[str, Any]] = []
    for task in tasks:
        due = parse_date(task.get("due_date"))
        due_date = due.date() if due else None
        status_text = str(task.get("status") or "").strip() or "Not started"
        task_view = {
            **task,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else "",
            "priority_class": priority_class(task.get("priority")),
            "status_text": status_text,
            "status_class": task_status_class(status_text),
        }
        bars.append(task_view)
        if due_date in day_map:
            day_map[due_date].append(task_view)

    def sort_key(item: Dict[str, Any]) -> tuple:
        priority = str(item.get("priority") or "").lower()
        priority_rank = {"high": 0, "medium": 1, "low": 2}.get(priority, 1)
        due = parse_date(item.get("due_date")) or datetime.max
        return (priority_rank, due)

    bars.sort(key=sort_key)
    for day_tasks in day_map.values():
        day_tasks.sort(key=sort_key)

    day_views = []
    for day in days:
        day_views.append(
            {
                "label": day.strftime("%a"),
                "date_label": day.strftime("%b %d"),
                "is_today": day == today,
                "tasks": day_map[day],
            }
        )

    return {
        "bars": bars,
        "days": day_views,
        "week_label": week_start.strftime("%b %d, %Y"),
    }


def fetch_card_state() -> Dict[str, Dict[str, int]]:
    rows = fetch_all_rows("SELECT key, position, pinned FROM card_state")
    return {row["key"]: {"position": row["position"], "pinned": row["pinned"]} for row in rows}


def ordered_card_keys() -> List[str]:
    state = fetch_card_state()
    ordered = sorted(state.items(), key=lambda item: item[1].get("position", 0))
    pinned = [key for key, meta in ordered if meta.get("pinned")]
    unpinned = [key for key, meta in ordered if not meta.get("pinned")]
    for key in CARD_KEYS:
        if key not in pinned and key not in unpinned:
            unpinned.append(key)
    return pinned + unpinned


def build_sections() -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for key, definition in ENTITY_DEFS.items():
        if key in {"project", "development_log", "tasks"}:
            continue
        fields = [field["name"] for field in definition["fields"]]
        labels = {field["name"]: field["label"] for field in definition["fields"]}
        rows = fetch_all(key)
        if key == "system_status":
            rows = rows[:1]
        sections.append(
            {
                "key": key,
                "title": definition["label"],
                "fields": fields,
                "labels": labels,
                "rows": rows,
            }
        )
    return sections


def normalize_status_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "")


def normalize_doc_type_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def bom_status_class(value: Any) -> str:
    key = normalize_status_key(value)
    if key in {"purchased", "purchase", "bought"}:
        return "pill-info"
    if key in {"nonpurchased", "notpurchased", "notyetpurchased", "unpurchased", "notbought"}:
        return "pill-danger"
    return "pill-muted"


def risk_status_class(value: Any) -> str:
    key = normalize_status_key(value)
    if key in {"ongoing", "inprogress"}:
        return "pill-danger"
    if key == "resolved":
        return "pill-success"
    return "pill-muted"


def load_dashboard_data() -> Dict[str, Any]:
    return {
        "project": fetch_project(),
        "development": build_development_view(),
        "progress_row": fetch_development_progress(),
        "logs": fetch_all("development_log"),
        "tasks": build_tasks_view(),
        "sections": build_sections(),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def empty_dashboard_data(error: str = "") -> Dict[str, Any]:
    return {
        "project": {"name": "Project", "phase": ""},
        "development": {"percent_value": 0, "percent_label": "0%", "phase": ""},
        "progress_row": {"percent": None, "phase": "", "status_text": ""},
        "logs": [],
        "tasks": {"bars": []},
        "sections": [],
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "error": error,
    }


def load_dashboard_data_safe() -> Dict[str, Any]:
    try:
        data = load_dashboard_data()
    except Exception as exc:
        _logger().exception("Failed to load dashboard data")
        return empty_dashboard_data(error=str(exc))
    data["error"] = ""
    return data


def sanitize_payload(entity: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    definition = ENTITY_DEFS[entity]
    data: Dict[str, Any] = {}
    for field in definition["fields"]:
        name = field["name"]
        value = payload.get(name, "")
        if name == "is_online":
            data[name] = parse_online_state(value) or 0
        else:
            data[name] = "" if value is None else str(value).strip()
    return data


def fetch_current_system_status() -> Dict[str, Any]:
    row = fetch_one("SELECT * FROM system_status ORDER BY id DESC LIMIT 1")
    if row is None:
        return {"id": None, "is_online": None, "reason": "", "estimated_downtime": ""}
    return row


def sanitize_current_system_status_payload(
    payload: Dict[str, Any],
    current: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    current = current or {}
    raw_online = payload.get("is_online", payload.get("status", payload.get("online")))
    parsed_online = parse_online_state(raw_online)

    if parsed_online is None:
        parsed_online = parse_online_state(current.get("is_online"))

    return {
        "is_online": 0 if parsed_online is None else parsed_online,
        "reason": str(payload.get("reason", current.get("reason", "")) or "").strip(),
        "estimated_downtime": str(
            payload.get("estimated_downtime", current.get("estimated_downtime", "")) or ""
        ).strip(),
    }


def upsert_current_system_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = fetch_one("SELECT * FROM system_status ORDER BY id DESC LIMIT 1")
    data = sanitize_current_system_status_payload(payload, current)

    if current is None:
        execute_sql(
            "INSERT INTO system_status (is_online, reason, estimated_downtime) VALUES (%s, %s, %s)",
            (data["is_online"], data["reason"], data["estimated_downtime"]),
        )
    else:
        execute_sql(
            "UPDATE system_status SET is_online = %s, reason = %s, estimated_downtime = %s WHERE id = %s",
            (data["is_online"], data["reason"], data["estimated_downtime"], current["id"]),
        )

    get_db().commit()
    return fetch_current_system_status()


def insert_entity(entity: str, payload: Dict[str, Any]) -> None:
    data = sanitize_payload(entity, payload)
    if entity == "documentation":
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    columns = ", ".join(data.keys())
    placeholders = ", ".join("%s" for _ in data)
    execute_sql(
        f"INSERT INTO {entity} ({columns}) VALUES ({placeholders})",
        list(data.values()),
    )
    get_db().commit()


def update_entity(entity: str, item_id: int, payload: Dict[str, Any]) -> None:
    data = sanitize_payload(entity, payload)
    if entity == "documentation":
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    assignments = ", ".join(f"{key} = %s" for key in data)
    execute_sql(
        f"UPDATE {entity} SET {assignments} WHERE id = %s",
        list(data.values()) + [item_id],
    )
    get_db().commit()


def delete_entity(entity: str, item_id: int) -> None:
    execute_sql(f"DELETE FROM {entity} WHERE id = %s", (item_id,))
    get_db().commit()


def update_project(payload: Dict[str, Any]) -> None:
    data = sanitize_payload("project", payload)
    execute_sql("UPDATE project SET name = %s WHERE id = 1", (data.get("name", ""),))
    get_db().commit()


def update_progress(payload: Dict[str, Any]) -> None:
    percent = parse_percent(payload.get("percent"))
    phase = normalize_phase(payload.get("phase"))
    if percent is None and phase in PHASE_TO_PERCENT:
        percent = PHASE_TO_PERCENT[phase]
    if percent is not None and not phase:
        phase = phase_from_percent(percent)
    percent_value = int(round(percent)) if percent is not None else None
    execute_sql(
        "INSERT INTO development_progress (id, percent, phase, status_text) VALUES (1, NULL, '', '') "
        "ON CONFLICT (id) DO NOTHING"
    )
    execute_sql(
        "UPDATE development_progress SET percent = %s, phase = %s, status_text = %s WHERE id = 1",
        (percent_value, phase, ""),
    )
    if phase:
        execute_sql("UPDATE project SET phase = %s WHERE id = 1", (phase,))
    get_db().commit()
