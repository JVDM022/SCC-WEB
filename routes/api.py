from __future__ import annotations

from datetime import datetime

from flask import jsonify, request, send_file

from config import TELEMETRY_LOG_LOCK, TELEMETRY_LOG_PATH
from db import fetch_one
from services.azure_relay import load_heater_telemetry_safe, send_heater_command
from services.dashboard import (
    delete_entity,
    entity_or_404,
    fetch_all,
    fetch_development_progress,
    fetch_project,
    insert_entity,
    update_entity,
    update_progress,
    update_project,
)
from services.telemetry import ensure_telemetry_log_file, telemetry_log_sample_count


def register_api_routes(app) -> None:
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

    @app.route("/api/telemetry", methods=["GET"])
    def api_telemetry():
        telemetry = load_heater_telemetry_safe()
        if telemetry.get("error"):
            return jsonify({"error": telemetry["error"]}), 502
        return jsonify(telemetry)

    @app.route("/api/command", methods=["POST"])
    def api_command():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object body"}), 400
        if "value" not in payload:
            return jsonify({"error": "Field 'value' is required"}), 400

        command_type = str(payload.get("type") or "").strip().upper()
        if command_type and command_type != "KILL":
            return jsonify({"error": "Only command type 'KILL' is supported"}), 400

        try:
            result = send_heater_command(payload.get("value"))
        except Exception as exc:
            app.logger.exception("Failed to send heater command")
            return jsonify({"error": str(exc)}), 502
        return jsonify(result)

    @app.route("/api/system-status/telemetry-log", methods=["GET"])
    def api_telemetry_log_meta():
        return jsonify(
            {
                "ok": True,
                "sample_count": telemetry_log_sample_count(),
                "download_url": "/api/system-status/telemetry-log.csv",
            }
        )

    @app.route("/api/system-status/telemetry-log.csv", methods=["GET"])
    def api_telemetry_log_csv():
        with TELEMETRY_LOG_LOCK:
            ensure_telemetry_log_file()
        return send_file(
            TELEMETRY_LOG_PATH,
            mimetype="text/csv",
            as_attachment=True,
            download_name=TELEMETRY_LOG_PATH.name,
        )

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
