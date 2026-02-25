from __future__ import annotations

import ast
import importlib.util
import os
import pkgutil
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

# Python 3.14: legacy AST node aliases removed. Werkzeug still expects them.
if not hasattr(ast, "Str"):
    ast.Str = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Bytes"):
    ast.Bytes = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Num"):
    ast.Num = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "NameConstant"):
    ast.NameConstant = ast.Constant  # type: ignore[attr-defined]

# Provide legacy attribute access on ast.Constant for older AST APIs.
if not hasattr(ast.Constant, "s"):
    def _get_s(self):
        return self.value

    def _set_s(self, value):
        self.value = value

    ast.Constant.s = property(_get_s, _set_s)  # type: ignore[attr-defined]

if not hasattr(ast.Constant, "n"):
    def _get_n(self):
        return self.value

    def _set_n(self, value):
        self.value = value

    ast.Constant.n = property(_get_n, _set_n)  # type: ignore[attr-defined]

# Flask 3.0 + Python 3.14 compatibility: pkgutil.get_loader was removed.
if not hasattr(pkgutil, "get_loader"):
    def _get_loader(name: str):
        try:
            spec = importlib.util.find_spec(name)
        except (ValueError, ImportError):
            return None
        return spec.loader if spec else None

    pkgutil.get_loader = _get_loader  # type: ignore[attr-defined]

from flask import Flask, abort, g, jsonify, request
from reactpy import component, event, hooks, html
from reactpy.backend.flask import Options, configure


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as env_file:
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


load_dotenv()

app = Flask(__name__)

try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError as exc:
    raise RuntimeError("DATABASE_URL environment variable is required") from exc


DB_POOL: pool.ThreadedConnectionPool | None = None

# Optionally initialize/upgrade schema at process startup if env var is set.
def maybe_init_db_on_startup() -> None:
    """Optionally initialize/upgrade schema at process startup.

    IMPORTANT: Do not run schema changes on the request path; it can cause slow first loads
    and unstable interactive sessions. To run once, set RUN_DB_INIT=1, restart the app,
    then set RUN_DB_INIT=0 again.
    """
    if os.environ.get("RUN_DB_INIT", "0") != "1":
        return

    db = None
    try:
        db = get_db_pool().getconn()
        init_db(db)
    finally:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
            get_db_pool().putconn(db)

PHASES = ["Concept", "Developing", "Prototype", "Testing", "Complete"]
PHASE_TO_PERCENT = {
    "Concept": 0,
    "Developing": 25,
    "Prototype": 50,
    "Testing": 75,
    "Complete": 100,
}

CARD_KEYS = ["development_progress", "bom", "documentation", "system_status", "tasks", "risks"]

ENTITY_DEFS = {
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


def get_db_pool() -> pool.ThreadedConnectionPool:
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
    return DB_POOL


def ensure_column(db, table: str, column: str, col_type: str) -> None:
    with db.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")


def init_db(db) -> None:
    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS project (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            owner TEXT,
            phase TEXT,
            target_release TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bom (
            id BIGSERIAL PRIMARY KEY,
            item TEXT,
            part_number TEXT,
            qty INTEGER,
            unit_cost REAL,
            supplier TEXT,
            lead_time_days INTEGER,
            status TEXT,
            link TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS documentation (
            id BIGSERIAL PRIMARY KEY,
            title TEXT,
            doc_type TEXT,
            owner TEXT,
            location TEXT,
            status TEXT,
            last_updated TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_status (
            id BIGSERIAL PRIMARY KEY,
            is_online INTEGER,
            reason TEXT,
            estimated_downtime TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS development_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            percent INTEGER,
            phase TEXT,
            status_text TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS development_log (
            id BIGSERIAL PRIMARY KEY,
            log_date TEXT,
            summary TEXT,
            details TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS card_state (
            key TEXT PRIMARY KEY,
            position INTEGER,
            pinned INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id BIGSERIAL PRIMARY KEY,
            task TEXT,
            owner TEXT,
            due_date TEXT,
            priority TEXT,
            status TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS risks (
            id BIGSERIAL PRIMARY KEY,
            risk TEXT,
            impact TEXT,
            solution TEXT,
            owner TEXT,
            status TEXT
        )
        """,
    ]

    with db.cursor() as cursor:
        for statement in schema_statements:
            cursor.execute(statement)
        cursor.execute(
            "INSERT INTO project (id, name, owner, phase, target_release) VALUES (1, '', '', '', '') "
            "ON CONFLICT (id) DO NOTHING"
        )

    ensure_column(db, "development_progress", "percent", "INTEGER")
    ensure_column(db, "development_progress", "phase", "TEXT")
    ensure_column(db, "development_progress", "status_text", "TEXT")
    ensure_column(db, "system_status", "is_online", "INTEGER")
    ensure_column(db, "tasks", "due_date", "TEXT")
    ensure_column(db, "tasks", "priority", "TEXT")
    ensure_column(db, "bom", "link", "TEXT")
    ensure_column(db, "risks", "solution", "TEXT")

    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO development_progress (id, percent, phase, status_text) VALUES (1, NULL, '', '') "
            "ON CONFLICT (id) DO NOTHING"
        )
        for position, key in enumerate(CARD_KEYS):
            cursor.execute(
                "INSERT INTO card_state (key, position, pinned) VALUES (%s, %s, 0) "
                "ON CONFLICT (key) DO NOTHING",
                (key, position),
            )

    db.commit()


def _to_postgres_placeholders(query: str) -> str:
    return query.replace("?", "%s")


def fetch_one(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> Dict[str, Any] | None:
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None


def fetch_all_rows(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> List[Dict[str, Any]]:
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)
        return [dict(row) for row in cursor.fetchall()]


def execute_sql(query: str, params: List[Any] | tuple[Any, ...] | None = None) -> None:
    with get_db().cursor() as cursor:
        cursor.execute(_to_postgres_placeholders(query), params)


def get_db():
    if "db" not in g:
        db = get_db_pool().getconn()
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(exc: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        try:
            db.rollback()
        except Exception:
            pass
        get_db_pool().putconn(db)


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
        query = "SELECT * FROM development_log ORDER BY log_date DESC, id DESC"
        rows = fetch_all_rows(query)
    else:
        rows = fetch_all_rows(f"SELECT * FROM {entity} ORDER BY id DESC")
    return rows


def entity_or_404(entity: str) -> Dict[str, Any]:
    if entity not in ENTITY_DEFS or entity == "project":
        abort(404)
    return ENTITY_DEFS[entity]


def empty_values(fields: List[Dict[str, Any]]) -> Dict[str, str]:
    return {field["name"]: "" for field in fields}


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


DOC_TYPE_FILTER_ALL = "__all__"


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
        app.logger.exception("Failed to load dashboard data")
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
            data[name] = 1 if str(value).lower() in {"1", "true", "yes", "on"} else 0
        else:
            data[name] = "" if value is None else str(value).strip()
    return data


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


@app.route("/api/data")
def api_data():
    return jsonify(
        {
            "project": fetch_project(),
            "development_progress": fetch_development_progress(),
            "bom": fetch_all("bom"),
            "documentation": fetch_all("documentation"),
            "system_status": fetch_all("system_status"),
            "tasks": fetch_all("tasks"),
            "risks": fetch_all("risks"),
            "development_log": fetch_all("development_log"),
            "last_updated": datetime.now().isoformat(timespec="minutes"),
        }
    )


@app.route("/api/db-health")
def api_db_health():
    row = fetch_one("SELECT 1 AS ok")
    return jsonify({"ok": bool(row and row.get("ok") == 1)})


@app.route("/api/project", methods=["GET", "PUT"])
def api_project():
    if request.method == "GET":
        return jsonify(fetch_project())
    payload = request.get_json(silent=True) or {}
    update_project(payload)
    return jsonify({"ok": True})


@app.route("/api/development_progress", methods=["GET", "PUT"])
def api_progress():
    if request.method == "GET":
        return jsonify(fetch_development_progress())
    payload = request.get_json(silent=True) or {}
    update_progress(payload)
    return jsonify({"ok": True})


@app.route("/api/<entity>", methods=["GET", "POST"])
def api_entity_collection(entity: str):
    entity_or_404(entity)
    if request.method == "GET":
        return jsonify(fetch_all(entity))
    payload = request.get_json(silent=True) or {}
    insert_entity(entity, payload)
    return jsonify({"ok": True})


@app.route("/api/<entity>/<int:item_id>", methods=["PUT", "DELETE"])
def api_entity_item(entity: str, item_id: int):
    entity_or_404(entity)
    if request.method == "DELETE":
        delete_entity(entity, item_id)
        return jsonify({"ok": True})
    payload = request.get_json(silent=True) or {}
    update_entity(entity, item_id, payload)
    return jsonify({"ok": True})


GLASS_CSS = """
:root {
  color-scheme: light;
  --bg: #eaf2ff;
  --bg-2: #86c9ff;
  --bg-3: #356eff;
  --bg-4: #f2f6ff;
  --glass: rgba(255, 255, 255, 0.58);
  --glass-2: rgba(255, 255, 255, 0.32);
  --border: rgba(255, 255, 255, 0.5);
  --text: #0b1220;
  --muted: #56627a;
  --shadow: 0 24px 60px rgba(10, 20, 45, 0.22);
  --shadow-soft: 0 12px 30px rgba(10, 20, 45, 0.14);
  --blur: 26px;
  --radius: 22px;
  --accent: #0a84ff;
  --accent-2: #6bd7ff;
  --accent-3: #ff7ad9;
  --glow-1: rgba(255, 255, 255, 0.9);
  --glow-2: rgba(110, 200, 255, 0.5);
  --glow-3: rgba(255, 120, 215, 0.4);
  --vignette: rgba(10, 16, 30, 0.25);
}

@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0b1022;
    --bg-2: #111f3d;
    --bg-3: #1b2f61;
    --bg-4: #0b142b;
    --glass: rgba(12, 18, 34, 0.62);
    --glass-2: rgba(12, 18, 34, 0.42);
    --border: rgba(255, 255, 255, 0.14);
    --text: #ecf2ff;
    --muted: #a7b6d3;
    --shadow: 0 26px 70px rgba(0, 0, 0, 0.45);
    --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.3);
    --blur: 30px;
    --accent: #6bb7ff;
    --accent-2: #7ee1ff;
    --accent-3: #ff8bde;
    --glow-1: rgba(120, 160, 255, 0.35);
    --glow-2: rgba(80, 150, 255, 0.4);
    --glow-3: rgba(255, 130, 220, 0.3);
    --vignette: rgba(0, 0, 0, 0.5);
  }
}

* { box-sizing: border-box; }

html, body {
  width: 100%;
  max-width: 100%;
}

body {
  margin: 0;
  font-family: "SF Pro Text", "SF Pro Display", "Helvetica Neue", "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(1200px 700px at 10% -10%, var(--glow-1), transparent 60%),
    radial-gradient(900px 700px at 110% 0%, var(--glow-3), transparent 65%),
    radial-gradient(800px 600px at -10% 60%, var(--glow-2), transparent 70%),
    radial-gradient(120% 120% at 50% 30%, rgba(255, 255, 255, 0.18), var(--vignette) 70%),
    linear-gradient(155deg, var(--bg-2) 0%, var(--bg-3) 55%, var(--bg-4) 100%);
  min-height: 100vh;
  overflow-x: hidden;
  position: relative;
  isolation: isolate;
}

body::before {
  content: "";
  position: fixed;
  inset: -20% -10% auto -10%;
  height: 70vh;
  background:
    radial-gradient(600px 320px at 15% 15%, rgba(255, 255, 255, 0.6), transparent 70%),
    radial-gradient(700px 340px at 70% 0%, rgba(255, 255, 255, 0.35), transparent 72%);
  filter: blur(44px) saturate(160%);
  pointer-events: none;
  z-index: -1;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='0.4'/%3E%3C/svg%3E");
  opacity: 0.07;
  mix-blend-mode: soft-light;
  pointer-events: none;
  z-index: 3;
}

.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 32px 24px 88px;
  display: grid;
  gap: 24px;
  position: relative;
  z-index: 1;
}

.glass-surface {
  background: linear-gradient(135deg, var(--glass), var(--glass-2));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow:
    var(--shadow),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(var(--surface-blur, var(--blur))) saturate(180%);
  -webkit-backdrop-filter: blur(var(--surface-blur, var(--blur))) saturate(180%);
  position: relative;
  overflow: hidden;
}

.glass-surface::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0));
  opacity: 0.55;
  pointer-events: none;
}

.glass-surface::after {
  content: "";
  position: absolute;
  inset: auto -20% -45% -20%;
  height: 70%;
  background:
    radial-gradient(320px 220px at 15% 20%, rgba(10, 132, 255, 0.35), transparent 70%),
    radial-gradient(320px 220px at 85% 80%, rgba(255, 122, 217, 0.32), transparent 70%);
  opacity: 0.55;
  mix-blend-mode: screen;
  pointer-events: none;
}

.glass-surface > * { position: relative; z-index: 1; }

.glass-card { --surface-blur: calc(var(--blur) + 6px); }
.glass-panel { --surface-blur: calc(var(--blur) - 4px); }

.card {
  padding: 24px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.navbar {
  max-width: 1120px;
  margin: 20px auto 0;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  position: sticky;
  top: 16px;
  z-index: 10;
}

.glass-navbar { --surface-blur: calc(var(--blur) + 10px); }

.nav-left {
  display: grid;
  gap: 2px;
  min-width: 0;
  flex: 1 1 280px;
}

.nav-eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.28em;
  font-size: 10px;
  color: var(--muted);
}

.nav-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

.nav-meta {
  font-size: 12px;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.nav-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.3em;
  font-size: 11px;
  color: var(--muted);
}

h1, h2 {
  margin: 0 0 8px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

h1 { font-size: 32px; }

h2 { font-size: 20px; margin-bottom: 4px; }

.meta { color: var(--muted); font-size: 14px; }

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.doc-filter {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.doc-filter .segmented {
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
}

.glass-btn,
.btn {
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.8), rgba(255, 255, 255, 0.35));
  padding: 10px 16px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text);
  box-shadow:
    var(--shadow-soft),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(14px) saturate(160%);
  -webkit-backdrop-filter: blur(14px) saturate(160%);
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.glass-btn::before,
.btn::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0) 55%),
    radial-gradient(80px 40px at 20% 0%, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0));
  opacity: 0.75;
  pointer-events: none;
}

.btn.primary {
  background: linear-gradient(160deg, var(--accent-2), var(--accent) 55%, #0a4bd6 100%);
  color: #fff;
  border: 1px solid rgba(10, 120, 255, 0.55);
  box-shadow:
    0 18px 44px rgba(10, 130, 255, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.btn.secondary {
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.3));
  color: var(--text);
}

.btn.primary::before { opacity: 0.35; }

.btn.ghost {
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: none;
}

.btn:focus-visible,
.seg-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.2);
}

.btn[disabled],
.glass-btn[disabled],
.seg-btn[disabled] {
  cursor: wait;
  opacity: 0.6;
  pointer-events: none;
  transform: none !important;
  box-shadow: none !important;
}

.input[disabled],
.textarea[disabled] {
  opacity: 0.75;
  cursor: not-allowed;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.55));
  font-size: 12px;
  color: var(--muted);
}

.pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
}

.pill-success { background: rgba(68, 201, 140, 0.18); color: #0f5132; border-color: rgba(68, 201, 140, 0.5); }
.pill-warning { background: rgba(255, 176, 86, 0.2); color: #7a4b0b; border-color: rgba(255, 176, 86, 0.5); }
.pill-danger { background: rgba(255, 99, 99, 0.2); color: #7a1010; border-color: rgba(255, 99, 99, 0.5); }
.pill-info { background: rgba(86, 160, 255, 0.2); color: #133d7a; border-color: rgba(86, 160, 255, 0.5); }
.pill-muted { background: rgba(15, 23, 42, 0.08); color: var(--muted); border-color: rgba(15, 23, 42, 0.12); }

.progress-card {
  padding: 16px;
  display: grid;
  gap: 12px;
  border-radius: 18px;
}

.progress-track {
  height: 12px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}

.progress-track span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
}

.phase-track {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.phase-step {
  text-align: center;
  font-size: 11px;
  padding: 6px 4px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.65);
  color: var(--muted);
  border: 1px solid rgba(255, 255, 255, 0.5);
  cursor: pointer;
  font-family: inherit;
  appearance: none;
}

.phase-step.active {
  background: rgba(10, 132, 255, 0.15);
  color: var(--accent);
  border-color: rgba(10, 132, 255, 0.5);
  font-weight: 600;
}

.list { display: grid; gap: 12px; }

.log-entry,
.task-row {
  padding: 14px 16px;
  border-radius: 16px;
  display: grid;
  gap: 8px;
}

.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.task-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

.table-wrap {
  border-radius: 16px;
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.table th, .table td {
  text-align: left;
  padding: 12px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.table th {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.6);
}

.table tr:last-child td { border-bottom: none; }

.link { color: var(--accent); text-decoration: none; font-weight: 600; }
.link:hover { text-decoration: underline; }

.modal {
  position: fixed;
  inset: 0;
  background: rgba(8, 16, 32, 0.45);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 40;
}

.modal-card {
  width: min(720px, 95vw);
  padding: 24px;
  display: grid;
  gap: 16px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-title { font-size: 20px; margin: 0; }

.form { display: grid; gap: 14px; }

.field { display: grid; gap: 6px; }

.label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
}

.helper { font-size: 12px; color: var(--muted); }

.glass-input,
.input, .textarea, .select {
  width: 100%;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.5));
  font-size: 14px;
  color: var(--text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px) saturate(160%);
  -webkit-backdrop-filter: blur(12px) saturate(160%);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input:focus, .textarea:focus, .select:focus {
  outline: none;
  border-color: rgba(10, 132, 255, 0.6);
  box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.2);
}

.textarea { min-height: 120px; resize: vertical; }

.segmented {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

.seg-btn {
  padding: 10px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.82), rgba(255, 255, 255, 0.45));
  color: var(--muted);
  cursor: pointer;
  font-weight: 600;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.seg-btn.active {
  background: rgba(10, 132, 255, 0.18);
  border-color: rgba(10, 132, 255, 0.5);
  color: var(--accent);
  box-shadow: var(--shadow-soft);
}

.form-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@supports not ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))) {
  .glass-surface,
  .glass-btn,
  .glass-input,
  .glass-navbar {
    background: rgba(255, 255, 255, 0.92);
  }
}

@media (prefers-color-scheme: dark) {
  .glass-surface {
    border-color: rgba(158, 190, 255, 0.24);
    box-shadow:
      var(--shadow),
      inset 0 1px 0 rgba(255, 255, 255, 0.09);
  }

  .glass-surface::before {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.14), rgba(255, 255, 255, 0));
    opacity: 0.7;
  }

  .glass-btn,
  .btn,
  .btn.secondary {
    background: linear-gradient(135deg, rgba(32, 47, 82, 0.84), rgba(20, 30, 56, 0.72));
    color: var(--text);
    border-color: rgba(150, 185, 255, 0.28);
    box-shadow:
      0 12px 30px rgba(0, 0, 0, 0.35),
      inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }

  .glass-btn::before,
  .btn::before {
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0) 58%),
      radial-gradient(80px 40px at 20% 0%, rgba(190, 225, 255, 0.24), rgba(255, 255, 255, 0));
    opacity: 0.7;
  }

  .btn.primary {
    color: #eaf5ff;
    border-color: rgba(98, 180, 255, 0.6);
    box-shadow:
      0 16px 40px rgba(20, 120, 255, 0.35),
      inset 0 1px 0 rgba(255, 255, 255, 0.22);
  }

  .btn.ghost {
    background: rgba(120, 150, 220, 0.16);
    border-color: rgba(160, 190, 255, 0.34);
  }

  .tag {
    background: linear-gradient(135deg, rgba(36, 50, 85, 0.82), rgba(26, 36, 64, 0.68));
    color: #cad7f2;
    border-color: rgba(150, 185, 255, 0.25);
  }

  .pill-success { background: rgba(48, 196, 135, 0.22); color: #9af4c8; border-color: rgba(75, 218, 154, 0.44); }
  .pill-warning { background: rgba(255, 176, 86, 0.22); color: #ffd69f; border-color: rgba(255, 196, 126, 0.42); }
  .pill-danger { background: rgba(255, 99, 99, 0.24); color: #ffc0c0; border-color: rgba(255, 131, 131, 0.42); }
  .pill-info { background: rgba(86, 160, 255, 0.23); color: #b9d8ff; border-color: rgba(126, 184, 255, 0.42); }
  .pill-muted { background: rgba(159, 182, 230, 0.14); color: #c4d1eb; border-color: rgba(174, 197, 245, 0.26); }

  .progress-track { background: rgba(150, 180, 230, 0.22); }

  .phase-step {
    background: rgba(32, 46, 80, 0.8);
    color: #c5d4f1;
    border-color: rgba(158, 190, 255, 0.3);
  }

  .table th,
  .table td {
    border-bottom-color: rgba(170, 195, 240, 0.16);
  }

  .table th {
    background: rgba(26, 37, 65, 0.75);
    color: #c7d6f2;
  }

  .glass-input,
  .input, .textarea, .select {
    border-color: rgba(150, 185, 255, 0.3);
    background: linear-gradient(135deg, rgba(30, 43, 75, 0.84), rgba(20, 30, 56, 0.68));
    color: #edf4ff;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }

  .input::placeholder,
  .textarea::placeholder {
    color: rgba(201, 216, 245, 0.65);
  }

  .seg-btn {
    background: linear-gradient(135deg, rgba(34, 48, 82, 0.84), rgba(22, 33, 60, 0.66));
    color: #c6d4ef;
    border-color: rgba(150, 185, 255, 0.28);
  }

  .seg-btn.active {
    background: rgba(91, 167, 255, 0.24);
    border-color: rgba(114, 185, 255, 0.58);
    color: #def0ff;
  }

  .link { color: #9dcbff; }
  .modal { background: rgba(4, 9, 20, 0.62); }

  @supports not ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))) {
    .glass-surface,
    .glass-btn,
    .glass-input,
    .glass-navbar {
      background: rgba(12, 18, 34, 0.92);
    }
  }
}

@media (hover: hover) and (pointer: fine) {
  .card:hover,
  .glass-panel:hover,
  .glass-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 30px 70px rgba(10, 20, 45, 0.28);
  }

  .btn:hover,
  .seg-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 18px 36px rgba(10, 20, 45, 0.22);
  }
}

@media (max-width: 720px) {
  h1 { font-size: 26px; }
  .page { padding: 24px 16px 70px; }
  .card { padding: 16px; }
  .section-head { align-items: flex-start; }
  .navbar {
    margin: 16px 16px 0;
    padding: 12px 14px;
    top: 8px;
  }
  .nav-left { flex-basis: 100%; }
  .nav-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .task-row { align-items: flex-start; }
  .task-row > :last-child {
    width: 100%;
    justify-content: flex-start;
  }
  .phase-track { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .modal { padding: 12px; }
  .modal-card {
    width: min(720px, calc(100vw - 24px));
    padding: 16px;
  }
  .modal-head {
    flex-wrap: wrap;
    gap: 8px;
    align-items: flex-start;
  }
  .form-actions { justify-content: flex-start; }
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  .card,
  .glass-panel,
  .glass-card,
  .btn,
  .seg-btn { transform: none !important; }
}
"""


@component
def App():
    data, set_data = hooks.use_state(load_dashboard_data_safe)
    modal, set_modal = hooks.use_state({"open": False})
    form_values, set_form_values = hooks.use_state({})
    doc_type_filter, set_doc_type_filter = hooks.use_state(DOC_TYPE_FILTER_ALL)
    is_form_dirty, set_is_form_dirty = hooks.use_state(False)
    is_busy, set_is_busy = hooks.use_state(False)
    busy_ref = hooks.use_ref(False)
    field_event_ts_ref = hooks.use_ref({})
    submit_intent_ref = hooks.use_ref(False)

    def refresh() -> None:
        set_data(load_dashboard_data_safe())

    def run_mutation(action: Callable[[], None], refresh_after: bool = True) -> None:
        if busy_ref.current:
            return
        busy_ref.current = True
        set_is_busy(True)
        try:
            action()
            if refresh_after:
                refresh()
        finally:
            busy_ref.current = False
            set_is_busy(False)

    def close_modal(event: Dict[str, Any] | None = None, force: bool = False) -> None:
        if busy_ref.current:
            return
        if modal.get("open") and is_form_dirty and not force:
            set_modal(lambda prev: {**prev, "confirm_discard": True})
            return
        submit_intent_ref.current = False
        set_is_form_dirty(False)
        set_modal({"open": False})

    def dismiss_discard_warning(event: Dict[str, Any] | None = None) -> None:
        if busy_ref.current:
            return
        set_modal(lambda prev: {**prev, "confirm_discard": False})

    def request_submit(event: Dict[str, Any] | None = None) -> None:
        if busy_ref.current:
            return
        submit_intent_ref.current = True

    def set_field(name: str, value: Any) -> None:
        if busy_ref.current:
            return
        set_form_values(lambda prev: {**prev, name: value})
        if modal.get("open"):
            set_is_form_dirty(True)

    def set_field_from_event(name: str, event: Dict[str, Any]) -> None:
        if busy_ref.current:
            return
        ts_raw = event.get("timeStamp")
        if ts_raw is None:
            ts_raw = event.get("timestamp")
        if ts_raw is not None:
            try:
                ts = float(ts_raw)
            except (TypeError, ValueError):
                ts = None
            else:
                last_ts = field_event_ts_ref.current.get(name, -1.0)
                if ts <= last_ts:
                    return
                field_event_ts_ref.current[name] = ts
        target = event.get("target", {})
        value = target.get("value", "")
        set_form_values(lambda prev: {**prev, name: value})
        if modal.get("open"):
            set_is_form_dirty(True)

    def is_segmented_field(entity: str, name: str) -> bool:
        return (
            (entity == "system_status" and name == "is_online")
            or (entity == "tasks" and name in {"priority", "status"})
            or (entity == "documentation" and name == "status")
            or (entity == "risks" and name == "status")
            or (entity == "bom" and name == "status")
        )

    def submitted_form_values(event_data: Dict[str, Any]) -> Dict[str, Any]:
        values = dict(form_values)
        target = event_data.get("currentTarget") or event_data.get("target") or {}
        elements = target.get("elements") or []
        controls: List[Dict[str, Any]] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            tag = str(element.get("tagName") or "").upper()
            if tag in {"INPUT", "TEXTAREA", "SELECT"}:
                controls.append(element)

        kind = str(modal.get("kind") or "")
        entity = ""
        if kind == "project":
            fields = ENTITY_DEFS["project"]["fields"]
            entity = "project"
        elif kind == "progress":
            fields = [{"name": "percent"}, {"name": "phase"}]
        elif kind == "entity":
            entity = str(modal.get("entity") or "")
            fields = ENTITY_DEFS.get(entity, {}).get("fields", [])
        else:
            fields = []

        input_field_names: List[str] = []
        for field in fields:
            name = str(field.get("name") or "")
            if not name:
                continue
            if entity and is_segmented_field(entity, name):
                continue
            input_field_names.append(name)

        for name, control in zip(input_field_names, controls):
            value = control.get("value", "")
            values[name] = "" if value is None else str(value)
        return values

    def set_progress_phase(phase: str) -> None:
        if busy_ref.current:
            return
        open_progress_modal(phase)

    def open_project_modal() -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_is_form_dirty(False)
        fields = ENTITY_DEFS["project"]["fields"]
        initial = {field["name"]: data["project"].get(field["name"], "") for field in fields}
        set_form_values(initial)
        set_modal({"open": True, "kind": "project", "title": "Edit Project", "confirm_discard": False})

    def open_progress_modal(selected_phase: str | None = None) -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_is_form_dirty(False)
        progress_row = data.get("progress_row", {})
        initial = {
            "phase": normalize_phase(progress_row.get("phase")) or "",
            "percent": progress_row.get("percent") or 0,
        }
        normalized_selected_phase = normalize_phase(selected_phase)
        if normalized_selected_phase:
            initial["phase"] = normalized_selected_phase
            initial["percent"] = PHASE_TO_PERCENT.get(normalized_selected_phase, initial["percent"])
        set_form_values(initial)
        set_modal({"open": True, "kind": "progress", "title": "Update Development Progress", "confirm_discard": False})

    def open_entity_modal(entity: str, mode: str, item: Dict[str, Any] | None = None) -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_is_form_dirty(False)
        fields = ENTITY_DEFS[entity]["fields"]
        if mode == "new":
            initial = default_values_for(entity, fields)
        else:
            item = item or {}
            initial = {field["name"]: item.get(field["name"], "") for field in fields}
        set_form_values(initial)
        set_modal(
            {
                "open": True,
                "kind": "entity",
                "entity": entity,
                "mode": mode,
                "item_id": item.get("id") if item else None,
                "title": ("Add " if mode == "new" else "Edit ") + ENTITY_DEFS[entity]["label"],
                "confirm_discard": False,
            }
        )

    def handle_delete(entity: str, item_id: int) -> None:
        if busy_ref.current:
            return
        run_mutation(lambda: delete_entity(entity, item_id))

    @event(prevent_default=True)
    def handle_submit(event_data: Dict[str, Any]) -> None:
        if not modal.get("open") or busy_ref.current:
            return
        if not submit_intent_ref.current:
            return
        submit_intent_ref.current = False
        kind = modal.get("kind")
        values = submitted_form_values(event_data)

        def commit_form() -> None:
            if kind == "project":
                update_project(values)
            elif kind == "progress":
                update_progress(values)
            elif kind == "entity":
                entity = str(modal.get("entity"))
                if modal.get("mode") == "new":
                    insert_entity(entity, values)
                else:
                    item_id = int(modal.get("item_id") or 0)
                    if item_id:
                        update_entity(entity, item_id, values)

        run_mutation(commit_form)
        close_modal(force=True)

    def render_segmented(name: str, value: str, options: List[Dict[str, str]]):
        return html.div(
            {"class": "segmented"},
            *[
                html.button(
                    {
                        "key": option["value"],
                        "type": "button",
                        "class": f"seg-btn {'active' if value == option['value'] else ''}",
                        "disabled": is_busy,
                        "on_click": lambda event, val=option["value"]: set_field(name, val),
                    },
                    option["label"],
                )
                for option in options
            ],
        )

    def render_field(entity: str, field: Dict[str, Any]):
        name = field["name"]
        label = field["label"]
        value = form_values.get(name, "")
        if entity == "system_status" and name == "is_online":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "1"),
                    [
                        {"label": "Online", "value": "1"},
                        {"label": "Offline", "value": "0"},
                    ],
                ),
            )
        if entity == "tasks" and name == "priority":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "Medium"),
                    [
                        {"label": "High", "value": "High"},
                        {"label": "Medium", "value": "Medium"},
                        {"label": "Low", "value": "Low"},
                    ],
                ),
            )
        if entity == "tasks" and name == "status":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "Not started"),
                    [
                        {"label": "Not started", "value": "Not started"},
                        {"label": "In progress", "value": "In progress"},
                        {"label": "Done", "value": "Done"},
                    ],
                ),
            )
        if entity == "documentation" and name == "status":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "Not started"),
                    [
                        {"label": "Not started", "value": "Not started"},
                        {"label": "In progress", "value": "In progress"},
                        {"label": "Done", "value": "Done"},
                    ],
                ),
            )
        if entity == "risks" and name == "status":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "Ongoing"),
                    [
                        {"label": "Ongoing", "value": "Ongoing"},
                        {"label": "Resolved", "value": "Resolved"},
                    ],
                ),
            )
        if entity == "bom" and name == "status":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                render_segmented(
                    name,
                    str(value or "Not yet purchased"),
                    [
                        {"label": "Not yet purchased", "value": "Not yet purchased"},
                        {"label": "Purchased", "value": "Purchased"},
                    ],
                ),
            )
        if field.get("widget") == "textarea":
            return html.div(
                {"class": "field"},
                html.span({"class": "label"}, label),
                html.textarea(
                    {
                        "name": name,
                        "class": "textarea glass-input",
                        "default_value": value,
                        "disabled": is_busy,
                        "on_change": lambda event: set_field_from_event(name, event),
                        "on_blur": lambda event: set_field_from_event(name, event),
                    }
                ),
            )
        attrs = {
            "name": name,
            "class": "input glass-input",
            "type": field.get("input_type", "text"),
            "default_value": value,
            "disabled": is_busy,
            "on_change": lambda event: set_field_from_event(name, event),
            "on_blur": lambda event: set_field_from_event(name, event),
        }
        if field.get("step"):
            attrs["step"] = field["step"]
        return html.div({"class": "field"}, html.span({"class": "label"}, label), html.input(attrs))

    def render_progress_modal():
        percent_value = form_values.get("percent", 0)
        phase_value = form_values.get("phase", "")
        return html.form(
            {"class": "form", "on_submit": handle_submit},
            html.div(
                {"class": "field"},
                html.span({"class": "label"}, "Percent"),
                html.input(
                    {
                        "name": "percent",
                        "class": "input glass-input",
                        "type": "number",
                        "min": 0,
                        "max": 100,
                        "default_value": percent_value,
                        "disabled": is_busy,
                        "on_change": lambda event: set_field_from_event("percent", event),
                        "on_blur": lambda event: set_field_from_event("percent", event),
                    }
                ),
                html.div({"class": "meta"}, "Use 0-100%"),
            ),
            html.div(
                {"class": "field"},
                html.span({"class": "label"}, "Phase"),
                html.input(
                    {
                        "name": "phase",
                        "class": "input glass-input",
                        "default_value": phase_value,
                        "disabled": is_busy,
                        "on_change": lambda event: set_field_from_event("phase", event),
                        "on_blur": lambda event: set_field_from_event("phase", event),
                    }
                ),
                html.div({"class": "meta"}, "Concept, Developing, Prototype, Testing, Complete"),
            ),
            html.div(
                {"class": "form-actions"},
                html.button({"type": "button", "class": "btn glass-btn ghost", "disabled": is_busy, "on_click": close_modal}, "Cancel"),
                html.button({"type": "submit", "class": "btn glass-btn primary", "disabled": is_busy, "on_click": request_submit}, "Save"),
            ),
        )

    def render_entity_modal(entity: str):
        fields = ENTITY_DEFS[entity]["fields"]
        return html.form(
            {"class": "form", "on_submit": handle_submit},
            *[render_field(entity, field) for field in fields],
            html.div(
                {"class": "form-actions"},
                html.button({"type": "button", "class": "btn glass-btn ghost", "disabled": is_busy, "on_click": close_modal}, "Cancel"),
                html.button({"type": "submit", "class": "btn glass-btn primary", "disabled": is_busy, "on_click": request_submit}, "Save"),
            ),
        )

    def render_modal():
        if not modal.get("open"):
            return None
        title = modal.get("title", "Edit")
        if modal.get("kind") == "progress":
            body = render_progress_modal()
        elif modal.get("kind") == "project":
            body = render_entity_modal("project")
        else:
            body = render_entity_modal(str(modal.get("entity")))
        discard_warning = (
            html.div(
                {"class": "glass-surface glass-panel", "style": {"padding": "12px", "display": "grid", "gap": "10px"}},
                html.div({"class": "meta"}, "You have unsaved changes. Discard them?"),
                html.div(
                    {"class": "form-actions"},
                    html.button(
                        {
                            "class": "btn glass-btn ghost",
                            "type": "button",
                            "disabled": is_busy,
                            "on_click": dismiss_discard_warning,
                        },
                        "Keep editing",
                    ),
                    html.button(
                        {
                            "class": "btn glass-btn primary",
                            "type": "button",
                            "disabled": is_busy,
                            "on_click": lambda e: close_modal(force=True),
                        },
                        "Discard",
                    ),
                ),
            )
            if modal.get("confirm_discard")
            else None
        )
        return html.div(
            {"class": "modal"},
            html.div(
                {"class": "modal-card glass-surface glass-card"},
                html.div(
                    {"class": "modal-head"},
                    html.h3({"class": "modal-title"}, title),
                    html.button({"class": "btn glass-btn ghost", "type": "button", "disabled": is_busy, "on_click": close_modal}, "Close"),
                ),
                *([discard_warning] if discard_warning else []),
                body,
            ),
        )

    def render_cell(entity: str, field: str, row: Dict[str, Any]):
        value = row.get(field, "")
        if entity == "documentation" and field == "doc_type":
            return html.span({"class": "tag"}, value or "")
        if entity == "documentation" and field == "location":
            if value:
                return html.a({"class": "link", "href": value, "target": "_blank", "rel": "noopener"}, "Open")
            return html.span({"class": "meta"}, "No link")
        if entity == "bom" and field == "link":
            if value:
                return html.a({"class": "link", "href": value, "target": "_blank", "rel": "noopener"}, "Open")
            return html.span({"class": "meta"}, "No link")
        if entity == "bom" and field == "status":
            return html.span({"class": f"pill {bom_status_class(value)}"}, value or "")
        if entity == "system_status" and field == "is_online":
            return html.span(
                {"class": f"pill {'pill-success' if str(value) in ['1', 'true', 'True', 'on'] else 'pill-danger'}"},
                "Online" if str(value) in ["1", "true", "True", "on"] else "Offline",
            )
        if entity == "risks" and field == "status":
            return html.span({"class": f"pill {risk_status_class(value)}"}, value or "")
        return value or ""

    def render_section(section: Dict[str, Any]):
        entity = section["key"]
        source_rows = section["rows"]
        rows = source_rows
        fields = section["fields"]
        labels = section["labels"]
        section_meta = f"Manage {section['title'].lower()} entries."
        filter_controls = None

        if entity == "documentation":
            type_label_by_key: Dict[str, str] = {}
            for row in source_rows:
                doc_type = str(row.get("doc_type") or "").strip()
                if not doc_type:
                    continue
                key = normalize_doc_type_key(doc_type)
                if key not in type_label_by_key:
                    type_label_by_key[key] = doc_type

            filter_options = [{"value": DOC_TYPE_FILTER_ALL, "label": "All"}]
            filter_options.extend(
                [
                    {"value": key, "label": label}
                    for key, label in sorted(type_label_by_key.items(), key=lambda item: item[1].lower())
                ]
            )
            option_values = {option["value"] for option in filter_options}
            active_filter = doc_type_filter if doc_type_filter in option_values else DOC_TYPE_FILTER_ALL
            if active_filter == DOC_TYPE_FILTER_ALL:
                rows = source_rows
                filter_label = "All types"
            else:
                rows = [row for row in source_rows if normalize_doc_type_key(row.get("doc_type")) == active_filter]
                filter_label = type_label_by_key.get(active_filter, "Unknown")
            section_meta = f"Showing {len(rows)} of {len(source_rows)} entries. Filter: {filter_label}."
            filter_controls = html.div(
                {"class": "doc-filter"},
                html.span({"class": "label"}, "Filter by type"),
                html.div(
                    {"class": "segmented"},
                    *[
                        html.button(
                            {
                                "key": option["value"],
                                "type": "button",
                                "class": f"seg-btn {'active' if active_filter == option['value'] else ''}",
                                "disabled": is_busy,
                                "on_click": lambda event, value=option["value"]: set_doc_type_filter(value),
                            },
                            option["label"],
                        )
                        for option in filter_options
                    ],
                ),
            )

        actions = []
        if entity == "system_status":
            if rows:
                actions.append(
                    html.button(
                        {"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e, row=rows[0]: open_entity_modal(entity, "edit", row)},
                        "Edit",
                    )
                )
            else:
                actions.append(html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_entity_modal(entity, "new")}, "Add"))
        else:
            actions.append(html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_entity_modal(entity, "new")}, "Add"))
        body = (
            html.div(
                {"class": "table-wrap glass-surface glass-panel"},
                html.table(
                    {"class": "table"},
                    html.thead(
                        html.tr(
                            *[html.th(labels[field]) for field in fields],
                            *([] if entity == "system_status" else [html.th("Actions")]),
                        )
                    ),
                    html.tbody(
                        *[
                            html.tr(
                                {"key": row.get("id", idx)},
                                *[html.td(render_cell(entity, field, row)) for field in fields],
                                *(
                                    []
                                    if entity == "system_status"
                                    else [
                                        html.td(
                                            html.button(
                                                {
                                                    "class": "btn glass-btn ghost",
                                                    "disabled": is_busy,
                                                    "on_click": lambda e, row=row: open_entity_modal(entity, "edit", row),
                                                },
                                                "Edit",
                                            ),
                                            html.button(
                                                {
                                                    "class": "btn glass-btn ghost",
                                                    "disabled": is_busy,
                                                    "on_click": lambda e, row=row: handle_delete(entity, int(row["id"])),
                                                },
                                                "Delete",
                                            ),
                                        )
                                    ]
                                ),
                            )
                            for idx, row in enumerate(rows)
                        ]
                    ),
                ),
            )
            if rows
            else html.div(
                {"class": "meta"},
                "No documentation entries match this type." if entity == "documentation" and source_rows else "No entries yet.",
            )
        )

        return html.section(
            {"class": "card glass-surface glass-card", "key": entity},
            html.div(
                {"class": "section-head"},
                html.div(
                    html.h2(section["title"]),
                    html.div({"class": "meta"}, section_meta),
                ),
                html.div(actions),
            ),
            *([filter_controls] if filter_controls else []),
            body,
        )

    development = data["development"]
    tasks = data["tasks"]
    logs = data["logs"]
    progress_label = development.get("percent_label") or "0%"
    phase_label = data["project"].get("phase") or "No phase"

    if data.get("error"):
        return html.div(
            {"id": "project-hub-root"},
            html.style(GLASS_CSS),
            html.main(
                {"class": "page"},
                html.section(
                    {"class": "card glass-surface glass-card"},
                    html.h1("Dashboard unavailable"),
                    html.div(
                        {"class": "meta"},
                        "The app started, but data could not be loaded. Check DATABASE_URL and database connectivity.",
                    ),
                    html.pre({"class": "meta", "style": {"whiteSpace": "pre-wrap"}}, data.get("error") or "Unknown error"),
                    html.div(
                        {"class": "form-actions"},
                        html.button(
                            {"class": "btn glass-btn primary", "type": "button", "disabled": is_busy, "on_click": lambda e: refresh()},
                            "Retry",
                        ),
                    ),
                ),
            ),
        )

    return html.div(
        {"id": "project-hub-root", "data-unsaved": "1" if modal.get("open") and is_form_dirty else "0"},
        html.style(GLASS_CSS),
        html.header(
            {"class": "navbar glass-surface glass-navbar"},
            html.div(
                {"class": "nav-left"},
                html.div({"class": "nav-eyebrow"}, "Project hub"),
                html.div({"class": "nav-title"}, data["project"].get("name") or "Project"),
                html.div({"class": "nav-meta"}, f"Last updated {data['updated']}"),
            ),
            html.div(
                {"class": "nav-actions"},
                html.span({"class": "pill pill-info"}, f"Progress {progress_label}"),
                html.span({"class": "pill pill-muted"}, phase_label),
                *([html.span({"class": "pill pill-warning"}, "Syncing...")] if is_busy else []),
            ),
        ),
        html.main(
            {"class": "page"},
            html.section(
                {"class": "card glass-surface glass-card hero"},
                html.div(
                    html.div({"class": "eyebrow"}, "Project hub"),
                    html.h1(data["project"].get("name") or "Project"),
                    html.div(
                        {"class": "meta"},
                        f"Phase: {data['project'].get('phase') or ''} · Last updated: {data['updated']}",
                    ),
                ),
                html.div(
                    html.button({"class": "btn glass-btn primary", "disabled": is_busy, "on_click": lambda e: open_project_modal()}, "Edit project"),
                ),
            ),
            html.section(
                {"class": "card glass-surface glass-card"},
                html.div(
                    {"class": "section-head"},
                    html.div(
                        html.h2("Development Progress"),
                        html.div({"class": "meta"}, "Track overall phase and milestones."),
                    ),
                    html.div(
                        html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_progress_modal()}, "Edit progress"),
                        html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_entity_modal("development_log", "new")}, "Add log"),
                    ),
                ),
                html.div(
                    {"class": "progress-card glass-surface glass-panel"},
                    html.div(
                        html.div({"class": "meta"}, "Overall development"),
                        html.div({"class": "meta"}, development.get("percent_label", "")),
                    ),
                    html.div(
                        {"class": "progress-track"},
                        html.span({"style": {"width": f"{development['percent_value']}%"}}),
                    ),
                    html.div(
                        {"class": "phase-track"},
                        *[
                            html.button(
                                {
                                    "class": f"phase-step {'active' if phase == development.get('phase') else ''}",
                                    "type": "button",
                                    "disabled": is_busy,
                                    "on_click": lambda event, phase=phase: set_progress_phase(phase),
                                },
                                phase,
                            )
                            for phase in PHASES
                        ],
                    ),
                ),
                html.div(
                    {"class": "section-head"},
                    html.div(
                        html.h2("Development Log"),
                        html.div({"class": "meta"}, "Latest updates from the team."),
                    ),
                ),
                html.div(
                    {"class": "list"},
                    *[
                        html.div(
                            {"class": "log-entry glass-surface glass-panel", "key": log.get("id", idx)},
                            html.div({"class": "meta"}, log.get("log_date") or ""),
                            html.div({"class": "meta"}, log.get("summary") or "Update"),
                            html.div(log.get("details") or ""),
                            html.div(
                                {"class": "form-actions"},
                                html.button(
                                    {
                                        "class": "btn glass-btn ghost",
                                        "disabled": is_busy,
                                        "on_click": lambda e, log=log: open_entity_modal("development_log", "edit", log),
                                    },
                                    "Edit",
                                ),
                                html.button(
                                    {
                                        "class": "btn glass-btn ghost",
                                        "disabled": is_busy,
                                        "on_click": lambda e, log=log: handle_delete("development_log", int(log["id"])),
                                    },
                                    "Delete",
                                ),
                            ),
                        )
                        for idx, log in enumerate(logs)
                    ]
                    if logs
                    else [html.div({"class": "meta"}, "No log entries yet.")],
                ),
            ),
            html.section(
                {"class": "card glass-surface glass-card"},
                html.div(
                    {"class": "section-head"},
                    html.div(
                        html.h2("Tasks"),
                        html.div({"class": "meta"}, "Current priorities and due dates."),
                    ),
                    html.div(
                        html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_entity_modal("tasks", "new")}, "Add task"),
                    ),
                ),
                html.div(
                    {"class": "list"},
                    *[
                        html.div(
                            {"class": "task-row glass-surface glass-panel", "key": task.get("id", idx)},
                            html.div(
                                html.div(task.get("task") or "Task"),
                                html.div(
                                    {"class": "task-meta"},
                                    html.span({"class": f"pill {task.get('priority_class', '')}"}, task.get("priority") or ""),
                                    html.span({"class": f"pill {task.get('status_class', '')}"}, task.get("status_text") or ""),
                                    html.span({"class": "meta"}, f"Due {task.get('due_date') or 'TBD'}"),
                                ),
                            ),
                            html.div(
                                {"class": "task-meta"},
                                html.button(
                                    {
                                        "class": "btn glass-btn ghost",
                                        "disabled": is_busy,
                                        "on_click": lambda e, task=task: open_entity_modal("tasks", "edit", task),
                                    },
                                    "Edit",
                                ),
                                html.button(
                                    {
                                        "class": "btn glass-btn ghost",
                                        "disabled": is_busy,
                                        "on_click": lambda e, task=task: handle_delete("tasks", int(task["id"])),
                                    },
                                    "Delete",
                                ),
                            ),
                        )
                        for idx, task in enumerate(tasks.get("bars", []))
                    ]
                    if tasks.get("bars")
                    else [html.div({"class": "meta"}, "No tasks yet.")],
                ),
            ),
            *[render_section(section) for section in data["sections"]],
        ),
        render_modal(),
    )



# One-time optional schema initialization at process startup (not per request)
maybe_init_db_on_startup()

configure(
    app,
    App,
    Options(
        head=(
            {"tagName": "title", "children": ["Project Hub"]},
            {
                "tagName": "meta",
                "attributes": {"name": "viewport", "content": "width=device-width, initial-scale=1"},
            },
            {
                "tagName": "script",
                "children": [
                    "window.addEventListener('beforeunload', function (event) {"
                    "  var root = document.getElementById('project-hub-root');"
                    "  if (!root || root.getAttribute('data-unsaved') !== '1') {"
                    "    return;"
                    "  }"
                    "  event.preventDefault();"
                    "  event.returnValue = '';"
                    "});"
                ],
            },
        )
    ),
)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5001")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
