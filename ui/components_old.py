from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from flask import current_app, has_app_context
from reactpy import component, event, hooks, html

from config import DOC_TYPE_FILTER_ALL, ENTITY_DEFS, PHASES, PHASE_TO_PERCENT
from services.heater_telemetry_source import load_heater_telemetry_safe, send_heater_command
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
from services.telemetry import telemetry_log_sample_count
from ui.styles import GLASS_CSS


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


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
)


@component
def App():
    data, set_data = hooks.use_state(load_dashboard_data_safe)
    telemetry, set_telemetry = hooks.use_state(load_heater_telemetry_safe)
    control_feedback, set_control_feedback = hooks.use_state("")
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

    def refresh_telemetry() -> None:
        def do_refresh() -> None:
            set_control_feedback("")
            set_telemetry(load_heater_telemetry_safe())

        run_mutation(do_refresh, refresh_after=False)

    def send_kill_command(value: int) -> None:
        def do_send() -> None:
            set_control_feedback("")
            try:
                send_heater_command(value)
                set_control_feedback("KILL command sent." if value == 1 else "UNKILL command sent.")
            except Exception as exc:
                _logger().exception("Failed to send heater command")
                set_control_feedback(f"Command failed: {exc}")
            set_telemetry(load_heater_telemetry_safe())

        run_mutation(do_send, refresh_after=False)

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

    def render_stepper(name: str, value: int | float, min_val: int = 0, max_val: int = 100, step: int = 1):
        """Render a stepper control for numeric input (Apple-style)"""
        current = int(value) if value else min_val
        return html.div(
            {"class": "stepper"},
            html.button(
                {
                    "type": "button",
                    "class": "stepper-btn stepper-minus",
                    "disabled": is_busy or current <= min_val,
                    "on_click": lambda e: set_field(name, max(min_val, current - step)),
                },
                "−",
            ),
            html.span({"class": "stepper-value"}, str(current)),
            html.button(
                {
                    "type": "button",
                    "class": "stepper-btn stepper-plus",
                    "disabled": is_busy or current >= max_val,
                    "on_click": lambda e: set_field(name, min(max_val, current + step)),
                },
                "+",
            ),
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
                render_stepper("percent", percent_value, 0, 100, 5),
                html.div({"class": "meta"}, f"{percent_value}%"),
            ),
            html.div(
                {"class": "field"},
                html.span({"class": "label"}, "Phase"),
                render_segmented(
                    "phase",
                    str(phase_value or ""),
                    [
                        {"label": "Concept", "value": "Concept"},
                        {"label": "Developing", "value": "Developing"},
                        {"label": "Prototype", "value": "Prototype"},
                        {"label": "Testing", "value": "Testing"},
                        {"label": "Complete", "value": "Complete"},
                    ],
                ),
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

    def render_telemetry_dashboard():
        temperature = telemetry.get("temperature")
        if isinstance(temperature, (int, float)):
            temperature_label = f"{float(temperature):.1f} °C"
        else:
            temperature_label = "--"

        heater_on = telemetry.get("heater_on")
        if heater_on is True:
            heater_label = "ON"
            heater_class = "pill-warning"
        elif heater_on is False:
            heater_label = "OFF"
            heater_class = "pill-muted"
        else:
            heater_label = "Unknown"
            heater_class = "pill-muted"

        kill_state = telemetry.get("kill_state")
        if kill_state is True:
            kill_label = "KILLED"
            kill_class = "pill-danger"
        elif kill_state is False:
            kill_label = "ACTIVE"
            kill_class = "pill-success"
        else:
            kill_label = "Unknown"
            kill_class = "pill-muted"

        fetched_at = str(telemetry.get("fetched_at") or "")
        telemetry_error = str(telemetry.get("error") or "")
        logged_samples = telemetry_log_sample_count()

        status_message = control_feedback if control_feedback else (telemetry_error if telemetry_error else "")
        status_class = "pill-danger" if telemetry_error else ("pill-info" if control_feedback else "pill-muted")

        return html.div(
            {"class": "glass-surface glass-panel", "style": {"padding": "14px", "display": "grid", "gap": "12px"}},
            html.div(
                {"class": "section-head"},
                html.div(
                    html.h3("Heater Status, Telemetry, Control"),
                    html.div({"class": "meta"}, f"Last telemetry: {fetched_at}" if fetched_at else "No telemetry yet"),
                ),
                html.div(
                    html.button(
                        {"class": "btn glass-btn ghost", "type": "button", "disabled": is_busy, "on_click": lambda e: refresh_telemetry()},
                        "Refresh",
                    ),
                ),
            ),
            html.div(
                {"style": {"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(160px, 1fr))", "gap": "10px"}},
                html.div(
                    {"class": "glass-surface glass-panel", "style": {"padding": "10px"}},
                    html.div({"class": "meta"}, "Temperature"),
                    html.div(temperature_label),
                ),
                html.div(
                    {"class": "glass-surface glass-panel", "style": {"padding": "10px"}},
                    html.div({"class": "meta"}, "Heater"),
                    html.span({"class": f"pill {heater_class}"}, heater_label),
                ),
                html.div(
                    {"class": "glass-surface glass-panel", "style": {"padding": "10px"}},
                    html.div({"class": "meta"}, "Kill State"),
                    html.span({"class": f"pill {kill_class}"}, kill_label),
                ),
            ),
            html.div(
                {"class": "form-actions"},
                html.button(
                    {"class": "btn glass-btn primary", "type": "button", "disabled": is_busy, "on_click": lambda e: send_kill_command(1)},
                    "KILL",
                ),
                html.button(
                    {"class": "btn glass-btn", "type": "button", "disabled": is_busy, "on_click": lambda e: send_kill_command(0)},
                    "UNKILL",
                ),
            ),
            html.div(
                {"class": "meta"},
                f"Logged samples: {logged_samples} · ",
                html.a(
                    {"class": "link", "href": "/api/system-status/telemetry-log.csv", "target": "_blank", "rel": "noopener"},
                    "Download CSV",
                ),
                " (MATLAB/Python ready)",
            ),
            html.div({"class": f"pill {status_class}"}, status_message or "Ready"),
        )

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
        if entity == "system_status":
            section_meta = "System health, live heater telemetry, and kill controls."
            return html.section(
                {"class": "card glass-surface glass-card", "key": entity},
                html.div(
                    {"class": "section-head"},
                    html.div(
                        html.h2(section["title"]),
                        html.div({"class": "meta"}, section_meta),
                    ),
                ),
                render_telemetry_dashboard(),
            )

        actions = [
            html.button({"class": "btn glass-btn", "disabled": is_busy, "on_click": lambda e: open_entity_modal(entity, "new")}, "Add")
        ]
        body = (
            html.div(
                {"class": "table-wrap glass-surface glass-panel"},
                html.table(
                    {"class": "table"},
                    html.thead(
                        html.tr(
                            *[html.th(labels[field]) for field in fields],
                            html.th("Actions"),
                        )
                    ),
                    html.tbody(
                        *[
                            html.tr(
                                {"key": row.get("id", idx)},
                                *[html.td(render_cell(entity, field, row)) for field in fields],
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
