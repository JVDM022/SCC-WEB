from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
DATABASE = "project.db"

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

HOME_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ project.name or "Project Hub" }}</title>
    <style>
      :root {
        --bg: #f5f2ec;
        --bg-accent: #f1ede3;
        --ink: #1f2a2e;
        --muted: #5c6b73;
        --card: #ffffff;
        --border: #e3ddd1;
        --accent: #2c6e63;
        --accent-2: #f2b880;
        --danger: #c84b4b;
        --shadow: 0 18px 40px rgba(32, 41, 40, 0.12);
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        font-family: "Avenir Next", "Optima", "Gill Sans", "Trebuchet MS", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, #ffffff 0%, var(--bg) 45%),
          repeating-linear-gradient(
            135deg,
            rgba(0, 0, 0, 0.015) 0,
            rgba(0, 0, 0, 0.015) 12px,
            rgba(255, 255, 255, 0.015) 12px,
            rgba(255, 255, 255, 0.015) 24px
          );
      }

      h1, h2 {
        font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        letter-spacing: 0.2px;
      }

      h1 { margin: 0 0 8px; font-size: 34px; }
      h2 { margin: 0; font-size: 20px; }

      .page {
        max-width: 1100px;
        margin: 0 auto;
        padding: 32px 20px 60px;
        display: grid;
        gap: 20px;
      }

      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        box-shadow: var(--shadow);
        animation: cardIn 0.5s ease forwards;
        opacity: 0;
        transform: translateY(10px);
        animation-delay: var(--delay, 0s);
      }

      @keyframes cardIn {
        to { opacity: 1; transform: translateY(0); }
      }

      .hero {
        display: grid;
        gap: 16px;
      }

      .eyebrow {
        text-transform: uppercase;
        letter-spacing: 0.2em;
        font-size: 11px;
        color: var(--muted);
      }

      .meta-grid {
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 14px;
      }

      .actions {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }

      .section-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }

      .btn {
        border: 1px solid var(--border);
        background: #f7f4ee;
        padding: 8px 12px;
        border-radius: 10px;
        cursor: pointer;
        text-decoration: none;
        color: var(--ink);
        font-size: 14px;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
      }

      .btn:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,0.08); }
      .btn.primary { background: linear-gradient(120deg, var(--accent), #3f8b7e); color: #fff; border: none; }
      .link-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 999px;
        border: 1px solid var(--border);
        font-size: 12px;
        margin-top: 8px;
      }
      .link-pill.valid { background: #e9f6ef; border-color: #b7dec7; color: #1f6b46; }
      .link-pill.invalid { background: #ffe5e5; border-color: #f0b1b1; color: #8b2f2f; }
      .toggle-row {
        display: grid;
        gap: 10px;
        width: 100%;
      }
      .status-pill {
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
      }
      .status-online { background: #e9f6ef; color: #1f6b46; border: 1px solid #b7dec7; }
      .status-offline { background: #ffe5e5; color: #8b2f2f; border: 1px solid #f0b1b1; }
      .status-toggle {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        width: 100%;
        min-height: 48px;
      }
      .status-btn {
        width: 100%;
        border: 1px solid var(--border);
        background: #f1ede3;
        color: var(--muted);
        padding: 14px 18px;
        border-radius: 999px;
        font-size: 14px;
        cursor: pointer;
        text-align: center;
        min-height: 44px;
        appearance: none;
        -webkit-appearance: none;
        box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.04);
      }
      .status-btn.active {
        background: #e1efe9;
        border-color: #b9d9ce;
        color: var(--accent);
        font-weight: 600;
      }
      .status-btn.online.active {
        background: #dff6e6;
        border-color: #a9e2bb;
        color: #1f6b46;
      }
      .status-btn.offline.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .offline-only { display: block; }
      .btn-danger { border-color: #e0b2b2; color: var(--danger); background: #fff7f7; }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }

      th, td {
        text-align: left;
        padding: 10px 8px;
        border-bottom: 1px solid var(--border);
      }

      th {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }

      tbody tr:hover { background: var(--bg-accent); }

      .muted { color: var(--muted); }
      .inline { display: inline; }
      .table-wrap { overflow-x: auto; }
      .progress-list { display: grid; gap: 12px; }
      .progress-card {
        background: #fbf8f1;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px;
        display: grid;
        gap: 10px;
      }
      .progress-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
      }
      .progress-title { font-weight: 600; }
      .progress-meta { font-size: 12px; color: var(--muted); }
      .progress-bar {
        position: relative;
        height: 10px;
        border-radius: 999px;
        background: #e7e0d2;
        overflow: hidden;
      }
      .progress-bar span {
        display: block;
        height: 100%;
        background: linear-gradient(90deg, var(--accent), var(--accent-2));
      }
      .progress-needle {
        position: absolute;
        top: -6px;
        width: 2px;
        height: 22px;
        background: var(--ink);
        left: 0%;
        transform: translateX(-1px);
      }
      .phase-track {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 6px;
        margin-top: 8px;
      }
      .phase-step {
        text-align: center;
        font-size: 11px;
        padding: 6px 4px;
        border-radius: 999px;
        background: #f1ede3;
        color: var(--muted);
        border: 1px solid var(--border);
        appearance: none;
      }
      .phase-step.active {
        background: #e1efe9;
        color: var(--accent);
        border-color: #b9d9ce;
        font-weight: 600;
      }
      .progress-actions { display: flex; gap: 8px; align-items: center; }
      .log-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-top: 16px;
      }
      .log-list { display: grid; gap: 12px; margin-top: 12px; }
      .log-entry {
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px;
        background: #ffffff;
        display: grid;
        gap: 6px;
      }
      .log-title { font-weight: 600; }
      .log-meta { font-size: 12px; color: var(--muted); }
      .log-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .card.collapsed .section-body { display: none; }
      .section-hint { font-size: 12px; color: var(--muted); }
      .card.draggable { cursor: grab; }
      .card.dragging { opacity: 0.65; }
      .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        background: #f1ede3;
        color: var(--muted);
        border: 1px solid var(--border);
      }
      .badge-schematic { background: #e6f0ff; border-color: #bcd3ff; color: #2b4d8b; }
      .badge-cad { background: #f0f2ff; border-color: #c6ccff; color: #404d9c; }
      .badge-pdf { background: #ffeef0; border-color: #f5c0c7; color: #8b2f2f; }
      .link-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 999px;
        border: 1px solid var(--border);
        font-size: 12px;
      }
      .link-pill.valid { background: #e9f6ef; border-color: #b7dec7; color: #1f6b46; }
      .link-pill.invalid { background: #ffe5e5; border-color: #f0b1b1; color: #8b2f2f; }
      .modal {
        position: fixed;
        inset: 0;
        background: rgba(26, 32, 36, 0.45);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 24px;
        z-index: 40;
      }
      .modal.open { display: flex; }
      .modal-card {
        width: min(720px, 95vw);
        background: #fffdf8;
        border-radius: 16px;
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
        padding: 22px;
        display: grid;
        gap: 12px;
        max-height: 80vh;
        overflow: auto;
      }
      .modal-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
      }
      .modal-title { font-size: 20px; margin: 0; }
      .modal-label {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }
      .modal-section { display: grid; gap: 6px; }
      .modal-body { white-space: pre-wrap; line-height: 1.5; }
      .modal-close {
        border: 1px solid var(--border);
        background: #f7f4ee;
        padding: 6px 10px;
        border-radius: 999px;
        cursor: pointer;
      }
      .calendar {
        display: grid;
        grid-template-columns: 180px repeat(7, minmax(0, 1fr));
        gap: 8px;
        align-items: stretch;
      }
      .calendar-header {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--muted);
        padding: 6px 8px;
      }
      .calendar-day {
        background: #fffdf8;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 10px;
        min-height: 120px;
        display: grid;
        gap: 6px;
      }
      .calendar-day.today {
        border-color: #b9d9ce;
        background: #f4fbf8;
      }
      .calendar-date {
        font-weight: 600;
        font-size: 14px;
      }
      .calendar-side {
        border: 1px dashed var(--border);
        border-radius: 12px;
        padding: 10px;
        background: #f7f4ee;
        font-size: 12px;
        color: var(--muted);
      }
      .task-bar {
        padding: 8px 10px;
        border-radius: 10px;
        font-size: 13px;
        display: flex;
        justify-content: space-between;
        gap: 8px;
        align-items: center;
        border: 1px solid transparent;
      }
      .task-bar small { font-size: 11px; color: var(--muted); }
      .priority-high { background: #ffe5e5; border-color: #f0b1b1; color: #8b2f2f; }
      .priority-medium { background: #fff0d9; border-color: #f1caa0; color: #8a5a12; }
      .priority-low { background: #e9f6ef; border-color: #b7dec7; color: #1f6b46; }
      .task-status {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 8px;
        border: 1px solid transparent;
      }
      .task-status.status-not-started { background: #f1ede3; border-color: #d8d1c4; color: #5c6b73; }
      .task-status.status-progress { background: #e7f0ff; border-color: #b9cdee; color: #2b4b7a; }
      .task-status.status-done { background: #e9f6ef; border-color: #b7dec7; color: #1f6b46; }
      .risk-status {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid transparent;
        text-transform: capitalize;
      }
      .risk-status.risk-ongoing { background: #ffe5e5; border-color: #f0b1b1; color: #8b2f2f; }
      .risk-status.risk-resolved { background: #e9f6ef; border-color: #b7dec7; color: #1f6b46; }
      .risk-status.risk-neutral { background: #f1ede3; border-color: #d8d1c4; color: #5c6b73; }
      .bom-status {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid transparent;
        text-transform: capitalize;
      }
      .bom-status.purchased { background: #e6f0ff; border-color: #bcd3ff; color: #2b4d8b; }
      .bom-status.not-purchased { background: #ffe5e5; border-color: #f0b1b1; color: #8b2f2f; }
      .bom-status.neutral { background: #f1ede3; border-color: #d8d1c4; color: #5c6b73; }
      .task-stack { display: grid; gap: 8px; }
      .calendar-actions { display: flex; gap: 8px; align-items: center; }
      @media (max-width: 980px) {
        .calendar { grid-template-columns: 1fr; }
      }

      @media (max-width: 720px) {
        h1 { font-size: 28px; }
        .page { padding: 24px 16px 40px; }
      }
    </style>
  </head>
  <body data-entity="{{ entity or '' }}">
    <main class="page">
      <header class="card hero" style="--delay: 0s;">
        <div>
          <div class="eyebrow">Project hub</div>
          <h1>{{ project.name or "Project" }}</h1>
          <div class="meta-grid">
            <div>Phase: {{ project.phase or "" }}</div>
            <div>Last updated: {{ updated }}</div>
          </div>
        </div>
        <div class="actions">
          <a class="btn primary" href="{{ url_for('edit_project') }}">Edit project</a>
        </div>
      </header>
      <div id="cardList">
        {% for card in cards %}
        <section
          class="card draggable"
          data-key="{{ card.key }}"
          draggable="true"
          style="--delay: {{ loop.index0 * 0.05 }}s;"
        >
          {% if card.type == "progress" %}
          <div class="section-head">
            <div>
              <h2>Development Progress</h2>
              <div class="muted">Single progress bar for overall development.</div>
              <div class="section-hint">Double-click this header to open/close.</div>
            </div>
            <a class="btn" href="{{ url_for('edit_progress') }}">Edit</a>
          </div>
          <div class="section-body">
            <div class="progress-card">
              <div class="progress-head">
                <div>
                  <div class="progress-title">Overall development</div>
                  {% if development.phase %}
                  <div class="progress-meta">Phase: {{ development.phase }}</div>
                  {% endif %}
                </div>
                {% if development.percent_label %}
                <div class="progress-meta">{{ development.percent_label }}</div>
                {% endif %}
              </div>
              <div class="progress-bar">
                <span style="width: {{ development.percent_value }}%"></span>
                <div class="progress-needle" style="left: {{ development.percent_value }}%"></div>
              </div>
              <div class="phase-track">
                {% for phase in phases %}
                <div class="phase-step {% if phase == development.phase %}active{% endif %}">{{ phase }}</div>
                {% endfor %}
              </div>
              <div class="log-head" id="development-log">
                <div>
                  <div class="progress-title">Development log</div>
                  <div class="muted">Add a daily update for the build.</div>
                </div>
                <a class="btn" href="{{ url_for('new_item', entity='development_log') }}">Add log</a>
              </div>
              {% if logs %}
              <div class="log-list">
                {% for log in logs %}
                <div class="log-entry">
                  <div class="log-meta">{{ log.log_date or "" }}</div>
                  <div class="log-title">{{ log.summary or "Update" }}</div>
                  {% if log.details %}
                  <div class="muted">{{ log.details }}</div>
                  {% endif %}
                  <div class="log-actions">
                    <a href="{{ url_for('edit_item', entity='development_log', item_id=log['id']) }}">Edit</a>
                    <form class="inline" method="post" action="{{ url_for('delete_item', entity='development_log', item_id=log['id']) }}">
                      <button class="btn btn-danger" type="submit">Delete</button>
                    </form>
                  </div>
                </div>
                {% endfor %}
              </div>
              {% else %}
              <div class="muted">No log entries yet.</div>
              {% endif %}
            </div>
          </div>
          {% elif card.type == "tasks" %}
          <div class="section-head">
            <div>
              <h2>Tasks</h2>
              <div class="muted">Week view calendar with priority bars.</div>
              <div class="section-hint">Double-click this header to open/close.</div>
            </div>
            <div class="calendar-actions">
              <a class="btn" href="{{ url_for('new_item', entity='tasks') }}">Add task</a>
            </div>
          </div>
          <div class="section-body">
            <div class="task-stack">
              {% for task in tasks.bars %}
              <div class="task-bar {{ task.priority_class }}">
                <div>
                  {{ task.task }}
                  <span class="task-status {{ task.status_class }}">{{ task.status_text }}</span>
                  {% if task.due_date %}<small>· Due {{ task.due_date }}</small>{% endif %}
                </div>
                <div class="calendar-actions">
                  <a href="{{ url_for('edit_item', entity='tasks', item_id=task['id']) }}">Edit</a>
                  <form class="inline" method="post" action="{{ url_for('delete_item', entity='tasks', item_id=task['id']) }}">
                    <button class="btn btn-danger" type="submit">Delete</button>
                  </form>
                </div>
              </div>
              {% endfor %}
              {% if not tasks.bars %}
              <div class="muted">No tasks yet.</div>
              {% endif %}
            </div>

            <div class="calendar" style="margin-top: 16px;">
              <div class="calendar-header">Week</div>
              {% for day in tasks.days %}
              <div class="calendar-header">{{ day.label }}</div>
              {% endfor %}

              <div class="calendar-side">
                Week of {{ tasks.week_label }}
                <div class="muted">Due dates shown in this week.</div>
              </div>
              {% for day in tasks.days %}
              <div class="calendar-day {% if day.is_today %}today{% endif %}">
                <div class="calendar-date">{{ day.date_label }}</div>
                <div class="task-stack">
                  {% for task in day.tasks %}
                  <div class="task-bar {{ task.priority_class }}">
                    <div>
                      {{ task.task }}
                    </div>
                  </div>
                  {% endfor %}
                </div>
              </div>
              {% endfor %}
            </div>
          </div>
          {% else %}
          <div class="section-head">
            <div>
              <h2>{{ card.section.title }}</h2>
              <div class="muted">Manage entries for {{ card.section.title|lower }}.</div>
              <div class="section-hint">Double-click this header to open/close.</div>
            </div>
            {% if card.section.key == "system_status" %}
            {% set status_row = card.section.rows[0] if card.section.rows else None %}
            {% set status_href = url_for('edit_item', entity=card.section.key, item_id=status_row['id']) if status_row else url_for('new_item', entity=card.section.key) %}
            <a class="btn" href="{{ status_href }}">Edit</a>
            {% else %}
            <a class="btn" href="{{ url_for('new_item', entity=card.section.key) }}">Add</a>
            {% endif %}
          </div>
          <div class="section-body">
            {% if card.section.rows %}
            {% set system_online = card.section.key == "system_status" and card.section.rows and card.section.rows[0]['is_online'] in [1, "1", True, "true", "True"] %}
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    {% for field in card.section.fields %}
                    {% if not (card.section.key == "risks" and field == "solution") and not (system_online and field in ["reason", "estimated_downtime"]) %}
                    <th>{{ card.section.labels[field] }}</th>
                    {% endif %}
                    {% endfor %}
                    {% if card.section.key == "documentation" %}
                    <th>Link</th>
                    {% endif %}
                    {% if card.section.key != "system_status" %}
                    <th>Actions</th>
                    {% endif %}
                  </tr>
                </thead>
                <tbody>
                  {% for row in card.section.rows %}
                  <tr
                    {% if card.section.key == "risks" %}
                    class="risk-row"
                    data-risk="{{ (row['risk'] or '')|e }}"
                    data-impact="{{ (row['impact'] or '')|e }}"
                    data-solution="{{ (row['solution'] or '')|e }}"
                    data-status="{{ (row['status'] or '')|e }}"
                    {% endif %}
                  >
                    {% for field in card.section.fields %}
                    {% if not (card.section.key == "risks" and field == "solution") and not (system_online and field in ["reason", "estimated_downtime"]) %}
                    <td>
                      {% if card.section.key == "documentation" and field == "doc_type" %}
                      {% set dtype = (row[field] or "")|lower %}
                      <span class="badge {% if dtype == 'schematic' %}badge-schematic{% elif dtype == 'cad' %}badge-cad{% elif dtype == 'pdf' %}badge-pdf{% endif %}">
                        {{ row[field] or "" }}
                      </span>
                      {% elif card.section.key == "documentation" and field == "location" %}
                      {% if row[field] %}
                      <span class="link-pill valid">Onedrive</span>
                      {% else %}
                      <span class="muted">No link</span>
                      {% endif %}
                      {% elif card.section.key == "bom" and field == "link" %}
                      {% if row[field] %}
                      <a class="btn" href="{{ row[field] }}" target="_blank" rel="noopener">Open</a>
                      {% else %}
                      <span class="muted">No link</span>
                      {% endif %}
                      {% elif card.section.key == "bom" and field == "status" %}
                      {% set status_text = row[field] or "" %}
                      {% set status_key = status_text|lower|replace(" ", "")|replace("-", "") %}
                      <span class="bom-status {% if status_key in ['purchased', 'purchase', 'bought'] %}purchased{% elif status_key in ['nonpurchased', 'notpurchased', 'notyetpurchased', 'unpurchased', 'notbought'] %}not-purchased{% else %}neutral{% endif %}">
                        {{ status_text }}
                      </span>
                      {% elif card.section.key == "system_status" and field == "is_online" %}
                      {% if row[field] in [1, "1", True, "true", "True"] %}
                      <span class="status-pill status-online">Online</span>
                      {% else %}
                      <span class="status-pill status-offline">Offline</span>
                      {% endif %}
                      {% elif card.section.key == "risks" and field == "status" %}
                      {% set status_text = row[field] or "" %}
                      {% set status_key = status_text|lower|replace(" ", "")|replace("-", "") %}
                      <span class="risk-status {% if status_key in ['ongoing', 'inprogress'] %}risk-ongoing{% elif status_key == 'resolved' %}risk-resolved{% else %}risk-neutral{% endif %}">
                        {{ status_text }}
                      </span>
                      {% else %}
                      {{ row[field] or "" }}
                      {% endif %}
                    </td>
                    {% endif %}
                    {% endfor %}
                    {% if card.section.key == "documentation" %}
                    <td>
                      {% if row.location %}
                      <a class="btn" href="{{ row.location }}" target="_blank" rel="noopener">Open</a>
                      {% else %}
                      <span class="muted">No link</span>
                      {% endif %}
                    </td>
                    {% endif %}
                    {% if card.section.key != "system_status" %}
                    <td>
                      <a href="{{ url_for('edit_item', entity=card.section.key, item_id=row['id']) }}">Edit</a>
                      <form class="inline" method="post" action="{{ url_for('delete_item', entity=card.section.key, item_id=row['id']) }}">
                        <button class="btn btn-danger" type="submit">Delete</button>
                      </form>
                    </td>
                    {% endif %}
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
            {% else %}
            <div class="muted">No entries yet.</div>
            {% endif %}
          </div>
          {% endif %}
        </section>
        {% endfor %}
      </div>
    </main>
    <div class="modal" id="riskModal" aria-hidden="true">
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="riskModalTitle">
        <div class="modal-head">
          <h3 class="modal-title" id="riskModalTitle">Risk details</h3>
          <button class="modal-close" type="button" id="riskModalClose">Close</button>
        </div>
        <div class="modal-section">
          <div class="modal-label">Risk</div>
          <div class="modal-body" id="riskModalRisk"></div>
        </div>
        <div class="modal-section">
          <div class="modal-label">Impact</div>
          <div class="modal-body" id="riskModalImpact"></div>
        </div>
        <div class="modal-section">
          <div class="modal-label">Solution</div>
          <div class="modal-body" id="riskModalSolution"></div>
        </div>
        <div class="modal-section">
          <div class="modal-label">Status</div>
          <div class="modal-body" id="riskModalStatus"></div>
        </div>
      </div>
    </div>
    <script>
      const cardList = document.getElementById("cardList");

      document.querySelectorAll("#cardList .section-head").forEach((header) => {
        header.addEventListener("dblclick", () => {
          const card = header.closest("section.card");
          if (card) {
            card.classList.toggle("collapsed");
          }
        });
      });

      function saveOrder() {
        const order = Array.from(cardList.querySelectorAll("section.card")).map((card) => card.dataset.key);
        fetch("{{ url_for('update_card_order') }}", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order }),
        });
      }

      cardList.querySelectorAll("section.card").forEach((card) => {
        card.addEventListener("dragstart", (event) => {
          if (event.target.closest("button, a, input, textarea, select, form")) {
            event.preventDefault();
            return;
          }
          card.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
        });

        card.addEventListener("dragend", () => {
          card.classList.remove("dragging");
          saveOrder();
        });

        card.addEventListener("dragover", (event) => {
          event.preventDefault();
          const dragging = cardList.querySelector(".dragging");
          if (!dragging || dragging === card) {
            return;
          }
          const rect = card.getBoundingClientRect();
          const next = event.clientY - rect.top > rect.height / 2;
          cardList.insertBefore(dragging, next ? card.nextSibling : card);
        });
      });

      const riskModal = document.getElementById("riskModal");
      const riskModalClose = document.getElementById("riskModalClose");
      const riskModalRisk = document.getElementById("riskModalRisk");
      const riskModalImpact = document.getElementById("riskModalImpact");
      const riskModalSolution = document.getElementById("riskModalSolution");
      const riskModalStatus = document.getElementById("riskModalStatus");

      function openRiskModal(row) {
        if (!riskModal) {
          return;
        }
        riskModalRisk.textContent = row.dataset.risk || "";
        riskModalImpact.textContent = row.dataset.impact || "";
        riskModalSolution.textContent = row.dataset.solution || "";
        riskModalStatus.textContent = row.dataset.status || "";
        riskModal.classList.add("open");
        riskModal.setAttribute("aria-hidden", "false");
      }

      function closeRiskModal() {
        if (!riskModal) {
          return;
        }
        riskModal.classList.remove("open");
        riskModal.setAttribute("aria-hidden", "true");
      }

      document.querySelectorAll(".risk-row").forEach((row) => {
        row.addEventListener("dblclick", () => openRiskModal(row));
      });

      if (riskModalClose) {
        riskModalClose.addEventListener("click", closeRiskModal);
      }

      if (riskModal) {
        riskModal.addEventListener("click", (event) => {
          if (event.target === riskModal) {
            closeRiskModal();
          }
        });
      }

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeRiskModal();
        }
      });
    </script>
  </body>
</html>
"""

PROGRESS_FORM_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ title }}</title>
    <style>
      :root {
        --bg: #f5f2ec;
        --ink: #1f2a2e;
        --muted: #5c6b73;
        --card: #ffffff;
        --border: #e3ddd1;
        --accent: #2c6e63;
        --shadow: 0 18px 40px rgba(32, 41, 40, 0.12);
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        font-family: "Avenir Next", "Optima", "Gill Sans", "Trebuchet MS", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at top left, #ffffff 0%, var(--bg) 55%);
      }

      h1 {
        font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        margin: 0 0 16px;
      }

      .page {
        max-width: 720px;
        margin: 0 auto;
        padding: 32px 20px 60px;
      }

      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        box-shadow: var(--shadow);
      }

      form { display: grid; gap: 16px; }
      label { font-weight: 600; display: block; margin-bottom: 6px; }
      input, textarea, select {
        width: 100%;
        padding: 12px 14px;
        border: 1px solid #cfc7b7;
        border-radius: 10px;
        font-size: 14px;
        background: #fffdf9;
      }
      select {
        font-size: 15px;
        border-radius: 12px;
        border-color: #c2b9a8;
        background-color: #fffaf1;
        color: var(--ink);
        appearance: none;
        background-image:
          linear-gradient(45deg, transparent 50%, #6e6a5f 50%),
          linear-gradient(135deg, #6e6a5f 50%, transparent 50%),
          linear-gradient(to right, #e3ddd1, #e3ddd1);
        background-position:
          calc(100% - 20px) 50%,
          calc(100% - 14px) 50%,
          calc(100% - 36px) 50%;
        background-size: 7px 7px, 7px 7px, 1px 60%;
        background-repeat: no-repeat;
        padding-right: 48px;
        box-shadow: 0 6px 14px rgba(32, 41, 40, 0.08);
      }
      .toggle-row {
        display: grid;
        gap: 10px;
        width: 100%;
      }
      .status-toggle {
        display: grid;
        grid-template-columns: 1fr;
        row-gap: 50px;
        width: 100%;
        min-height: 52px;
      }
      .status-btn {
        width: 100%;
        border: 1px solid var(--border);
        background: #f1ede3;
        color: var(--muted);
        padding: 14px 22px;
        border-radius: 999px;
        font-size: 14px;
        cursor: pointer;
        text-align: center;
        min-height: 46px;
        appearance: none;
        -webkit-appearance: none;
        box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.04);
      }
      .status-btn.active {
        background: #e1efe9;
        border-color: #b9d9ce;
        color: var(--accent);
        font-weight: 600;
      }
      .status-btn.online.active {
        background: #dff6e6;
        border-color: #a9e2bb;
        color: #1f6b46;
      }
      .status-btn.offline.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .offline-only { display: none; }
      textarea { min-height: 120px; }
      .range-row {
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: center;
        gap: 12px;
      }
      .range-value {
        min-width: 64px;
        text-align: right;
        font-weight: 600;
      }
      .phase-track {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 6px;
        margin-top: 6px;
      }
      .phase-step {
        text-align: center;
        font-size: 11px;
        padding: 6px 4px;
        border-radius: 999px;
        background: #f1ede3;
        color: var(--muted);
        border: 1px solid var(--border);
        cursor: pointer;
        appearance: none;
      }
      .phase-step.active {
        background: #e1efe9;
        color: var(--accent);
        border-color: #b9d9ce;
        font-weight: 600;
      }
      .toggle-row {
        display: grid;
        gap: 10px;
        width: 100%;
      }
      .status-toggle {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        width: 100%;
        min-height: 52px;
      }
      .status-btn {
        width: 100%;
        border: 1px solid var(--border);
        background: #f1ede3;
        color: var(--muted);
        padding: 14px 22px;
        border-radius: 999px;
        font-size: 14px;
        cursor: pointer;
        text-align: center;
        min-height: 46px;
        appearance: none;
        -webkit-appearance: none;
        box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.04);
      }
      .status-btn.active {
        background: #e1efe9;
        border-color: #b9d9ce;
        color: var(--accent);
        font-weight: 600;
      }
      .status-btn.online.active {
        background: #dff6e6;
        border-color: #a9e2bb;
        color: #1f6b46;
      }
      .status-btn.offline.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .offline-only { display: none; }
      .actions { display: flex; gap: 8px; }
      .btn {
        border: 1px solid var(--border);
        background: #f7f4ee;
        padding: 8px 12px;
        border-radius: 10px;
        cursor: pointer;
        text-decoration: none;
        color: var(--ink);
        font-size: 14px;
      }
      .btn.primary { background: linear-gradient(120deg, var(--accent), #3f8b7e); color: #fff; border: none; }
    </style>
  </head>
  <body data-entity="{{ entity or '' }}">
    <main class="page">
      <div class="card">
        <h1>{{ title }}</h1>
        <form method="post">
          <div>
            <label>Phase</label>
            <input type="hidden" id="phase" name="phase" value="{{ values.phase }}" />
            <input type="hidden" id="percent" name="percent" value="{{ values.percent or 0 }}" />
            <div class="phase-track">
              {% for phase in phases %}
              <button
                type="button"
                class="phase-step {% if values.phase == phase %}active{% endif %}"
                data-phase="{{ phase }}"
                data-percent="{{ phase_map[phase] }}"
              >
                {{ phase }}
              </button>
              {% endfor %}
            </div>
            <div class="range-row" style="margin-top: 10px;">
              <div class="muted">Progress</div>
              <div class="range-value" id="percentValue">{{ values.percent or 0 }}%</div>
            </div>
          </div>
          <div class="log-head">
            <div>
              <div class="progress-title">Development log</div>
              <div class="muted">Add or review daily updates.</div>
            </div>
            <div class="actions">
              <a class="btn" href="{{ url_for('new_item', entity='development_log') }}">Add log</a>
              <a class="btn" href="{{ url_for('index') }}#development-log">View logs</a>
            </div>
          </div>
          <div class="actions">
            <button class="btn primary" type="submit">Save</button>
            <a class="btn" href="{{ url_for('index') }}">Cancel</a>
          </div>
        </form>
      </div>
    </main>
    <script>
      const phaseMap = {{ phase_map | tojson }};
      const phaseInput = document.getElementById("phase");
      const percentInput = document.getElementById("percent");
      const percentValue = document.getElementById("percentValue");
      const phaseButtons = document.querySelectorAll(".phase-step");

      function updatePercentLabel() {
        percentValue.textContent = `${percentInput.value}%`;
      }

      function setActivePhase(phase) {
        phaseInput.value = phase;
        phaseButtons.forEach((step) => {
          step.classList.toggle("active", step.dataset.phase === phase);
        });
      }

      function nearestPhase(value) {
        let nearest = "";
        let distance = Infinity;
        Object.entries(phaseMap).forEach(([phase, percent]) => {
          const diff = Math.abs(value - percent);
          if (diff < distance) {
            distance = diff;
            nearest = phase;
          }
        });
        return nearest;
      }

      function syncPhaseFromPercent() {
        const percent = parseInt(percentInput.value, 10);
        const phase = nearestPhase(percent);
        if (phase) {
          setActivePhase(phase);
        }
      }

      phaseButtons.forEach((button) => {
        button.addEventListener("click", () => {
          const selected = button.dataset.phase;
          const percent = button.dataset.percent;
          if (phaseMap[selected] !== undefined) {
            percentInput.value = percent;
            updatePercentLabel();
            setActivePhase(selected);
          }
        });
      });

      updatePercentLabel();
      if (!phaseInput.value) {
        syncPhaseFromPercent();
      } else {
        setActivePhase(phaseInput.value);
      }
    </script>
  </body>
</html>
"""

FORM_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ title }}</title>
    <style>
      :root {
        --bg: #f5f2ec;
        --ink: #1f2a2e;
        --muted: #5c6b73;
        --card: #ffffff;
        --border: #e3ddd1;
        --accent: #2c6e63;
        --shadow: 0 18px 40px rgba(32, 41, 40, 0.12);
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        font-family: "Avenir Next", "Optima", "Gill Sans", "Trebuchet MS", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at top left, #ffffff 0%, var(--bg) 55%);
      }

      h1 {
        font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        margin: 0 0 16px;
      }

      .page {
        max-width: 720px;
        margin: 0 auto;
        padding: 32px 20px 60px;
      }

      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        box-shadow: var(--shadow);
      }

      form { display: grid; gap: 14px; }
      label { font-weight: 600; }
      input, textarea {
        width: 100%;
        padding: 10px;
        border: 1px solid #cfc7b7;
        border-radius: 8px;
        font-size: 14px;
        background: #fffdf9;
      }
      textarea { min-height: 120px; }
      .toggle-row {
        display: grid;
        gap: 10px;
        width: 100%;
      }
      .status-toggle {
        display: grid;
        gap: 12px;
        width: 100%;
      }
      .choice-toggle {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 10px;
        width: 100%;
      }
      .choice-btn {
        border: 1px solid var(--border);
        background: #f1ede3;
        color: var(--muted);
        padding: 12px 14px;
        border-radius: 999px;
        font-size: 14px;
        cursor: pointer;
        text-align: center;
        min-height: 44px;
        appearance: none;
        -webkit-appearance: none;
        box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.04);
      }
      .choice-btn.active {
        background: #e1efe9;
        border-color: #b9d9ce;
        color: var(--accent);
        font-weight: 600;
      }
      .choice-btn.priority-high.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .choice-btn.priority-medium.active {
        background: #fff0d9;
        border-color: #f1caa0;
        color: #8a5a12;
      }
      .choice-btn.priority-low.active {
        background: #e9f6ef;
        border-color: #b7dec7;
        color: #1f6b46;
      }
      .choice-btn.status-not-started.active {
        background: #fff0d9;
        border-color: #f1caa0;
        color: #8a5a12;
      }
      .choice-btn.status-progress.active {
        background: #e7f0ff;
        border-color: #b9cdee;
        color: #2b4b7a;
      }
      .choice-btn.status-done.active {
        background: #e9f6ef;
        border-color: #b7dec7;
        color: #1f6b46;
      }
      .choice-btn.risk-ongoing.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .choice-btn.risk-resolved.active {
        background: #e9f6ef;
        border-color: #b7dec7;
        color: #1f6b46;
      }
      .choice-btn.bom-purchased.active {
        background: #e6f0ff;
        border-color: #bcd3ff;
        color: #2b4d8b;
      }
      .choice-btn.bom-not-yet.active {
        background: #ffe5e5;
        border-color: #f0b1b1;
        color: #8b2f2f;
      }
      .actions { display: flex; gap: 8px; }
      .btn {
        border: 1px solid var(--border);
        background: #f7f4ee;
        padding: 8px 12px;
        border-radius: 10px;
        cursor: pointer;
        text-decoration: none;
        color: var(--ink);
        font-size: 14px;
      }
      .btn.primary { background: linear-gradient(120deg, var(--accent), #3f8b7e); color: #fff; border: none; }
      a { color: #1b4b7a; text-decoration: none; }
      a:hover { text-decoration: underline; }
    </style>
  </head>
  <body>
    <main class="page">
      <div class="card">
        <h1>{{ title }}</h1>
        <form method="post">
          {% set online = values.get('is_online') in ['1', 1, True, 'true', 'True'] %}
          {% for field in fields %}
          <div
            class="field-block {% if entity == 'system_status' and field.name in ['reason', 'estimated_downtime'] %}offline-only{% endif %}"
            {% if entity == 'system_status' and field.name in ['reason', 'estimated_downtime'] %}
            style="display: {{ 'none' if online else 'block' }};"
            {% endif %}
          >
            <label for="{{ field.name }}">{{ field.label }}</label>
            {% if field.widget == 'textarea' %}
            <textarea id="{{ field.name }}" name="{{ field.name }}">{{ values.get(field.name, "") }}</textarea>
            {% elif entity == "system_status" and field.name == "is_online" %}
            <div class="toggle-row">
              <input id="is_online" name="is_online" type="hidden" value="{{ 1 if online else 0 }}" />
              <div class="status-toggle" role="group" aria-label="System status">
                <button
                  type="button"
                  class="status-btn online {% if online %}active{% endif %}"
                  data-value="1"
                  style="width:100%; padding:14px 22px; min-height:46px; border-radius:999px; border:1px solid {{ '#a9e2bb' if online else 'var(--border)' }}; background: {{ '#dff6e6' if online else '#f1ede3' }}; color: {{ '#1f6b46' if online else 'var(--muted)' }};"
                  onclick="setSystemStatus('1')"
                >
                  Online
                </button>
                <button
                  type="button"
                  class="status-btn offline {% if not online %}active{% endif %}"
                  data-value="0"
                  style="width:100%; padding:14px 22px; min-height:46px; border-radius:999px; border:1px solid {{ '#f0b1b1' if not online else 'var(--border)' }}; background: {{ '#ffe5e5' if not online else '#f1ede3' }}; color: {{ '#8b2f2f' if not online else 'var(--muted)' }};"
                  onclick="setSystemStatus('0')"
                >
                  Offline
                </button>
              </div>
            </div>
            {% elif entity == "tasks" and field.name in ["priority", "status"] %}
            {% set current_value = values.get(field.name, "") or "" %}
            {% if field.name == "priority" %}
            {% set options = ["High", "Medium", "Low"] %}
            {% else %}
            {% set options = ["Not started", "In progress", "Done"] %}
            {% endif %}
            <div class="toggle-row">
              <input id="{{ field.name }}" name="{{ field.name }}" type="hidden" value="{{ current_value }}" />
              <div class="choice-toggle" data-target="{{ field.name }}" role="group" aria-label="{{ field.label }}">
                {% for option in options %}
                <button
                  type="button"
                  class="choice-btn{% if field.name == 'priority' %} priority-{{ option|lower }}{% endif %}{% if current_value|lower == option|lower %} active{% endif %}"
                  data-value="{{ option }}"
                >
                  {{ option }}
                </button>
                {% endfor %}
              </div>
            </div>
            {% elif entity == "bom" and field.name == "status" %}
            {% set current_value = values.get(field.name, "") or "" %}
            {% set status_key = current_value|lower|replace(" ", "")|replace("-", "") %}
            {% if status_key in ["purchased", "purchase", "bought"] %}
            {% set current_value = "Purchased" %}
            {% elif status_key in ["notyetpurchased", "notpurchased", "nonpurchased", "unpurchased", "notbought"] %}
            {% set current_value = "Not yet purchased" %}
            {% endif %}
            {% set options = ["Not yet purchased", "Purchased"] %}
            <div class="toggle-row">
              <input id="{{ field.name }}" name="{{ field.name }}" type="hidden" value="{{ current_value }}" />
              <div class="choice-toggle" data-target="{{ field.name }}" role="group" aria-label="{{ field.label }}">
                {% for option in options %}
                {% if option == "Purchased" %}
                {% set status_class = "bom-purchased" %}
                {% else %}
                {% set status_class = "bom-not-yet" %}
                {% endif %}
                <button
                  type="button"
                  class="choice-btn {{ status_class }}{% if current_value|lower == option|lower %} active{% endif %}"
                  data-value="{{ option }}"
                >
                  {{ option }}
                </button>
                {% endfor %}
              </div>
            </div>
            {% elif entity == "risks" and field.name == "status" %}
            {% set current_value = values.get(field.name, "") or "" %}
            {% set options = ["Ongoing", "Resolved"] %}
            <div class="toggle-row">
              <input id="{{ field.name }}" name="{{ field.name }}" type="hidden" value="{{ current_value }}" />
              <div class="choice-toggle" data-target="{{ field.name }}" role="group" aria-label="{{ field.label }}">
                {% for option in options %}
                <button
                  type="button"
                  class="choice-btn risk-{{ option|lower }}{% if current_value|lower == option|lower %} active{% endif %}"
                  data-value="{{ option }}"
                >
                  {{ option }}
                </button>
                {% endfor %}
              </div>
            </div>
            {% elif entity == "documentation" and field.name == "status" %}
            {% set current_value = values.get(field.name, "") or "" %}
            {% set options = ["Not started", "In progress", "Done"] %}
            <div class="toggle-row">
              <input id="{{ field.name }}" name="{{ field.name }}" type="hidden" value="{{ current_value }}" />
              <div class="choice-toggle" data-target="{{ field.name }}" role="group" aria-label="{{ field.label }}">
                {% for option in options %}
                {% if option == "Not started" %}
                {% set status_class = "status-not-started" %}
                {% elif option == "In progress" %}
                {% set status_class = "status-progress" %}
                {% else %}
                {% set status_class = "status-done" %}
                {% endif %}
                <button
                  type="button"
                  class="choice-btn {{ status_class }}{% if current_value|lower == option|lower %} active{% endif %}"
                  data-value="{{ option }}"
                >
                  {{ option }}
                </button>
                {% endfor %}
              </div>
            </div>
            {% else %}
            <input
              id="{{ field.name }}"
              name="{{ field.name }}"
              type="{{ field.input_type or 'text' }}"
              value="{{ values.get(field.name, "") }}"
              {% if field.step %}step="{{ field.step }}"{% endif %}
            />
            {% endif %}
            {% if entity == "documentation" and field.name == "location" %}
            <span class="link-pill" id="onedrivePill">Paste OneDrive link</span>
            {% endif %}
          </div>
          {% endfor %}
          <div class="actions">
            <button class="btn primary" type="submit">Save</button>
            <a class="btn" href="{{ url_for('index') }}">Cancel</a>
          </div>
        </form>
      </div>
    </main>
    <script>
      const entity = document.body.dataset.entity;
      if (entity === "documentation") {
        const input = document.querySelector("input[name='location']");
        if (input) {
          const pill = document.getElementById("onedrivePill") || document.createElement("span");
          if (!pill.id) {
            pill.id = "onedrivePill";
            pill.className = "link-pill";
            pill.textContent = "Paste OneDrive link";
            input.parentElement.appendChild(pill);
          }

          function isOneDriveUrl(url) {
            try {
              const parsed = new URL(url);
              return (
                parsed.hostname.includes("1drv.ms") ||
                parsed.hostname.includes("onedrive.live.com") ||
                parsed.hostname.includes("sharepoint.com")
              );
            } catch {
              return false;
            }
          }

          function update() {
            const value = input.value.trim();
            if (!value) {
              pill.className = "link-pill";
              pill.textContent = "Paste OneDrive link";
              return;
            }
            if (isOneDriveUrl(value)) {
              pill.className = "link-pill valid";
              pill.textContent = "OneDrive link";
            } else {
              pill.className = "link-pill invalid";
              pill.textContent = "Not OneDrive";
            }
          }

          input.addEventListener("input", update);
          update();
        }
      }

      function initChoiceToggles() {
        document.querySelectorAll(".choice-toggle").forEach((toggle) => {
          const target = toggle.dataset.target;
          const hidden = document.getElementById(target);
          const buttons = toggle.querySelectorAll(".choice-btn");
          if (!buttons.length) {
            return;
          }

          const setValue = (value) => {
            if (hidden) {
              hidden.value = value;
            }
            buttons.forEach((btn) => {
              btn.classList.toggle("active", btn.dataset.value === value);
            });
          };

          buttons.forEach((btn) => {
            btn.addEventListener("click", () => setValue(btn.dataset.value));
          });

          if (hidden && hidden.value) {
            setValue(hidden.value);
          } else {
            setValue(buttons[0].dataset.value);
          }
        });
      }

      initChoiceToggles();

      function setSystemStatus(value) {
        const hidden = document.getElementById("is_online");
        const offlineOnly = document.querySelectorAll(".offline-only");
        const buttons = document.querySelectorAll(".status-btn");
        const online = value === "1";

        if (hidden) {
          hidden.value = online ? "1" : "0";
        }

        buttons.forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.value === (online ? "1" : "0"));
          if (btn.dataset.value === "1") {
            btn.style.borderColor = online ? "#a9e2bb" : "var(--border)";
            btn.style.background = online ? "#dff6e6" : "#f1ede3";
            btn.style.color = online ? "#1f6b46" : "var(--muted)";
          } else {
            btn.style.borderColor = online ? "var(--border)" : "#f0b1b1";
            btn.style.background = online ? "#f1ede3" : "#ffe5e5";
            btn.style.color = online ? "var(--muted)" : "#8b2f2f";
          }
        });

        offlineOnly.forEach((block) => {
          block.style.display = online ? "none" : "block";
        });
      }

      if (entity === "system_status") {
        const hidden = document.getElementById("is_online");
        if (hidden) {
          setSystemStatus(hidden.value === "1" ? "1" : "0");
        }
      }
    </script>
  </body>
</html>
"""


def ensure_column(db: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS project (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            owner TEXT,
            phase TEXT,
            target_release TEXT
        );
        CREATE TABLE IF NOT EXISTS bom (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT,
            part_number TEXT,
            qty INTEGER,
            unit_cost REAL,
            supplier TEXT,
            lead_time_days INTEGER,
            status TEXT,
            link TEXT
        );
        CREATE TABLE IF NOT EXISTS documentation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            doc_type TEXT,
            owner TEXT,
            location TEXT,
            status TEXT,
            last_updated TEXT
        );
        CREATE TABLE IF NOT EXISTS system_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_online INTEGER,
            reason TEXT,
            estimated_downtime TEXT
        );
        CREATE TABLE IF NOT EXISTS development_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            percent INTEGER,
            phase TEXT,
            status_text TEXT
        );
        CREATE TABLE IF NOT EXISTS development_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT,
            summary TEXT,
            details TEXT
        );
        CREATE TABLE IF NOT EXISTS card_state (
            key TEXT PRIMARY KEY,
            position INTEGER,
            pinned INTEGER
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            owner TEXT,
            due_date TEXT,
            priority TEXT,
            status TEXT
        );
        CREATE TABLE IF NOT EXISTS risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk TEXT,
            impact TEXT,
            solution TEXT,
            owner TEXT,
            status TEXT
        );
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO project (id, name, owner, phase, target_release) VALUES (1, '', '', '', '')"
    )
    ensure_column(db, "development_progress", "percent", "INTEGER")
    ensure_column(db, "development_progress", "phase", "TEXT")
    ensure_column(db, "development_progress", "status_text", "TEXT")
    ensure_column(db, "system_status", "is_online", "INTEGER")
    ensure_column(db, "tasks", "due_date", "TEXT")
    ensure_column(db, "tasks", "priority", "TEXT")
    ensure_column(db, "bom", "link", "TEXT")
    ensure_column(db, "risks", "solution", "TEXT")
    db.execute(
        "INSERT OR IGNORE INTO development_progress (id, percent, phase, status_text) VALUES (1, NULL, '', '')"
    )
    for position, key in enumerate(CARD_KEYS):
        db.execute(
            "INSERT OR IGNORE INTO card_state (key, position, pinned) VALUES (?, ?, 0)",
            (key, position),
        )
    db.commit()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        init_db(db)
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(exc: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def fetch_project() -> Dict[str, str]:
    row = get_db().execute("SELECT * FROM project WHERE id = 1").fetchone()
    if row is None:
        return {"name": "", "phase": ""}
    return dict(row)


def fetch_development_progress() -> Dict[str, object]:
    row = get_db().execute("SELECT * FROM development_progress WHERE id = 1").fetchone()
    if row is None:
        return {"percent": None, "phase": "", "status_text": ""}
    return dict(row)


def fetch_all(entity: str) -> List[Dict[str, object]]:
    if entity == "development_log":
        query = "SELECT * FROM development_log ORDER BY log_date DESC, id DESC"
        rows = get_db().execute(query).fetchall()
    else:
        rows = get_db().execute(f"SELECT * FROM {entity} ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def entity_or_404(entity: str) -> Dict[str, object]:
    if entity not in ENTITY_DEFS or entity == "project":
        abort(404)
    return ENTITY_DEFS[entity]


def collect_form_data(fields: List[Dict[str, object]]) -> Dict[str, object]:
    data: Dict[str, object] = {}
    for field in fields:
        name = field["name"]
        if name == "is_online":
            data[name] = 1 if request.form.get(name) in {"1", "true", "True", "on"} else 0
        else:
            data[name] = request.form.get(name, "").strip()
    return data


def empty_values(fields: List[Dict[str, object]]) -> Dict[str, str]:
    return {field["name"]: "" for field in fields}


def default_values_for(entity: str, fields: List[Dict[str, object]]) -> Dict[str, str]:
    values = empty_values(fields)
    if entity == "development_log":
        values["log_date"] = datetime.now().strftime("%Y-%m-%d")
    if entity == "tasks":
        values["priority"] = "Medium"
    if entity == "documentation":
        values["status"] = "Not started"
    if entity == "bom":
        values["status"] = "Not yet purchased"
    if entity == "risks":
        values["status"] = "Ongoing"
    if entity == "system_status":
        values["is_online"] = "1"
    return values


def parse_percent(value: object) -> float | None:
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, percent))


def parse_date(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def priority_class(value: object) -> str:
    text = str(value or "").strip().lower()
    if text == "high":
        return "priority-high"
    if text == "low":
        return "priority-low"
    return "priority-medium"


def task_status_class(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"done", "complete", "completed"}:
        return "status-done"
    if text in {"in progress", "in-progress", "inprogress"}:
        return "status-progress"
    return "status-not-started"


def normalize_phase(value: object) -> str:
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


def build_development_view() -> Dict[str, object]:
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


def build_tasks_view() -> Dict[str, object]:
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    day_map = {day: [] for day in days}

    tasks = fetch_all("tasks")
    bars: List[Dict[str, object]] = []
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

    def sort_key(item: Dict[str, object]) -> tuple:
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
    rows = get_db().execute("SELECT key, position, pinned FROM card_state").fetchall()
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


def build_cards(sections: List[Dict[str, object]]) -> List[Dict[str, object]]:
    state = fetch_card_state()
    sections_map = {section["key"]: section for section in sections}
    cards: List[Dict[str, object]] = []
    for key in ordered_card_keys():
        pinned = bool(state.get(key, {}).get("pinned"))
        if key == "development_progress":
            cards.append({"key": key, "type": "progress", "pinned": pinned})
        elif key == "tasks":
            cards.append({"key": key, "type": "tasks", "pinned": pinned})
        elif key in sections_map:
            cards.append({"key": key, "type": "section", "section": sections_map[key], "pinned": pinned})
    return cards


def build_sections() -> List[Dict[str, object]]:
    sections: List[Dict[str, object]] = []
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


@app.route("/")
def index() -> str:
    project = fetch_project()
    sections = build_sections()
    return render_template_string(
        HOME_TEMPLATE,
        project=project,
        development=build_development_view(),
        phases=PHASES,
        logs=fetch_all("development_log"),
        tasks=build_tasks_view(),
        cards=build_cards(sections),
        sections=sections,
        updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/project/edit", methods=["GET", "POST"])
def edit_project() -> str:
    definition = ENTITY_DEFS["project"]
    project = fetch_project()
    if request.method == "POST":
        data = collect_form_data(definition["fields"])
        get_db().execute(
            "UPDATE project SET name = ? WHERE id = 1",
            (data["name"],),
        )
        get_db().commit()
        return redirect(url_for("index"))
    return render_template_string(
        FORM_TEMPLATE,
        title="Edit Project",
        fields=definition["fields"],
        values=project,
        entity="project",
    )


@app.route("/progress/edit", methods=["GET", "POST"])
def edit_progress() -> str:
    progress = fetch_development_progress()
    phase_value = normalize_phase(progress.get("phase"))
    percent_value = progress.get("percent")
    if percent_value is None and phase_value in PHASE_TO_PERCENT:
        percent_value = PHASE_TO_PERCENT[phase_value]
    if percent_value is not None and not phase_value:
        phase_value = phase_from_percent(percent_value)
    values = {
        "percent": 0 if percent_value is None else percent_value,
        "phase": phase_value,
    }
    if request.method == "POST":
        percent = parse_percent(request.form.get("percent"))
        phase = normalize_phase(request.form.get("phase"))
        if percent is None and phase in PHASE_TO_PERCENT:
            percent = PHASE_TO_PERCENT[phase]
        if percent is not None and not phase:
            phase = phase_from_percent(percent)
        percent_value = int(round(percent)) if percent is not None else None
        get_db().execute(
            "INSERT OR IGNORE INTO development_progress (id, percent, phase, status_text) VALUES (1, NULL, '', '')"
        )
        get_db().execute(
            "UPDATE development_progress SET percent = ?, phase = ?, status_text = ? WHERE id = 1",
            (percent_value, phase, ""),
        )
        if phase:
            get_db().execute("UPDATE project SET phase = ? WHERE id = 1", (phase,))
        get_db().commit()
        return redirect(url_for("index"))
    return render_template_string(
        PROGRESS_FORM_TEMPLATE,
        title="Edit Development Progress",
        values=values,
        phases=PHASES,
        phase_map=PHASE_TO_PERCENT,
    )


@app.route("/new/<entity>", methods=["GET", "POST"])
def new_item(entity: str) -> str:
    definition = entity_or_404(entity)
    if request.method == "POST":
        data = collect_form_data(definition["fields"])
        if entity == "documentation":
            data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        get_db().execute(
            f"INSERT INTO {entity} ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        get_db().commit()
        return redirect(url_for("index"))
    return render_template_string(
        FORM_TEMPLATE,
        title=f"Add {definition['label']} item",
        fields=definition["fields"],
        values=default_values_for(entity, definition["fields"]),
        entity=entity,
    )


@app.route("/edit/<entity>/<int:item_id>", methods=["GET", "POST"])
def edit_item(entity: str, item_id: int) -> str:
    definition = entity_or_404(entity)
    row = get_db().execute(f"SELECT * FROM {entity} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        abort(404)
    values = dict(row)
    if request.method == "POST":
        data = collect_form_data(definition["fields"])
        if entity == "documentation":
            data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        assignments = ", ".join(f"{key} = ?" for key in data)
        get_db().execute(
            f"UPDATE {entity} SET {assignments} WHERE id = ?",
            list(data.values()) + [item_id],
        )
        get_db().commit()
        return redirect(url_for("index"))
    return render_template_string(
        FORM_TEMPLATE,
        title=f"Edit {definition['label']} item",
        fields=definition["fields"],
        values=values,
        entity=entity,
    )


@app.route("/delete/<entity>/<int:item_id>", methods=["POST"])
def delete_item(entity: str, item_id: int):
    entity_or_404(entity)
    get_db().execute(f"DELETE FROM {entity} WHERE id = ?", (item_id,))
    get_db().commit()
    return redirect(url_for("index"))


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


@app.route("/api/cards/order", methods=["POST"])
def update_card_order():
    payload = request.get_json(silent=True) or {}
    order = payload.get("order") or []
    if not isinstance(order, list):
        abort(400)
    for position, key in enumerate(order):
        if key not in CARD_KEYS:
            continue
        get_db().execute(
            "INSERT OR IGNORE INTO card_state (key, position, pinned) VALUES (?, ?, 0)",
            (key, position),
        )
        get_db().execute(
            "UPDATE card_state SET position = ? WHERE key = ?",
            (position, key),
        )
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/cards/pin", methods=["POST"])
def update_card_pin():
    payload = request.get_json(silent=True) or {}
    key = payload.get("key")
    pinned = payload.get("pinned")
    if key not in CARD_KEYS:
        abort(400)
    value = 1 if pinned else 0
    get_db().execute(
        "INSERT OR IGNORE INTO card_state (key, position, pinned) VALUES (?, 0, ?)",
        (key, value),
    )
    get_db().execute(
        "UPDATE card_state SET pinned = ? WHERE key = ?",
        (value, key),
    )
    get_db().commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
