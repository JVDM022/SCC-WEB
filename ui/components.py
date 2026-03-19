from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List

from flask import current_app, has_app_context
from reactpy import component, event, hooks, html

from config import DOC_TYPE_FILTER_ALL, ENTITY_DEFS, PHASES, PHASE_TO_PERCENT
from services.heater_telemetry_source import load_heater_telemetry_safe, send_heater_command
from services.blob_export import export_broadcast_csv_to_blob
from services.dashboard import (
    bom_status_class,
    default_values_for,
    delete_entity,
    insert_entity,
    load_dashboard_data_safe,
    normalize_doc_type_key,
    normalize_phase,
    risk_status_class,
    update_entity,
    update_progress,
    update_project,
)
from services.iot_hub import get_device_twin, iot_hub_status_summary, patch_device_ota_target
from services.iot_hub_telemetry import iot_hub_telemetry_status_summary
from services.pacific_time import format_pacific_timestamp
from services.telemetry import coerce_float, telemetry_log_sample_count
from ui.styles import GLASS_CSS


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


BLOB_UPLOAD_SCRIPT = """
(function () {
  function getDropZone() {
    return document.getElementById("blob-upload-zone");
  }

  function getInput() {
    return document.getElementById("blob-upload-input");
  }

  function setLabel(text) {
    var label = document.querySelector("#blob-upload-zone [data-upload-label]");
    if (label) {
      label.textContent = text;
    }
  }

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) {
      return;
    }

    var file = fileList[0];
    var dropZone = getDropZone();
    if (!dropZone) {
      return;
    }

    var formData = new FormData();
    formData.append("file", file, file.name);
    dropZone.dataset.uploadState = "uploading";
    setLabel("Uploading " + file.name + "...");

    try {
      var response = await fetch("/api/documentation/blob-upload", {
        method: "POST",
        body: formData
      });
      var body = {};
      try {
        body = await response.json();
      } catch (error) {}

      if (!response.ok) {
        throw new Error(body.error || "Upload failed");
      }

      dropZone.dataset.uploadState = "done";
      setLabel("Upload complete. Refreshing...");
      window.location.reload();
    } catch (error) {
      dropZone.dataset.uploadState = "error";
      setLabel(error && error.message ? error.message : "Upload failed");
    }
  }

  document.addEventListener("click", function (event) {
    var dropZone = event.target.closest("#blob-upload-zone");
    if (!dropZone) {
      return;
    }
    var input = getInput();
    if (input) {
      input.click();
    }
  });

  document.addEventListener("change", function (event) {
    if (!event.target || event.target.id !== "blob-upload-input") {
      return;
    }
    uploadFiles(event.target.files);
    event.target.value = "";
  });

  document.addEventListener("dragover", function (event) {
    var dropZone = event.target.closest("#blob-upload-zone");
    if (!dropZone) {
      return;
    }
    event.preventDefault();
    dropZone.classList.add("dragover");
  });

  document.addEventListener("dragleave", function (event) {
    var dropZone = event.target.closest("#blob-upload-zone");
    if (!dropZone) {
      return;
    }
    if (event.relatedTarget && dropZone.contains(event.relatedTarget)) {
      return;
    }
    dropZone.classList.remove("dragover");
  });

  document.addEventListener("drop", function (event) {
    var dropZone = event.target.closest("#blob-upload-zone");
    if (!dropZone) {
      return;
    }
    event.preventDefault();
    dropZone.classList.remove("dragover");
    uploadFiles(event.dataTransfer && event.dataTransfer.files);
  });
})();
"""

TELEMETRY_POLL_SECONDS = 3.0


APP_HEAD = (
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
    {
        "tagName": "script",
        "children": [BLOB_UPLOAD_SCRIPT],
    },
)


def parse_online_state(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "online"}:
        return True
    if text in {"0", "false", "no", "off", "offline"}:
        return False
    return None


def derive_system_on(telemetry: Dict[str, Any]) -> bool | None:
    explicit = parse_online_state(telemetry.get("system_on"))
    if explicit is not None:
        return explicit

    kill_state = telemetry.get("kill_state")
    if kill_state is True:
        return False
    if kill_state is False:
        return True

    if telemetry.get("heater_on") is not None or telemetry.get("temperature") is not None:
        return True
    return None


def format_uptime(seconds: Any) -> str:
    try:
        total_seconds = int(seconds)
    except (TypeError, ValueError):
        return ""

    if total_seconds < 0:
        return ""

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def documentation_status_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"done", "complete", "completed"} or text.startswith("synced"):
        return "pill-success"
    if text in {"in progress", "in-progress", "inprogress"}:
        return "pill-info"
    return "pill-muted"


def empty_telemetry_state() -> Dict[str, Any]:
    return {
        "temperature": None,
        "heater_on": None,
        "kill_state": None,
        "system_on": None,
        "uptime_seconds": None,
        "fetched_at": "",
        "error": "",
    }


def normalize_telemetry_state(telemetry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(telemetry or {})
    normalized["temperature"] = coerce_float(normalized.get("temperature"))
    return normalized


def telemetry_has_signal(telemetry: Dict[str, Any]) -> bool:
    return any(
        telemetry.get(key) is not None
        for key in ("temperature", "heater_on", "kill_state", "system_on", "uptime_seconds")
    )


def merged_telemetry_state(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    if telemetry_has_signal(current):
        return current
    if current.get("error") and telemetry_has_signal(previous):
        merged = dict(previous)
        merged["error"] = str(current.get("error") or "")
        return merged
    return current


def empty_iot_hub_state() -> Dict[str, Any]:
    return {
        "configured": False,
        "default_device_id": "",
        "sdk_available": True,
        "transport": "rest",
        "sdk_error": "",
        "telemetry": {},
        "twin": None,
        "error": "",
    }


def ota_form_defaults(twin: Dict[str, Any] | None = None) -> Dict[str, str]:
    desired_ota = ((twin or {}).get("ota") or {}).get("desired") or {}
    size = desired_ota.get("size")
    return {
        "target_version": str(desired_ota.get("targetVersion") or ""),
        "artifact_url": str(desired_ota.get("artifactUrl") or ""),
        "sha256": str(desired_ota.get("sha256") or ""),
        "size": "" if size in (None, "") else str(size),
        "rollout_id": str(desired_ota.get("rolloutId") or ""),
        "action": str(desired_ota.get("action") or "download_and_apply"),
    }


def load_iot_hub_snapshot_safe() -> Dict[str, Any]:
    snapshot = empty_iot_hub_state()
    try:
        status = iot_hub_status_summary()
    except Exception as exc:
        snapshot["error"] = str(exc)
        return snapshot

    snapshot.update(status)
    snapshot["telemetry"] = iot_hub_telemetry_status_summary(start_listener=True)
    if not status.get("configured"):
        snapshot["error"] = str(status.get("sdk_error") or "")
        return snapshot

    try:
        snapshot["twin"] = get_device_twin(status.get("default_device_id") or None)
    except Exception as exc:
        snapshot["error"] = str(exc)
    return snapshot


def format_iot_timestamp(value: Any) -> str:
    return format_pacific_timestamp(value, "--")


def display_value(value: Any, fallback: str = "--") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def iot_pill_class(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "enabled", "success", "succeeded", "complete", "completed", "listening"}:
        return "pill-success"
    if normalized in {"downloading", "downloaded", "rebooting", "pending_verify", "running", "waiting"}:
        return "pill-info"
    if normalized in {"failed", "error", "disabled", "disconnected"}:
        return "pill-danger"
    if normalized in {"rolled_back", "warning"}:
        return "pill-warning"
    return "pill-muted"


@component
def App():
    data, set_data = hooks.use_state(load_dashboard_data_safe)
    telemetry, set_telemetry = hooks.use_state(empty_telemetry_state)
    telemetry_samples, set_telemetry_samples = hooks.use_state(lambda: 0)
    iot_hub, set_iot_hub = hooks.use_state(load_iot_hub_snapshot_safe)
    ota_form_values, set_ota_form_values = hooks.use_state(
        lambda: ota_form_defaults(iot_hub.get("twin"))
    )
    modal_state, set_modal_state = hooks.use_state({
        "open": False,
        "type": None,
        "entity": None,
        "item_id": None,
        "item_data": None,
    })
    form_values, set_form_values = hooks.use_state({})
    form_dirty, set_form_dirty = hooks.use_state(False)
    is_busy, set_is_busy = hooks.use_state(False)
    control_feedback, set_control_feedback = hooks.use_state("")
    doc_type_filter, set_doc_type_filter = hooks.use_state(DOC_TYPE_FILTER_ALL)
    busy_ref = hooks.use_ref(False)
    field_event_ts_ref = hooks.use_ref({})
    submit_intent_ref = hooks.use_ref(False)

    def get_field_value(name: str, default: Any = "") -> Any:
        return form_values.get(name, default)

    def refresh_dashboard() -> None:
        set_data(load_dashboard_data_safe())

    def read_telemetry_snapshot() -> tuple[Dict[str, Any], int]:
        next_telemetry = normalize_telemetry_state(load_heater_telemetry_safe())
        return next_telemetry, telemetry_log_sample_count()

    def apply_telemetry_snapshot(next_telemetry: Dict[str, Any], sample_count: int) -> None:
        set_telemetry(lambda previous: merged_telemetry_state(previous, next_telemetry))
        set_telemetry_samples(sample_count)

    def load_telemetry_snapshot() -> None:
        next_telemetry, sample_count = read_telemetry_snapshot()
        apply_telemetry_snapshot(next_telemetry, sample_count)

    async def poll_telemetry_effect():
        while True:
            next_telemetry, sample_count = await asyncio.to_thread(read_telemetry_snapshot)
            apply_telemetry_snapshot(next_telemetry, sample_count)
            await asyncio.sleep(TELEMETRY_POLL_SECONDS)

    hooks.use_effect(poll_telemetry_effect, [])

    def load_iot_hub_snapshot(sync_form: bool = False) -> Dict[str, Any]:
        next_snapshot = load_iot_hub_snapshot_safe()
        set_iot_hub(next_snapshot)
        if sync_form:
            set_ota_form_values(ota_form_defaults(next_snapshot.get("twin")))
        return next_snapshot

    def set_field(name: str, value: Any) -> None:
        if busy_ref.current:
            return
        set_form_values(lambda prev: {**prev, name: value})
        if modal_state.get("open"):
            set_form_dirty(True)

    def set_field_from_event(name: str, event_data: Dict[str, Any]) -> None:
        if busy_ref.current:
            return

        ts_raw = event_data.get("timeStamp")
        if ts_raw is None:
            ts_raw = event_data.get("timestamp")
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

        target = event_data.get("target", {})
        set_field(name, target.get("value", ""))

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

        modal_type = str(modal_state.get("type") or "")
        entity = ""
        if modal_type == "edit_project":
            entity = "project"
            fields = ENTITY_DEFS["project"]["fields"]
        elif modal_type == "edit_progress":
            fields = [{"name": "percent"}, {"name": "phase"}]
        elif modal_type in {"new_entity", "edit_entity"}:
            entity = str(modal_state.get("entity") or "")
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

    def close_modal(force: bool = False) -> None:
        if busy_ref.current:
            return
        if modal_state.get("open") and form_dirty and not force:
            set_modal_state(lambda prev: {**prev, "confirm_close": True})
            return

        submit_intent_ref.current = False
        set_modal_state({"open": False, "type": None})
        set_form_values({})
        set_form_dirty(False)

    def confirm_close() -> None:
        submit_intent_ref.current = False
        set_modal_state({"open": False, "type": None})
        set_form_values({})
        set_form_dirty(False)

    def dismiss_close_warning() -> None:
        set_modal_state(lambda prev: {**prev, "confirm_close": False})

    def run_mutation(action: Callable[[], None], refresh_after: bool = True) -> None:
        if busy_ref.current:
            return
        busy_ref.current = True
        set_is_busy(True)
        try:
            action()
            if refresh_after:
                refresh_dashboard()
        finally:
            busy_ref.current = False
            set_is_busy(False)

    def request_submit() -> None:
        if busy_ref.current:
            return
        submit_intent_ref.current = True

    @event(prevent_default=True)
    def handle_submit(event_data: Dict[str, Any]) -> None:
        if not modal_state.get("open") or busy_ref.current:
            return
        if not submit_intent_ref.current:
            return

        submit_intent_ref.current = False
        modal_type = str(modal_state.get("type") or "")
        values = submitted_form_values(event_data)

        def do_save() -> None:
            if modal_type == "edit_project":
                update_project(values)
                set_control_feedback("Project updated")
            elif modal_type == "edit_progress":
                update_progress(values)
                set_control_feedback("Progress updated")
            elif modal_type in {"new_entity", "edit_entity"}:
                entity = str(modal_state.get("entity") or "")
                item_id = int(modal_state.get("item_id") or 0)
                if modal_type == "edit_entity" and item_id:
                    update_entity(entity, item_id, values)
                    set_control_feedback(f"{ENTITY_DEFS[entity]['label']} updated")
                else:
                    insert_entity(entity, values)
                    set_control_feedback(f"{ENTITY_DEFS[entity]['label']} added")

        run_mutation(do_save)
        close_modal(force=True)

    def open_project_modal() -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_form_dirty(False)
        fields = ENTITY_DEFS["project"]["fields"]
        initial = {field["name"]: data["project"].get(field["name"], "") for field in fields}
        set_form_values(initial)
        set_modal_state({"open": True, "type": "edit_project", "confirm_close": False})

    def open_progress_modal(selected_phase: str | None = None) -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_form_dirty(False)
        progress_row = data.get("progress_row", {})
        initial = {
            "phase": normalize_phase(progress_row.get("phase")) or "Concept",
            "percent": progress_row.get("percent") or 0,
        }
        normalized_selected_phase = normalize_phase(selected_phase)
        if normalized_selected_phase:
            initial["phase"] = normalized_selected_phase
            initial["percent"] = PHASE_TO_PERCENT.get(normalized_selected_phase, initial["percent"])
        set_form_values(initial)
        set_modal_state({"open": True, "type": "edit_progress", "confirm_close": False})

    def open_entity_modal(entity: str, mode: str, item: Dict[str, Any] | None = None) -> None:
        if busy_ref.current:
            return
        field_event_ts_ref.current = {}
        submit_intent_ref.current = False
        set_form_dirty(False)
        fields = ENTITY_DEFS[entity]["fields"]
        if mode == "new":
            initial = default_values_for(entity, fields)
        else:
            item = item or {}
            initial = {field["name"]: item.get(field["name"], "") for field in fields}
        set_form_values(initial)
        set_modal_state(
            {
                "open": True,
                "type": "new_entity" if mode == "new" else "edit_entity",
                "entity": entity,
                "item_id": item.get("id") if item else None,
                "item_data": item,
                "confirm_close": False,
            }
        )

    def open_delete_modal(entity: str, item_id: int | None) -> None:
        if busy_ref.current:
            return
        submit_intent_ref.current = False
        set_form_dirty(False)
        set_modal_state(
            {
                "open": True,
                "type": "delete_confirm",
                "entity": entity,
                "item_id": item_id,
                "confirm_close": False,
            }
        )

    def handle_delete_entity() -> None:
        def do_delete() -> None:
            entity = modal_state.get("entity")
            item_id = modal_state.get("item_id")
            delete_entity(entity, item_id)
            set_control_feedback(f"{ENTITY_DEFS[entity]['label']} deleted")
        run_mutation(do_delete)
        submit_intent_ref.current = False
        set_form_values({})
        set_form_dirty(False)
        set_modal_state({"open": False, "type": None})

    def send_heater_command_action(kill_value: int) -> None:
        def do_send() -> None:
            set_control_feedback("")
            try:
                send_heater_command(kill_value)
                set_control_feedback("Shutdown command sent." if kill_value == 1 else "Resume command sent.")
            except Exception as exc:
                _logger().exception("Failed to send heater command")
                set_control_feedback(f"Command failed: {exc}")
            load_telemetry_snapshot()
        run_mutation(do_send, refresh_after=False)

    def refresh_telemetry_data() -> None:
        def do_refresh() -> None:
            set_control_feedback("")
            load_telemetry_snapshot()
        run_mutation(do_refresh, refresh_after=False)

    def refresh_iot_hub_data(sync_form: bool = False) -> None:
        def do_refresh() -> None:
            set_control_feedback("")
            next_snapshot = load_iot_hub_snapshot(sync_form=sync_form)
            if next_snapshot.get("error") or next_snapshot.get("sdk_error"):
                set_control_feedback(f"IoT Hub refresh failed: {next_snapshot.get('error') or next_snapshot.get('sdk_error')}")
            elif next_snapshot.get("configured"):
                set_control_feedback("IoT Hub twin refreshed.")
        run_mutation(do_refresh, refresh_after=False)

    def set_ota_field(name: str, event_data: Dict[str, Any]) -> None:
        if busy_ref.current:
            return
        target = event_data.get("target", {})
        value = target.get("value", "")
        set_ota_form_values(lambda previous: {**previous, name: "" if value is None else str(value)})

    def push_ota_target_action() -> None:
        def do_push() -> None:
            set_control_feedback("")
            try:
                target_version = str(ota_form_values.get("target_version") or "").strip()
                artifact_url = str(ota_form_values.get("artifact_url") or "").strip()
                action = str(ota_form_values.get("action") or "download_and_apply").strip() or "download_and_apply"

                if not target_version:
                    raise RuntimeError("Target version is required")
                if not artifact_url:
                    raise RuntimeError("Artifact URL is required")

                ota_patch: Dict[str, Any] = {
                    "targetVersion": target_version,
                    "artifactUrl": artifact_url,
                    "action": action,
                }

                sha256 = str(ota_form_values.get("sha256") or "").strip()
                if sha256:
                    ota_patch["sha256"] = sha256

                size_raw = str(ota_form_values.get("size") or "").strip()
                if size_raw:
                    try:
                        ota_patch["size"] = int(size_raw)
                    except ValueError as exc:
                        raise RuntimeError("Size must be a whole number of bytes") from exc

                rollout_id = str(ota_form_values.get("rollout_id") or "").strip()
                if rollout_id:
                    ota_patch["rolloutId"] = rollout_id

                twin = patch_device_ota_target(ota_patch)
                set_iot_hub(lambda previous: {**previous, "twin": twin, "error": ""})
                set_ota_form_values(ota_form_defaults(twin))
                set_control_feedback(f"OTA target {target_version} queued in IoT Hub.")
            except Exception as exc:
                _logger().exception("Failed to queue OTA target")
                set_control_feedback(f"OTA failed: {exc}")

        run_mutation(do_push, refresh_after=False)

    def export_broadcast_csv_action() -> None:
        def do_export() -> None:
            set_control_feedback("")
            try:
                result = export_broadcast_csv_to_blob()
            except Exception as exc:
                _logger().exception("Failed to export telemetry log CSV to blob")
                set_control_feedback(f"Blob export failed: {exc}")
                return

            sample_count = int(result.get("row_count") or 0)
            blob_name = str(result.get("blob_name") or "blob")
            set_control_feedback(f"Telemetry log CSV exported: {sample_count} samples to {blob_name}")

        run_mutation(do_export)

    def render_button(label: str, **kwargs) -> Dict:
        class_name = kwargs.pop("class", kwargs.pop("class_", "btn glass-btn"))
        return html.button(
            {
                "class": class_name,
                "type": kwargs.pop("type", "button"),
                "disabled": is_busy or kwargs.pop("disabled", False),
                **kwargs,
            },
            label,
        )

    def render_input_field(name: str, label: str, input_type: str = "text", **extra_attrs) -> Dict:
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.input(
                {
                    "name": name,
                    "type": input_type,
                    "class": "input glass-input",
                    "default_value": get_field_value(name, ""),
                    "disabled": is_busy,
                    "on_change": lambda event_data: set_field_from_event(name, event_data),
                    "on_blur": lambda event_data: set_field_from_event(name, event_data),
                    **{key: value for key, value in extra_attrs.items() if value is not None},
                }
            ),
        )

    def render_textarea_field(name: str, label: str, **extra_attrs) -> Dict:
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.textarea(
                {
                    "name": name,
                    "class": "textarea glass-input",
                    "default_value": get_field_value(name, ""),
                    "disabled": is_busy,
                    "on_change": lambda event_data: set_field_from_event(name, event_data),
                    "on_blur": lambda event_data: set_field_from_event(name, event_data),
                    **{key: value for key, value in extra_attrs.items() if value is not None},
                }
            ),
        )

    def render_segmented_field(name: str, label: str, options: List[Dict[str, str]]) -> Dict:
        current_val = get_field_value(name, options[0]["value"] if options else "")
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.div(
                {"class": "segmented"},
                *[
                    html.button(
                        {
                            "type": "button",
                            "class": f"seg-btn {'active' if current_val == opt['value'] else ''}",
                            "disabled": is_busy,
                            "on_click": lambda e, val=opt["value"]: set_field(name, val),
                        },
                        opt["label"],
                    )
                    for opt in options
                ],
            ),
        )

    def render_stepper_field(name: str, label: str, min_val: int = 0, max_val: int = 100, step: int = 5) -> Dict:
        try:
            current = int(get_field_value(name, min_val))
        except (TypeError, ValueError):
            current = min_val
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.div(
                {"class": "stepper"},
                render_button(
                    "−",
                    class_="stepper-btn stepper-minus",
                    disabled=current <= min_val,
                    on_click=lambda e: set_field(name, max(min_val, current - step)),
                ),
                html.span({"class": "stepper-value"}, f"{current}%"),
                render_button(
                    "+",
                    class_="stepper-btn stepper-plus",
                    disabled=current >= max_val,
                    on_click=lambda e: set_field(name, min(max_val, current + step)),
                ),
            ),
        )

    def render_generic_field(entity: str, field: Dict[str, Any]) -> Dict:
        name = field["name"]
        label = field["label"]
        if entity == "system_status" and name == "is_online":
            return render_segmented_field(name, label, [
                {"label": "Online", "value": "1"},
                {"label": "Offline", "value": "0"},
            ])
        elif entity == "tasks" and name == "priority":
            return render_segmented_field(name, label, [
                {"label": "High", "value": "High"},
                {"label": "Medium", "value": "Medium"},
                {"label": "Low", "value": "Low"},
            ])
        elif entity == "tasks" and name == "status":
            return render_segmented_field(name, label, [
                {"label": "Not started", "value": "Not started"},
                {"label": "In progress", "value": "In progress"},
                {"label": "Done", "value": "Done"},
            ])
        elif entity == "documentation" and name == "status":
            return render_segmented_field(name, label, [
                {"label": "Not started", "value": "Not started"},
                {"label": "In progress", "value": "In progress"},
                {"label": "Done", "value": "Done"},
            ])
        elif entity == "risks" and name == "status":
            return render_segmented_field(name, label, [
                {"label": "Ongoing", "value": "Ongoing"},
                {"label": "Resolved", "value": "Resolved"},
            ])
        elif entity == "bom" and name == "status":
            return render_segmented_field(name, label, [
                {"label": "Not yet purchased", "value": "Not yet purchased"},
                {"label": "Purchased", "value": "Purchased"},
            ])
        elif field.get("widget") == "textarea":
            return render_textarea_field(name, label)
        else:
            return render_input_field(
                name,
                label,
                field.get("input_type", "text"),
                step=field.get("step"),
            )

    def render_project_modal() -> Dict:
        fields = ENTITY_DEFS["project"]["fields"]
        return html.form(
            {"class": "form", "on_submit": handle_submit},
            html.h3({"class": "modal-subtitle"}, "Edit Project"),
            *[render_generic_field("project", f) for f in fields],
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal()),
                render_button(
                    "Save",
                    class_="btn glass-btn primary",
                    type="submit",
                    on_click=lambda e: request_submit(),
                ),
            ),
        )

    def render_progress_modal() -> Dict:
        return html.form(
            {"class": "form", "on_submit": handle_submit},
            render_stepper_field("percent", "Progress", 0, 100, 5),
            render_segmented_field("phase", "Phase", [
                {"label": "Concept", "value": "Concept"},
                {"label": "Developing", "value": "Developing"},
                {"label": "Prototype", "value": "Prototype"},
                {"label": "Testing", "value": "Testing"},
                {"label": "Complete", "value": "Complete"},
            ]),
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal()),
                render_button(
                    "Save",
                    class_="btn glass-btn primary",
                    type="submit",
                    on_click=lambda e: request_submit(),
                ),
            ),
        )

    def render_entity_modal() -> Dict:
        entity = modal_state.get("entity")
        entity_def = ENTITY_DEFS.get(entity, {})
        fields = entity_def.get("fields", [])
        is_edit = bool(modal_state.get("item_id"))
        title = f"{'Edit' if is_edit else 'Add'} {entity_def.get('label', entity)}"
        return html.form(
            {"class": "form", "on_submit": handle_submit},
            html.h3({"class": "modal-subtitle"}, title),
            *[render_generic_field(entity, f) for f in fields],
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal()),
                render_button(
                    "Save",
                    class_="btn glass-btn primary",
                    type="submit",
                    on_click=lambda e: request_submit(),
                ),
            ),
        )

    def render_delete_confirm_modal() -> Dict:
        entity = modal_state.get("entity")
        entity_def = ENTITY_DEFS.get(entity, {})
        return html.div(
            {"class": "confirm-dialog"},
            html.h3("Delete item?"),
            html.p(f"This will permanently delete the {entity_def.get('label', entity).lower()}."),
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal(force=True)),
                render_button("Delete", class_="btn glass-btn danger", on_click=lambda e: handle_delete_entity()),
            ),
        )

    def render_modal() -> Dict | None:
        if not modal_state.get("open"):
            return None

        modal_type = modal_state.get("type")
        if modal_state.get("confirm_close"):
            body = html.div(
                {"class": "confirm-dialog"},
                html.p("You have unsaved changes. Discard them?"),
                html.div(
                    {"class": "form-actions"},
                    render_button("Keep editing", class_="btn glass-btn ghost", on_click=lambda e: dismiss_close_warning()),
                    render_button("Discard", class_="btn glass-btn primary", on_click=lambda e: confirm_close()),
                ),
            )
        elif modal_type == "edit_project":
            body = render_project_modal()
        elif modal_type == "edit_progress":
            body = render_progress_modal()
        elif modal_type in ["new_entity", "edit_entity"]:
            body = render_entity_modal()
        elif modal_type == "delete_confirm":
            body = render_delete_confirm_modal()
        else:
            return None
        
        return html.div(
            {"class": "modal"},
            html.div(
                {"class": "modal-card glass-surface glass-card"},
                html.div(
                    {"class": "modal-header"},
                    html.button(
                        {
                            "class": "btn glass-btn ghost modal-close",
                            "type": "button",
                            "disabled": is_busy,
                            "on_click": lambda e: close_modal(),
                        },
                        "✕",
                    ),
                ),
                body,
            ),
        )

    # Telemetry and status display
    def render_telemetry_card() -> Dict:
        temp = coerce_float(telemetry.get("temperature"))
        temp_label = f"{float(temp):.1f}°C" if temp is not None else "--"
        
        heater_on = telemetry.get("heater_on")
        heater_label = "ON" if heater_on is True else ("OFF" if heater_on is False else "Unknown")
        heater_class = "pill-warning" if heater_on is True else ("pill-muted" if heater_on is False else "pill-muted")
        
        kill_state = telemetry.get("kill_state")
        kill_label = "SHUT DOWN" if kill_state is True else ("RUNNING" if kill_state is False else "Unknown")
        kill_class = "pill-danger" if kill_state is True else ("pill-success" if kill_state is False else "pill-muted")
        
        telemetry_system_on = derive_system_on(telemetry)

        # Fall back to the editable database value only when telemetry has no system signal.
        system_status_section = next((s for s in data.get("sections", []) if s.get("key") == "system_status"), None)
        system_status_row = system_status_section.get("rows", [{}])[0] if system_status_section and system_status_section.get("rows") else {}
        fallback_system_on = parse_online_state(system_status_row.get("is_online"))
        system_on = telemetry_system_on if telemetry_system_on is not None else fallback_system_on
        system_online_label = "ON" if system_on is True else ("OFF" if system_on is False else "Unknown")
        system_online_class = "pill-success" if system_on is True else ("pill-danger" if system_on is False else "pill-muted")
        uptime_seconds = telemetry.get("uptime_seconds")
        uptime_label = format_uptime(uptime_seconds) if uptime_seconds is not None else "--"
        reason = "" if telemetry_system_on is not None else system_status_row.get("reason", "")
        return html.section(
            {"class": "card glass-surface glass-card"},
            html.div(
                {"class": "section-header"},
                html.h2("System & Heater Control"),
                html.p({"class": "meta"}, f"Last telemetry: {telemetry.get('fetched_at') or 'Never'}"),
            ),
            (html.p(
                {"class": "meta", "style": {"color": "#b42318", "marginBottom": "0.75rem"}},
                str(telemetry.get("error") or ""),
            ) if telemetry.get("error") else None),
            html.div(
                {"class": "telemetry-grid"},
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Temperature"),
                    html.span({"class": "stat-value"}, temp_label),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Heater"),
                    html.span({"class": f"pill {heater_class}"}, heater_label),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Shutdown State"),
                    html.span({"class": f"pill {kill_class}"}, kill_label),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "System"),
                    html.span({"class": f"pill {system_online_class}"}, system_online_label),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Uptime"),
                    html.span({"class": "stat-value"}, uptime_label),
                ),
            ),
            (html.div(
                {"class": "status-info glass-surface glass-panel", "style": {"padding": "1rem", "margin": "1rem 0"}},
                html.p({"class": "meta"}, f"Reason: {reason}"),
            ) if reason else None),
            html.div(
                {"class": "button-group"},
                render_button("Refresh", class_="btn glass-btn", on_click=lambda e: refresh_telemetry_data()),
                render_button("Shut Off", class_="btn glass-btn danger", on_click=lambda e: send_heater_command_action(1)),
                render_button("Resume", class_="btn glass-btn", on_click=lambda e: send_heater_command_action(0)),
            ),
            html.p({"class": "meta"}, f"Logged: {telemetry_samples} samples"),
        )

    def render_ota_field(name: str, label: str, placeholder: str = "", input_type: str = "text") -> Dict:
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.input(
                {
                    "type": input_type,
                    "class": "input glass-input",
                    "value": str(ota_form_values.get(name) or ""),
                    "placeholder": placeholder,
                    "disabled": is_busy or not iot_hub.get("configured"),
                    "on_change": lambda event_data, field_name=name: set_ota_field(field_name, event_data),
                }
            ),
        )

    def render_iot_hub_card() -> Dict:
        twin = iot_hub.get("twin") or {}
        telemetry_status = iot_hub.get("telemetry") or {}
        desired_ota = ((twin.get("ota") or {}).get("desired") or {})
        reported_ota = ((twin.get("ota") or {}).get("reported") or {})

        device_id = display_value(twin.get("device_id") or iot_hub.get("default_device_id"))
        connection_state = display_value(twin.get("connection_state"), "Unknown")
        listener_state = "Listening" if telemetry_status.get("listening") else "Waiting"
        device_status = display_value(twin.get("status"), "Unknown")
        current_version = display_value(reported_ota.get("currentVersion"))
        target_version = display_value(desired_ota.get("targetVersion") or reported_ota.get("targetVersion"))
        ota_state = display_value(reported_ota.get("state"), "Pending firmware support")
        action_value = display_value(desired_ota.get("action") or reported_ota.get("action"), "download_and_apply")
        rollout_id = display_value(desired_ota.get("rolloutId") or reported_ota.get("rolloutId"))
        last_activity = format_iot_timestamp(twin.get("last_activity_time"))
        last_attempt = format_iot_timestamp(reported_ota.get("lastAttemptAt"))
        last_event = format_iot_timestamp(telemetry_status.get("last_event_at"))
        artifact_url = str(desired_ota.get("artifactUrl") or "").strip()
        sha256 = display_value(desired_ota.get("sha256"))
        size_label = display_value(desired_ota.get("size"))

        return html.section(
            {"class": "card glass-surface glass-card"},
            html.div(
                {"class": "section-header"},
                html.div(
                    {},
                    html.h2("Device Twin & OTA"),
                    html.p({"class": "meta"}, "Azure IoT Hub desired/reported properties for the relay device."),
                ),
                html.div(
                    {"class": "button-group"},
                    render_button(
                        "Refresh Twin",
                        class_="btn glass-btn",
                        on_click=lambda e: refresh_iot_hub_data(sync_form=False),
                    ),
                    render_button(
                        "Load Desired OTA",
                        class_="btn glass-btn ghost",
                        disabled=not bool(desired_ota),
                        on_click=lambda e: set_ota_form_values(ota_form_defaults(twin)),
                    ),
                ),
            ),
            (
                html.p(
                    {"class": "meta", "style": {"color": "#b42318", "marginBottom": "0.75rem"}},
                    str(iot_hub.get("error") or iot_hub.get("sdk_error") or ""),
                )
                if (iot_hub.get("error") or iot_hub.get("sdk_error"))
                else None
            ),
            html.div(
                {"class": "telemetry-grid"},
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Device"),
                    html.span({"class": "stat-value stat-value-sm"}, device_id),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Connection"),
                    html.span({"class": f"pill {iot_pill_class(connection_state)}"}, connection_state),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Telemetry"),
                    html.span({"class": f"pill {iot_pill_class(listener_state)}"}, listener_state),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Firmware"),
                    html.span({"class": "stat-value"}, current_version),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Target"),
                    html.span({"class": "stat-value"}, target_version),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "OTA State"),
                    html.span({"class": f"pill {iot_pill_class(ota_state)}"}, ota_state),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Device Status"),
                    html.span({"class": f"pill {iot_pill_class(device_status)}"}, device_status),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Last Event"),
                    html.span({"class": "stat-value stat-value-sm"}, last_event),
                ),
            ),
            html.div(
                {"class": "iot-detail-grid"},
                html.div(
                    {"class": "status-info glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Last Activity"),
                    html.p({"class": "meta"}, last_activity),
                ),
                html.div(
                    {"class": "status-info glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Last OTA Attempt"),
                    html.p({"class": "meta"}, last_attempt),
                ),
                html.div(
                    {"class": "status-info glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "Rollout ID"),
                    html.p({"class": "meta"}, rollout_id),
                ),
                html.div(
                    {"class": "status-info glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "SHA-256"),
                    html.p({"class": "meta"}, sha256),
                ),
            ),
            html.div(
                {"class": "status-info glass-surface glass-panel iot-artifact-panel"},
                html.span({"class": "stat-label"}, "Artifact"),
                (
                    html.a(
                        {"class": "link", "href": artifact_url, "target": "_blank", "rel": "noopener"},
                        artifact_url,
                    )
                    if artifact_url
                    else html.p({"class": "meta"}, "No OTA artifact queued yet.")
                ),
                html.p({"class": "meta"}, f"Action: {action_value}"),
                html.p({"class": "meta"}, f"Size: {size_label}"),
            ),
            html.div(
                {"class": "status-info glass-surface glass-panel"},
                html.div(
                    {"class": "section-header"},
                    html.div(
                        {},
                        html.h3("Queue OTA Target"),
                        html.p(
                            {"class": "meta"},
                            "This writes desired OTA properties to IoT Hub. The current ESP32 firmware must support twins before it will act on them.",
                        ),
                    ),
                ),
                html.div(
                    {"class": "ota-form-grid"},
                    render_ota_field("target_version", "Target version", "1.4.2"),
                    render_ota_field("artifact_url", "Artifact URL", "https://storage/.../app.bin"),
                    render_ota_field("sha256", "SHA-256", "Optional integrity hash"),
                    render_ota_field("size", "Size (bytes)", "Optional image size", input_type="number"),
                    render_ota_field("rollout_id", "Rollout ID", "canary-2026-03-17"),
                    render_ota_field("action", "Action", "download_and_apply"),
                ),
                html.div(
                    {"class": "button-group"},
                    render_button(
                        "Queue OTA",
                        class_="btn glass-btn primary",
                        disabled=not iot_hub.get("configured"),
                        on_click=lambda e: push_ota_target_action(),
                    ),
                ),
            ),
        )

    def render_list_item(entity: str, item: Dict[str, Any], index: int) -> Dict:
        if entity == "tasks":
            priority_class = {"High": "high", "Medium": "medium", "Low": "low"}.get(item.get("priority"), "")
            status_class = {"Not started": "", "In progress": "in-progress", "Done": "done"}.get(item.get("status"), "")
            return html.div(
                {"class": "list-item glass-surface glass-panel task-item"},
                html.div(
                    {"class": "item-header"},
                    html.h4(item.get("task") or "Task"),
                    html.div(
                        {"class": "item-badges"},
                        html.span({"class": f"pill priority-{priority_class}"}, item.get("priority") or ""),
                        html.span({"class": f"pill status-{status_class}"}, item.get("status") or ""),
                    ),
                ),
                html.p({"class": "meta"}, f"Due: {item.get('due_date') or 'TBD'}"),
                html.div(
                    {"class": "item-actions"},
                    render_button("Edit", class_="btn glass-btn ghost",
                        on_click=lambda e: open_entity_modal("tasks", "edit", item)),
                    render_button("Delete", class_="btn glass-btn ghost danger",
                        on_click=lambda e: open_delete_modal("tasks", item.get("id"))),
                ),
            )
        return None

    def render_table_cell(entity: str, name: str, row: Dict[str, Any]) -> Any:
        value = row.get(name, "")
        text_value = "" if value is None else str(value)

        if entity == "documentation" and name == "title":
            if row.get("location") and row.get("id"):
                return html.a(
                    {"class": "link documentation-link", "href": f"/api/documentation/{int(row['id'])}/blob"},
                    text_value or "Blob",
                )
            return text_value

        if entity == "documentation" and name == "location":
            if value:
                return html.a(
                    {"class": "link", "href": str(value), "target": "_blank", "rel": "noopener"},
                    "Open",
                )
            return html.span({"class": "meta"}, "No link")

        if entity == "documentation" and name == "status":
            return html.span({"class": f"pill {documentation_status_class(value)}"}, str(value or ""))

        if entity == "bom" and name == "link":
            if value:
                return html.a(
                    {"class": "link", "href": str(value), "target": "_blank", "rel": "noopener"},
                    "Open",
                )
            return html.span({"class": "meta"}, "No link")

        if entity == "bom" and name == "status":
            return html.span({"class": f"pill {bom_status_class(value)}"}, str(value or ""))

        if entity == "risks" and name == "status":
            return html.span({"class": f"pill {risk_status_class(value)}"}, str(value or ""))

        return text_value

    def render_blob_upload_zone() -> Dict:
        return html.div(
            {
                "id": "blob-upload-zone",
                "class": "blob-upload-zone glass-surface glass-panel",
                "role": "button",
                "tabIndex": "0",
                "data-upload-state": "idle",
            },
            html.input(
                {
                    "id": "blob-upload-input",
                    "type": "file",
                    "style": {"display": "none"},
                }
            ),
            html.div({"class": "blob-upload-title", "data-upload-label": "1"}, "Drop a file here or click to upload to Blob"),
            html.p(
                {"class": "meta"},
                "The file is uploaded to Azure Blob Storage and added to Documentation automatically.",
            ),
        )

    def render_table_section(entity: str, rows: List[Dict[str, Any]], section_title: str) -> Dict:
        action_buttons = []
        upload_zone = None
        if entity == "documentation":
            action_buttons.append(
                render_button(
                    "Export Telemetry Log CSV",
                    class_="btn glass-btn primary",
                    on_click=lambda e: export_broadcast_csv_action(),
                )
            )
            upload_zone = render_blob_upload_zone()
        action_buttons.append(
            render_button("Add", class_="btn glass-btn", on_click=lambda e: open_entity_modal(entity, "new"))
        )

        if not rows:
            return html.section(
                {"class": "card glass-surface glass-card"},
                html.div(
                    {"class": "section-header"},
                    html.h2(section_title),
                ),
                upload_zone,
                html.p({"class": "meta"}, "No items yet."),
                html.div({"class": "button-group"}, *action_buttons),
            )

        entity_def = ENTITY_DEFS.get(entity, {})
        fields = entity_def.get("fields", [])
        field_names = [f["name"] for f in fields]
        field_labels = {f["name"]: f["label"] for f in fields}

        return html.section(
            {"class": "card glass-surface glass-card"},
            html.div(
                {"class": "section-header"},
                html.h2(section_title),
                html.div({"class": "button-group"}, *action_buttons),
            ),
            upload_zone,
            html.div(
                {"class": "table-wrap glass-surface glass-panel"},
                html.table(
                    {"class": "table"},
                    html.thead(
                        html.tr(
                            *[html.th(field_labels.get(name, name)) for name in field_names],
                            html.th("Actions"),
                        )
                    ),
                    html.tbody(
                        *[
                            html.tr(
                                {"key": row.get("id", idx)},
                                *[html.td(render_table_cell(entity, name, row)) for name in field_names],
                                html.td(
                                    html.div(
                                        {"class": "action-buttons"},
                                        render_button("Edit", class_="btn glass-btn ghost",
                                            on_click=lambda e, r=row: open_entity_modal(entity, "edit", r)),
                                        render_button("Delete", class_="btn glass-btn ghost danger",
                                            on_click=lambda e, r=row: open_delete_modal(entity, r.get("id"))),
                                    ),
                                ),
                            )
                            for idx, row in enumerate(rows)
                        ]
                    ),
                ),
            ),
        )

    if data.get("error"):
        return html.div(
            {"id": "project-hub-root"},
            html.style(GLASS_CSS),
            html.main(
                {"class": "page"},
                html.section(
                    {"class": "card glass-surface glass-card error-state"},
                    html.h1("Dashboard Error"),
                    html.p(data.get("error") or "Unknown error"),
                    render_button("Retry", class_="btn glass-btn primary",
                        on_click=lambda e: set_data(load_dashboard_data_safe())),
                ),
            ),
        )

    project = data.get("project", {})
    development = data.get("development", {})
    tasks = data.get("tasks", {})
    sections = data.get("sections", [])
    progress_row = data.get("progress_row", {})

    return html.div(
        {"id": "project-hub-root", "data-unsaved": "1" if (modal_state.get("open") and form_dirty) else "0"},
        html.style(GLASS_CSS),
        html.header(
            {"class": "navbar glass-surface glass-navbar"},
            html.div(
                {"class": "nav-brand"},
                html.h1(project.get("name") or "Project Hub"),
            ),
            html.div(
                {"class": "nav-status"},
                html.span({"class": "pill pill-info"}, f"Progress: {development.get('percent_label', '0%')}"),
                html.span({"class": "pill pill-muted"}, f"Phase: {project.get('phase') or 'None'}"),
            ),
            html.div(
                {"class": "nav-actions"},
                render_button("Edit Project", class_="btn glass-btn ghost", on_click=lambda e: open_project_modal()),
            ),
        ),
        html.main(
            {"class": "page"},
            html.section(
                {"class": "card glass-surface glass-card progress-section"},
                html.div(
                    {"class": "section-header"},
                    html.h2("Development Phase"),
                    html.p({"class": "meta"}, "Click a phase to save immediately"),
                ),
                html.div(
                    {"class": "progress-display"},
                    html.div(
                        {"class": "progress-metric"},
                        html.span({"class": "label"}, "Current Phase"),
                        html.span({"class": "value"}, development.get("phase", "Concept")),
                    ),
                    html.div(
                        {"class": "progress-bar-container"},
                        html.div(
                            {"class": "progress-bar", "style": {"width": f"{PHASE_TO_PERCENT.get(development.get('phase', 'Concept'), 0)}%"}},
                        ),
                    ),
                ),
                html.div(
                    {"class": "phase-selector"},
                    *[
                        html.button(
                            {
                                "class": f"phase-btn {'active' if phase == development.get('phase') else ''}",
                                "type": "button",
                                "disabled": is_busy,
                                "on_click": lambda e, p=phase: run_mutation(
                                    lambda: update_progress({"phase": p, "percent": PHASE_TO_PERCENT.get(p, 0)})
                                ),
                            },
                            phase,
                        )
                        for phase in PHASES
                    ],
                ),
            ),
            html.section(
                {"class": "card glass-surface glass-card"},
                html.div(
                    {"class": "section-header"},
                    html.h2("Tasks"),
                    html.p({"class": "meta"}, f"{len(tasks.get('bars', []))} tasks"),
                ),
                html.div(
                    {"class": "list"},
                    *[render_list_item("tasks", task, idx) for idx, task in enumerate(tasks.get("bars", []))]
                    if tasks.get("bars") else [html.p({"class": "meta"}, "No tasks yet.")],
                ),
                render_button("Add Task", class_="btn glass-btn", on_click=lambda e: open_entity_modal("tasks", "new")),
            ),
            render_telemetry_card(),
            render_iot_hub_card(),
            *[render_table_section(s["key"], s["rows"], s["title"]) for s in sections if s.get("rows") is not None and s.get("key") != "system_status"],
        ),
        render_modal(),
        (
            html.div(
                {"class": "toast glass-surface glass-panel"},
                html.span(
                    {
                        "class": (
                            "pill pill-danger"
                            if ("failed" in control_feedback.lower() or "error" in control_feedback.lower())
                            else (
                                "pill pill-success"
                                if any(
                                    keyword in control_feedback.lower()
                                    for keyword in ("updated", "added", "deleted", "exported", "synced")
                                )
                                else "pill pill-info"
                            )
                        )
                    },
                    control_feedback,
                ),
            )
            if control_feedback
            else None
        ),
    )
