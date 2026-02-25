from __future__ import annotations

import ast
import importlib.util
import os
import pkgutil
from typing import Any

import requests
from flask import Flask, jsonify, request

# Python 3.14 compatibility: legacy AST node aliases removed.
if not hasattr(ast, "Str"):
    ast.Str = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Bytes"):
    ast.Bytes = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Num"):
    ast.Num = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "NameConstant"):
    ast.NameConstant = ast.Constant  # type: ignore[attr-defined]

# Provide legacy ast.Constant attribute access expected by older Werkzeug code.
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

# Flask compatibility for Python 3.14 where pkgutil.get_loader was removed.
if not hasattr(pkgutil, "get_loader"):
    def _get_loader(name: str):
        try:
            spec = importlib.util.find_spec(name)
        except (ValueError, ImportError):
            return None
        return spec.loader if spec else None

    pkgutil.get_loader = _get_loader  # type: ignore[attr-defined]

app = Flask(__name__)


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
        app.logger.exception("Failed to read %s", path)


load_dotenv()

AZURE_TIMEOUT_SECONDS = float(os.environ.get("AZURE_TIMEOUT_SECONDS", "5"))
CORS_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
}


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def azure_json_request(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[Any, int]:
    try:
        response = requests.request(method, url, json=payload, timeout=AZURE_TIMEOUT_SECONDS)
    except requests.RequestException:
        app.logger.exception("Azure relay request failed")
        return {"error": "Azure relay is unavailable"}, 502

    try:
        body: Any = response.json()
    except ValueError:
        body = {"raw": response.text}

    if response.status_code >= 400:
        return {
            "error": "Azure relay returned an error",
            "status": response.status_code,
            "response": body,
        }, response.status_code

    return body, response.status_code


def cors_origin_for_request() -> str | None:
    origin = request.headers.get("Origin")
    if not origin:
        return None
    if "*" in CORS_ALLOWED_ORIGINS:
        return "*"
    if origin in CORS_ALLOWED_ORIGINS:
        return origin
    return None


@app.before_request
def api_cors_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return "", 204


@app.after_request
def add_api_cors_headers(response):
    if not request.path.startswith("/api/"):
        return response

    origin = cors_origin_for_request()
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        if origin != "*":
            response.headers["Vary"] = "Origin"

    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


@app.route("/api/telemetry", methods=["GET"])
def api_telemetry():
    try:
        url = required_env("AZ_TELEMETRY_URL")
    except RuntimeError:
        app.logger.exception("AZ_TELEMETRY_URL is missing")
        return jsonify({"error": "Server is not configured for telemetry relay"}), 500

    body, status = azure_json_request("GET", url)
    return jsonify(body), status


@app.route("/api/command", methods=["POST"])
def api_command():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object body"}), 400

    cmd_type = payload.get("type")
    if not isinstance(cmd_type, str) or not cmd_type.strip():
        return jsonify({"error": "Field 'type' must be a non-empty string"}), 400
    if "value" not in payload:
        return jsonify({"error": "Field 'value' is required"}), 400

    forward_payload = {
        "type": cmd_type.strip(),
        "value": payload["value"],
    }

    try:
        url = required_env("AZ_COMMAND_URL")
    except RuntimeError:
        app.logger.exception("AZ_COMMAND_URL is missing")
        return jsonify({"error": "Server is not configured for command relay"}), 500

    body, status = azure_json_request("POST", url, payload=forward_payload)
    return jsonify(body), status


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
