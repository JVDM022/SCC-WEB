from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from flask import current_app, has_app_context
from reactpy import component, event, hooks, html

from config import DOC_TYPE_FILTER_ALL, ENTITY_DEFS, PHASES, PHASE_TO_PERCENT
from services.azure_relay import load_heater_telemetry_safe, send_heater_command
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
    # Data & State Management
    data, set_data = hooks.use_state(load_dashboard_data_safe)
    telemetry, set_telemetry = hooks.use_state(load_heater_telemetry_safe)
    
    # Modal State - Simplified
    modal_state, set_modal_state = hooks.use_state({
        "open": False,
        "type": None,  # "edit_project", "edit_progress", "new_entity", "edit_entity", "delete_confirm"
        "entity": None,  # For entity modals: "tasks", "bom", etc.
        "item_id": None,  # For edit/delete
        "item_data": None,  # Current item being edited
    })
    
    # Form State - Controlled inputs
    form_values, set_form_values = hooks.use_state({})
    form_dirty, set_form_dirty = hooks.use_state(False)
    is_busy, set_is_busy = hooks.use_state(False)
    control_feedback, set_control_feedback = hooks.use_state("")
    doc_type_filter, set_doc_type_filter = hooks.use_state(DOC_TYPE_FILTER_ALL)

    # Helper: Get field value from form with default
    def get_field_value(name: str, default: Any = "") -> Any:
        return form_values.get(name, default)

    def set_field_value(name: str, value: Any) -> None:
        if is_busy:
            return
        set_form_values(lambda prev: {**prev, name: value})
        set_form_dirty(True)

    # Modal Management
    def open_modal(modal_type: str, **kwargs) -> None:
        if is_busy:
            return
        set_form_values({})
        set_form_dirty(False)
        set_modal_state({"open": True, "type": modal_type, **kwargs})

    def close_modal(force: bool = False) -> None:
        if is_busy:
            return
        if modal_state.get("open") and form_dirty and not force:
            # Show discard warning
            set_modal_state(lambda prev: {**prev, "confirm_close": True})
        else:
            set_modal_state({"open": False, "type": None})
            set_form_values({})
            set_form_dirty(False)

    def confirm_close() -> None:
        set_modal_state({"open": False, "type": None})
        set_form_values({})
        set_form_dirty(False)

    def dismiss_close_warning() -> None:
        set_modal_state(lambda prev: {**prev, "confirm_close": False})

    # Data mutations
    def run_mutation(action: Callable[[], None], refresh_after: bool = True) -> None:
        if is_busy:
            return
        set_is_busy(True)
        try:
            action()
            if refresh_after:
                set_data(load_dashboard_data_safe())
        finally:
            set_is_busy(False)

    def handle_save_project() -> None:
        def do_save() -> None:
            update_project(form_values)
            set_control_feedback("Project updated")
        run_mutation(do_save)
        close_modal(force=True)

    def handle_save_progress() -> None:
        def do_save() -> None:
            update_progress(form_values)
            set_control_feedback("Progress updated")
        run_mutation(do_save)
        close_modal(force=True)

    def handle_save_entity() -> None:
        def do_save() -> None:
            entity = modal_state.get("entity")
            item_id = modal_state.get("item_id")
            if item_id:
                update_entity(entity, item_id, form_values)
                set_control_feedback(f"{ENTITY_DEFS[entity]['label']} updated")
            else:
                insert_entity(entity, form_values)
                set_control_feedback(f"{ENTITY_DEFS[entity]['label']} added")
        run_mutation(do_save)
        close_modal(force=True)

    def handle_delete_entity() -> None:
        def do_delete() -> None:
            entity = modal_state.get("entity")
            item_id = modal_state.get("item_id")
            delete_entity(entity, item_id)
            set_control_feedback(f"{ENTITY_DEFS[entity]['label']} deleted")
        run_mutation(do_delete)
        set_modal_state({"open": False, "type": None})

    def send_heater_command_action(kill_value: int) -> None:
        def do_send() -> None:
            set_control_feedback("")
            try:
                send_heater_command(kill_value)
                set_control_feedback("KILL command sent." if kill_value == 1 else "UNKILL command sent.")
            except Exception as exc:
                _logger().exception("Failed to send heater command")
                set_control_feedback(f"Command failed: {exc}")
            set_telemetry(load_heater_telemetry_safe())
        run_mutation(do_send, refresh_after=False)

    def refresh_telemetry_data() -> None:
        def do_refresh() -> None:
            set_control_feedback("")
            set_telemetry(load_heater_telemetry_safe())
        run_mutation(do_refresh, refresh_after=False)

    # === RENDER FUNCTIONS ===

    def render_button(label: str, **kwargs) -> Dict:
        """Generic button render"""
        return html.button(
            {
                "class": kwargs.pop("class", "btn glass-btn"),
                "type": kwargs.pop("type", "button"),
                "disabled": is_busy or kwargs.pop("disabled", False),
                **kwargs
            },
            label,
        )

    def render_input_field(name: str, label: str, input_type: str = "text", **extra_attrs) -> Dict:
        """Controlled text input"""
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.input(
                {
                    "type": input_type,
                    "class": "input glass-input",
                    "value": get_field_value(name, ""),
                    "disabled": is_busy,
                    "on_change": lambda e: set_field_value(name, e.get("target", {}).get("value", "")),
                    **extra_attrs
                }
            ),
        )

    def render_textarea_field(name: str, label: str, **extra_attrs) -> Dict:
        """Controlled textarea"""
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.textarea(
                {
                    "class": "textarea glass-input",
                    "value": get_field_value(name, ""),
                    "disabled": is_busy,
                    "on_change": lambda e: set_field_value(name, e.get("target", {}).get("value", "")),
                    **extra_attrs
                }
            ),
        )

    def render_segmented_field(name: str, label: str, options: List[Dict[str, str]]) -> Dict:
        """Segmented control (button group)"""
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
                            "on_click": lambda e, val=opt["value"]: set_field_value(name, val),
                        },
                        opt["label"],
                    )
                    for opt in options
                ],
            ),
        )

    def render_stepper_field(name: str, label: str, min_val: int = 0, max_val: int = 100, step: int = 5) -> Dict:
        """Numeric stepper control"""
        current = int(get_field_value(name, min_val))
        return html.div(
            {"class": "field"},
            html.label({"class": "label"}, label),
            html.div(
                {"class": "stepper"},
                render_button("−", 
                    class_="stepper-btn stepper-minus",
                    disabled=current <= min_val,
                    on_click=lambda e: set_field_value(name, max(min_val, current - step)),
                ),
                html.span({"class": "stepper-value"}, f"{current}%"),
                render_button("+",
                    class_="stepper-btn stepper-plus",
                    disabled=current >= max_val,
                    on_click=lambda e: set_field_value(name, min(max_val, current + step)),
                ),
            ),
        )

    def render_generic_field(entity: str, field: Dict[str, Any]) -> Dict:
        """Dynamically render a field based on entity and field config"""
        name = field["name"]
        label = field["label"]
        
        # Check for segmented control fields
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
            return render_input_field(name, label, field.get("input_type", "text"), 
                step=field.get("step") if field.get("step") else None)

    # Modal components
    def render_project_modal() -> Dict:
        fields = ENTITY_DEFS["project"]["fields"]
        initial = {f["name"]: data["project"].get(f["name"], "") for f in fields}
        if not form_values:
            set_form_values(initial)
        return html.form(
            {"class": "form", "on_submit": lambda e: e.preventDefault()},
            *[render_generic_field("project", f) for f in fields],
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal()),
                render_button("Save", class_="btn glass-btn primary", on_click=lambda e: handle_save_project()),
            ),
        )

    def render_progress_modal() -> Dict:
        progress_row = data.get("progress_row", {})
        if not form_values:
            set_form_values({
                "phase": normalize_phase(progress_row.get("phase")) or "Concept",
                "percent": progress_row.get("percent") or 0,
            })
        return html.form(
            {"class": "form", "on_submit": lambda e: e.preventDefault()},
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
                render_button("Save", class_="btn glass-btn primary", on_click=lambda e: handle_save_progress()),
            ),
        )

    def render_entity_modal() -> Dict:
        entity = modal_state.get("entity")
        entity_def = ENTITY_DEFS.get(entity, {})
        fields = entity_def.get("fields", [])
        
        # Initialize form if empty
        if not form_values:
            item_data = modal_state.get("item_data")
            if item_data:
                initial = {f["name"]: item_data.get(f["name"], "") for f in fields}
            else:
                initial = default_values_for(entity, fields)
            set_form_values(initial)
        
        is_edit = bool(modal_state.get("item_id"))
        title = f"{'Edit' if is_edit else 'Add'} {entity_def.get('label', entity)}"
        
        return html.form(
            {"class": "form", "on_submit": lambda e: e.preventDefault()},
            html.h3({"class": "modal-subtitle"}, title),
            *[render_generic_field(entity, f) for f in fields],
            html.div(
                {"class": "form-actions"},
                render_button("Cancel", class_="btn glass-btn ghost", on_click=lambda e: close_modal()),
                render_button("Save", class_="btn glass-btn primary", on_click=lambda e: handle_save_entity()),
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
        
        # Close confirmation
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
        temp = telemetry.get("temperature")
        temp_label = f"{float(temp):.1f}°C" if isinstance(temp, (int, float)) else "--"
        
        heater_on = telemetry.get("heater_on")
        heater_label = "ON" if heater_on is True else ("OFF" if heater_on is False else "Unknown")
        heater_class = "pill-warning" if heater_on is True else ("pill-muted" if heater_on is False else "pill-muted")
        
        kill_state = telemetry.get("kill_state")
        kill_label = "KILLED" if kill_state is True else ("ACTIVE" if kill_state is False else "Unknown")
        kill_class = "pill-danger" if kill_state is True else ("pill-success" if kill_state is False else "pill-muted")
        
        # Get system status from sections
        system_status_section = next((s for s in data.get("sections", []) if s.get("key") == "system_status"), None)
        system_status_row = system_status_section.get("rows", [{}])[0] if system_status_section and system_status_section.get("rows") else {}
        system_online = system_status_row.get("is_online")
        system_online_label = "Online" if system_online in ["1", "true", "True"] else ("Offline" if system_online in ["0", "false", "False"] else "Unknown")
        system_online_class = "pill-success" if system_online in ["1", "true", "True"] else ("pill-danger" if system_online in ["0", "false", "False"] else "pill-muted")
        reason = system_status_row.get("reason", "")
        
        return html.section(
            {"class": "card glass-surface glass-card"},
            html.div(
                {"class": "section-header"},
                html.h2("System & Heater Control"),
                html.p({"class": "meta"}, f"Last telemetry: {telemetry.get('fetched_at') or 'Never'}"),
            ),
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
                    html.span({"class": "stat-label"}, "Kill State"),
                    html.span({"class": f"pill {kill_class}"}, kill_label),
                ),
                html.div(
                    {"class": "stat-box glass-surface glass-panel"},
                    html.span({"class": "stat-label"}, "System"),
                    html.span({"class": f"pill {system_online_class}"}, system_online_label),
                ),
            ),
            (html.div(
                {"class": "status-info glass-surface glass-panel", "style": {"padding": "1rem", "margin": "1rem 0"}},
                html.p({"class": "meta"}, f"Reason: {reason}"),
            ) if reason else None),
            html.div(
                {"class": "button-group"},
                render_button("Refresh", class_="btn glass-btn", on_click=lambda e: refresh_telemetry_data()),
                render_button("KILL", class_="btn glass-btn danger", on_click=lambda e: send_heater_command_action(1)),
                render_button("UNKILL", class_="btn glass-btn", on_click=lambda e: send_heater_command_action(0)),
                render_button("Edit System Status", class_="btn glass-btn ghost", on_click=lambda e: open_modal("edit_entity", entity="system_status", item_id=system_status_row.get("id"), item_data=system_status_row)),
            ),
            html.p({"class": "meta"}, f"Logged: {telemetry_log_sample_count()} samples"),
        )

    # List item rendering
    def render_list_item(entity: str, item: Dict[str, Any], index: int) -> Dict:
        """Generic list item for tasks"""
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
                        on_click=lambda e: open_modal("edit_entity", entity="tasks",
                            item_id=item.get("id"), item_data=item)),
                    render_button("Delete", class_="btn glass-btn ghost danger",
                        on_click=lambda e: open_modal("delete_confirm", entity="tasks", item_id=item.get("id"))),
                ),
            )
        return None

    def render_table_section(entity: str, rows: List[Dict[str, Any]], section_title: str) -> Dict:
        """Generic table for BOM, Documentation, Risks"""
        if not rows:
            return html.section(
                {"class": "card glass-surface glass-card"},
                html.div(
                    {"class": "section-header"},
                    html.h2(section_title),
                ),
                html.p({"class": "meta"}, "No items yet."),
                render_button("Add", class_="btn glass-btn", 
                    on_click=lambda e: open_modal("new_entity", entity=entity)),
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
            ),
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
                                *[html.td(str(row.get(name, ""))) for name in field_names],
                                html.td(
                                    html.div(
                                        {"class": "action-buttons"},
                                        render_button("Edit", class_="btn glass-btn ghost",
                                            on_click=lambda e, r=row: open_modal("edit_entity", entity=entity,
                                                item_id=r.get("id"), item_data=r)),
                                        render_button("Delete", class_="btn glass-btn ghost danger",
                                            on_click=lambda e, r=row: open_modal("delete_confirm", entity=entity, item_id=r.get("id"))),
                                    ),
                                ),
                            )
                            for idx, row in enumerate(rows)
                        ]
                    ),
                ),
            ),
            render_button("Add", class_="btn glass-btn",
                on_click=lambda e: open_modal("new_entity", entity=entity)),
        )

    # Main render
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
        
        # Header
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
                render_button("Edit Project", class_="btn glass-btn ghost",
                    on_click=lambda e: open_modal("edit_project")),
            ),
        ),
        
        # Main content
        html.main(
            {"class": "page"},
            
            # Progress visualization
            html.section(
                {"class": "card glass-surface glass-card progress-section"},
                html.div(
                    {"class": "section-header"},
                    html.h2("Development Phase"),
                    html.p({"class": "meta"}, "Click to change phase"),
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
            
            # Tasks
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
                render_button("Add Task", class_="btn glass-btn",
                    on_click=lambda e: open_modal("new_entity", entity="tasks")),
            ),
            
            # Heater control
            render_telemetry_card(),
            
            # Tables: BOM, Documentation, Risks
            *[render_table_section(s["key"], s["rows"], s["title"]) for s in sections if s.get("rows") is not None],
        ),
        
        # Modal
        render_modal(),
        
        # Status message
        (html.div(
            {"class": "toast glass-surface glass-panel"},
            html.span({"class": f"pill {'pill-success' if 'updated' in control_feedback or 'added' in control_feedback or 'deleted' in control_feedback else 'pill-info'}"}, control_feedback),
        ) if control_feedback else None),
    )
