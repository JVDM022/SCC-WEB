from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

import requests
from flask import current_app, has_app_context

from config import (
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_TIMEOUT_SECONDS,
    BROADCAST_BLOB_CONTAINER,
    BROADCAST_BLOB_PATH_PREFIX,
    BROADCAST_ENDPOINT_HEADERS_JSON,
    BROADCAST_ENDPOINT_METHOD,
    BROADCAST_ENDPOINT_PAYLOAD_JSON,
    BROADCAST_ENDPOINT_URL,
    BROADCAST_SOURCE_URL_FALLBACK,
    TELEMETRY_LOG_LOCK,
    TELEMETRY_LOG_PATH,
)
from db import execute_sql, fetch_one, get_db
from services.telemetry import ensure_telemetry_log_file

try:
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient, ContentSettings
except ImportError:  # pragma: no cover - runtime dependency is optional during local editing
    BlobServiceClient = None
    ContentSettings = None

    class ResourceExistsError(Exception):
        pass


def _logger() -> logging.Logger:
    if has_app_context():
        return current_app.logger
    return logging.getLogger(__name__)


def _require_config(value: str, name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"{name} is not configured")


def _load_json_object(raw: str, name: str) -> Dict[str, str]:
    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON") from exc

    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _load_json_value(raw: str, name: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON") from exc


def _request_broadcast_payload() -> Any:
    url = BROADCAST_ENDPOINT_URL or BROADCAST_SOURCE_URL_FALLBACK
    url = _require_config(url, "BROADCAST_ENDPOINT_URL or AZ_TELEMETRY_URL")
    method = _require_config(BROADCAST_ENDPOINT_METHOD, "BROADCAST_ENDPOINT_METHOD")
    headers = _load_json_object(BROADCAST_ENDPOINT_HEADERS_JSON, "BROADCAST_ENDPOINT_HEADERS_JSON")
    payload = _load_json_value(BROADCAST_ENDPOINT_PAYLOAD_JSON, "BROADCAST_ENDPOINT_PAYLOAD_JSON")

    try:
        response = requests.request(
            method,
            url,
            headers=headers or None,
            json=payload,
            timeout=AZURE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Broadcast endpoint is unavailable") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Broadcast endpoint returned {response.status_code}")

    try:
        return response.json()
    except ValueError:
        return response.text


def _flatten_row(value: Any, prefix: str = "", row: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = {} if row is None else row

    if isinstance(value, dict):
        if not value and prefix:
            row[prefix] = ""
            return row
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_row(item, next_prefix, row)
        return row

    if isinstance(value, list):
        target = prefix or "value"
        if not value:
            row[target] = ""
            return row
        if all(not isinstance(item, (dict, list)) for item in value):
            row[target] = json.dumps(value, ensure_ascii=False)
            return row
        for index, item in enumerate(value):
            next_prefix = f"{target}[{index}]"
            _flatten_row(item, next_prefix, row)
        return row

    row[prefix or "value"] = "" if value is None else value
    return row


def _extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        source_rows = payload
    elif isinstance(payload, dict):
        source_rows = None
        for key in ("broadcast", "items", "data", "records", "results", "value"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                source_rows = candidate
                break
        if source_rows is None:
            source_rows = [payload]
    else:
        source_rows = [payload]

    rows = [_flatten_row(item) for item in source_rows]
    return rows or [{"value": ""}]


def _rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    if not fieldnames:
        fieldnames = ["value"]

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return output.getvalue()


def _blob_name_for(exported_at: datetime) -> str:
    timestamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = BROADCAST_BLOB_PATH_PREFIX.strip().strip("/")
    if prefix:
        return f"{prefix}/broadcast_{timestamp}.csv"
    return f"broadcast_{timestamp}.csv"


def _service_client() -> BlobServiceClient:
    connection_string = _require_config(
        AZURE_STORAGE_CONNECTION_STRING,
        "AZURE_STORAGE_CONNECTION_STRING",
    )

    if BlobServiceClient is None or ContentSettings is None:
        raise RuntimeError("azure-storage-blob is not installed")

    return BlobServiceClient.from_connection_string(connection_string)


def _container_client(container_name: str):
    service_client = _service_client()
    container_client = service_client.get_container_client(container_name)
    try:
        container_client.create_container()
    except ResourceExistsError:
        pass
    return container_client


def _upload_blob_bytes(data: bytes, blob_name: str, content_type: str) -> str:
    container_name = _require_config(BROADCAST_BLOB_CONTAINER, "BROADCAST_BLOB_CONTAINER")
    container_client = _container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob_client.url


def _upload_csv(csv_text: str, exported_at: datetime) -> tuple[str, str]:
    blob_name = _blob_name_for(exported_at)
    blob_url = _upload_blob_bytes(
        csv_text.encode("utf-8"),
        blob_name,
        "text/csv; charset=utf-8",
    )
    return blob_name, blob_url


def _telemetry_log_blob_name_for(exported_at: datetime) -> str:
    timestamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = BROADCAST_BLOB_PATH_PREFIX.strip().strip("/")
    if prefix:
        return f"{prefix}/telemetry_log_{timestamp}.csv"
    return f"telemetry_log_{timestamp}.csv"


def _read_telemetry_log_csv() -> tuple[str, int]:
    with TELEMETRY_LOG_LOCK:
        ensure_telemetry_log_file()
        try:
            csv_text = TELEMETRY_LOG_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError("Telemetry log could not be read") from exc

    row_count = sum(1 for _ in csv.DictReader(io.StringIO(csv_text)))
    return csv_text, row_count


def _upload_telemetry_log_csv(csv_text: str, exported_at: datetime) -> tuple[str, str]:
    blob_name = _telemetry_log_blob_name_for(exported_at)
    blob_url = _upload_blob_bytes(
        csv_text.encode("utf-8"),
        blob_name,
        "text/csv; charset=utf-8",
    )
    return blob_name, blob_url


def _upsert_documentation_entry(blob_url: str, row_count: int, exported_at: datetime) -> None:
    title = "Telemetry Log CSV Export"
    doc_type = "Blob"
    owner = "System"
    status = f"Synced {row_count} samples"
    last_updated = exported_at.strftime("%Y-%m-%d")
    existing = fetch_one(
        "SELECT id FROM documentation WHERE title IN (%s, %s) ORDER BY id DESC LIMIT 1",
        (title, "Broadcast CSV Export"),
    )

    if existing:
        execute_sql(
            "UPDATE documentation SET title = %s, doc_type = %s, owner = %s, location = %s, status = %s, last_updated = %s "
            "WHERE id = %s",
            (title, doc_type, owner, blob_url, status, last_updated, existing["id"]),
        )
    else:
        execute_sql(
            "INSERT INTO documentation (title, doc_type, owner, location, status, last_updated) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (title, doc_type, owner, blob_url, status, last_updated),
        )
    get_db().commit()


def _insert_documentation_entry(
    title: str,
    doc_type: str,
    owner: str,
    location: str,
    status: str,
    exported_at: datetime,
) -> int:
    last_updated = exported_at.strftime("%Y-%m-%d")
    execute_sql(
        "INSERT INTO documentation (title, doc_type, owner, location, status, last_updated) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (title, doc_type, owner, location, status, last_updated),
    )
    row = fetch_one(
        "SELECT id FROM documentation WHERE location = %s ORDER BY id DESC LIMIT 1",
        (location,),
    )
    get_db().commit()
    return int(row["id"]) if row else 0


def _upload_name_for(filename: str, uploaded_at: datetime) -> str:
    prefix = BROADCAST_BLOB_PATH_PREFIX.strip().strip("/")
    timestamp = uploaded_at.strftime("%Y%m%dT%H%M%SZ")
    safe_name = Path(filename).name or "upload.bin"
    if prefix:
        return f"{prefix}/uploads/{timestamp}_{safe_name}"
    return f"uploads/{timestamp}_{safe_name}"


def _blob_ref_from_url(location: str) -> tuple[str, str] | None:
    if not location:
        return None

    parsed = urlparse(location)
    if parsed.scheme not in {"http", "https"}:
        return None
    if "blob." not in parsed.netloc:
        return None

    path = [segment for segment in parsed.path.split("/") if segment]
    if len(path) < 2:
        return None

    container_name = path[0]
    blob_name = unquote("/".join(path[1:]))
    if not container_name or not blob_name:
        return None
    return container_name, blob_name


def export_broadcast_csv_to_blob() -> Dict[str, Any]:
    csv_text, row_count = _read_telemetry_log_csv()
    exported_at = datetime.now(timezone.utc)
    blob_name, blob_url = _upload_telemetry_log_csv(csv_text, exported_at)

    _upsert_documentation_entry(blob_url, row_count, exported_at)

    _logger().info("Exported telemetry log CSV to blob %s", blob_name)
    return {
        "ok": True,
        "blob_name": blob_name,
        "blob_url": blob_url,
        "row_count": row_count,
        "exported_at": exported_at.isoformat().replace("+00:00", "Z"),
    }


def upload_documentation_file_to_blob(
    filename: str,
    data: bytes,
    content_type: str,
    title: str,
    owner: str = "User",
) -> Dict[str, Any]:
    uploaded_at = datetime.now(timezone.utc)
    blob_name = _upload_name_for(filename, uploaded_at)
    blob_url = _upload_blob_bytes(
        data,
        blob_name,
        content_type or "application/octet-stream",
    )
    item_id = _insert_documentation_entry(
        title=title,
        doc_type="Blob Upload",
        owner=owner,
        location=blob_url,
        status="Uploaded",
        exported_at=uploaded_at,
    )
    return {
        "ok": True,
        "item_id": item_id,
        "blob_name": blob_name,
        "blob_url": blob_url,
        "title": title,
        "uploaded_at": uploaded_at.isoformat().replace("+00:00", "Z"),
    }


def download_documentation_blob(item_id: int) -> Dict[str, Any]:
    row = fetch_one(
        "SELECT id, title, location FROM documentation WHERE id = %s",
        (item_id,),
    )
    if row is None:
        raise RuntimeError("Documentation item was not found")

    location = str(row.get("location") or "").strip()
    if not location:
        raise RuntimeError("Documentation item has no blob location")

    blob_ref = _blob_ref_from_url(location)
    if blob_ref is None:
        return {"mode": "redirect", "url": location}

    container_name, blob_name = blob_ref
    blob_client = _service_client().get_blob_client(container=container_name, blob=blob_name)
    content = blob_client.download_blob().readall()
    properties = blob_client.get_blob_properties()
    content_type = str(properties.content_settings.content_type or "application/octet-stream")
    download_name = Path(blob_name).name or f"{row.get('title') or 'blob'}"
    return {
        "mode": "download",
        "data": content,
        "content_type": content_type,
        "download_name": download_name,
    }
