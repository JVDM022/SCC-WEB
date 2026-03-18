from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import jsonify, redirect, request, send_file
from werkzeug.utils import secure_filename

from config import TELEMETRY_LOG_LOCK, TELEMETRY_LOG_PATH
from db import fetch_one
from services.azure_relay import load_heater_telemetry_safe, send_heater_command
from services.blob_export import (
    download_documentation_blob,
    export_broadcast_csv_to_blob,
    upload_documentation_file_to_blob,
)
from services.dashboard import (
    delete_entity,
    entity_or_404,
    fetch_all,
    fetch_current_system_status,
    fetch_development_progress,
    fetch_project,
    insert_entity,
    upsert_current_system_status,
    update_entity,
    update_progress,
    update_project,
)
from services.iot_hub import (
    get_device_twin,
    get_job,
    iot_hub_status_summary,
    patch_device_desired_properties,
    patch_device_ota_target,
    schedule_ota_rollout,
)
from services.telemetry import ensure_telemetry_log_file, telemetry_log_sample_count


def register_api_routes(app) -> None:
    def iot_hub_error_response(exc: Exception):
        message = str(exc)
        lowered = message.lower()
        if "required" in lowered or "must be" in lowered:
            return jsonify({"error": message}), 400
        if "not configured" in lowered or "not installed" in lowered:
            return jsonify({"error": message}), 503
        return jsonify({"error": message}), 502

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

    @app.route("/api/iot-hub/status", methods=["GET"])
    def api_iot_hub_status():
        return jsonify(iot_hub_status_summary())

    @app.route("/api/iot-hub/device/twin", defaults={"device_id": None}, methods=["GET"])
    @app.route("/api/iot-hub/devices/<device_id>/twin", methods=["GET"])
    def api_iot_hub_device_twin(device_id: str | None):
        try:
            return jsonify(get_device_twin(device_id))
        except Exception as exc:
            app.logger.exception("Failed to fetch IoT Hub device twin")
            return iot_hub_error_response(exc)

    @app.route("/api/iot-hub/device/desired", defaults={"device_id": None}, methods=["POST"])
    @app.route("/api/iot-hub/devices/<device_id>/desired", methods=["POST"])
    def api_iot_hub_patch_desired(device_id: str | None):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object body"}), 400

        desired_patch = payload.get("desired")
        if desired_patch is None:
            desired_patch = payload

        try:
            return jsonify(patch_device_desired_properties(desired_patch, device_id=device_id))
        except Exception as exc:
            app.logger.exception("Failed to patch IoT Hub desired properties")
            return iot_hub_error_response(exc)

    @app.route("/api/iot-hub/device/ota", defaults={"device_id": None}, methods=["POST"])
    @app.route("/api/iot-hub/devices/<device_id>/ota", methods=["POST"])
    def api_iot_hub_patch_ota(device_id: str | None):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object body"}), 400

        ota_patch = payload.get("ota")
        if ota_patch is None:
            ota_patch = payload

        try:
            return jsonify(patch_device_ota_target(ota_patch, device_id=device_id))
        except Exception as exc:
            app.logger.exception("Failed to patch IoT Hub OTA desired state")
            return iot_hub_error_response(exc)

    @app.route("/api/iot-hub/rollouts/ota", methods=["POST"])
    def api_iot_hub_rollout_ota():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object body"}), 400

        ota_patch = payload.get("ota")
        if ota_patch is None:
            ota_patch = payload.get("desired")
        query_condition = payload.get("query_condition") or payload.get("queryCondition")
        job_id = payload.get("job_id") or payload.get("jobId")
        start_time = payload.get("start_time") or payload.get("startTime")
        max_execution_time = (
            payload.get("max_execution_time_in_seconds")
            or payload.get("maxExecutionTimeInSeconds")
        )

        try:
            return jsonify(
                schedule_ota_rollout(
                    ota_patch=ota_patch,
                    query_condition=str(query_condition or ""),
                    job_id=str(job_id or "") or None,
                    start_time=str(start_time or "") or None,
                    max_execution_time_in_seconds=max_execution_time,
                )
            )
        except Exception as exc:
            app.logger.exception("Failed to schedule IoT Hub OTA rollout job")
            return iot_hub_error_response(exc)

    @app.route("/api/iot-hub/jobs/<job_id>", methods=["GET"])
    def api_iot_hub_job(job_id: str):
        try:
            return jsonify(get_job(job_id))
        except Exception as exc:
            app.logger.exception("Failed to fetch IoT Hub job")
            return iot_hub_error_response(exc)

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

    @app.route("/api/documentation/blob-export", methods=["POST"])
    def api_documentation_blob_export():
        try:
            result = export_broadcast_csv_to_blob()
        except Exception as exc:
            app.logger.exception("Failed to export broadcast CSV to blob")
            return jsonify({"error": str(exc)}), 502
        return jsonify(result)

    @app.route("/api/documentation/blob-upload", methods=["POST"])
    def api_documentation_blob_upload():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "Upload a file first"}), 400

        filename = secure_filename(upload.filename) or "upload.bin"
        title = str(request.form.get("title") or Path(filename).stem or "Blob Upload").strip()
        owner = str(request.form.get("owner") or "User").strip() or "User"
        data = upload.read()
        if not data:
            return jsonify({"error": "Uploaded file is empty"}), 400

        try:
            result = upload_documentation_file_to_blob(
                filename=filename,
                data=data,
                content_type=str(upload.mimetype or "application/octet-stream"),
                title=title,
                owner=owner,
            )
        except Exception as exc:
            app.logger.exception("Failed to upload documentation blob")
            return jsonify({"error": str(exc)}), 502
        return jsonify(result)

    @app.route("/api/documentation/<int:item_id>/blob", methods=["GET"])
    def api_documentation_blob_download(item_id: int):
        try:
            result = download_documentation_blob(item_id)
        except Exception as exc:
            app.logger.exception("Failed to download documentation blob")
            return jsonify({"error": str(exc)}), 404

        if result.get("mode") == "redirect":
            return redirect(str(result["url"]))

        return send_file(
            BytesIO(result["data"]),
            mimetype=str(result.get("content_type") or "application/octet-stream"),
            as_attachment=True,
            download_name=str(result.get("download_name") or "blob"),
        )

    @app.route("/api/system-status/current", methods=["GET", "POST", "PUT"])
    def api_current_system_status():
        if request.method == "GET":
            return jsonify(fetch_current_system_status())

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object body"}), 400

        return jsonify(upsert_current_system_status(payload))

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
