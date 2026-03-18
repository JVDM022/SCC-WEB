from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import quote, quote_plus

import requests

from config import AZURE_TIMEOUT_SECONDS, IOTHUB_CONNECTION_STRING, IOTHUB_DEFAULT_DEVICE_ID, IOTHUB_OTA_MAX_EXECUTION_SECONDS


IOTHUB_API_VERSION = "2021-04-12"


def _parse_connection_string() -> Dict[str, str]:
    if not IOTHUB_CONNECTION_STRING.strip():
        raise RuntimeError("IOTHUB_CONNECTION_STRING is not configured")

    parsed: Dict[str, str] = {}
    for part in IOTHUB_CONNECTION_STRING.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            parsed[key] = value

    hostname = parsed.get("HostName", "").strip()
    policy_name = parsed.get("SharedAccessKeyName", "").strip()
    shared_access_key = parsed.get("SharedAccessKey", "").strip()
    if not hostname or not policy_name or not shared_access_key:
        raise RuntimeError("IOTHUB_CONNECTION_STRING must include HostName, SharedAccessKeyName, and SharedAccessKey")
    return {
        "hostname": hostname.lower(),
        "policy_name": policy_name,
        "shared_access_key": shared_access_key,
    }


def _build_sas_token(expiry_seconds: int = 3600) -> str:
    conn = _parse_connection_string()
    resource_uri = conn["hostname"]
    expiry = int((datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)).timestamp())
    encoded_uri = quote_plus(resource_uri)
    sign_key = f"{encoded_uri}\n{expiry}".encode("utf-8")
    decoded_key = base64.b64decode(conn["shared_access_key"])
    signature = base64.b64encode(hmac.new(decoded_key, sign_key, hashlib.sha256).digest()).decode("utf-8")
    encoded_signature = quote_plus(signature)
    return (
        "SharedAccessSignature "
        f"sr={encoded_uri}&sig={encoded_signature}&se={expiry}&skn={quote_plus(conn['policy_name'])}"
    )


def iot_hub_status_summary() -> Dict[str, Any]:
    configured = True
    config_error = ""
    try:
        _parse_connection_string()
    except RuntimeError as exc:
        configured = False
        config_error = str(exc)

    return {
        "configured": configured,
        "sdk_available": True,
        "transport": "rest",
        "default_device_id": IOTHUB_DEFAULT_DEVICE_ID,
        "sdk_error": config_error,
    }


def _iot_hub_request(
    method: str,
    path: str,
    *,
    json_body: Dict[str, Any] | None = None,
    if_match: str | None = None,
) -> Dict[str, Any]:
    conn = _parse_connection_string()
    url = f"https://{conn['hostname']}{path}?api-version={IOTHUB_API_VERSION}"
    headers = {
        "Authorization": _build_sas_token(),
        "Accept": "application/json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if if_match is not None:
        headers["If-Match"] = if_match

    try:
        response = requests.request(
            method,
            url,
            json=json_body,
            headers=headers,
            timeout=AZURE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Azure IoT Hub request failed") from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = response.text

    if response.status_code >= 400:
        message = f"Azure IoT Hub returned {response.status_code}"
        if body not in ({}, "", None):
            message += f": {body}"
        raise RuntimeError(message)

    if isinstance(body, dict):
        return body
    return {"value": body}


def resolve_device_id(device_id: str | None = None) -> str:
    resolved = str(device_id or IOTHUB_DEFAULT_DEVICE_ID or "").strip()
    if not resolved:
        raise RuntimeError("Device ID is required. Set IOTHUB_DEFAULT_DEVICE_ID or pass a device ID.")
    return resolved


def _normalize_twin(twin: Dict[str, Any]) -> Dict[str, Any]:
    properties = twin.get("properties") or {}
    desired = properties.get("desired") or {}
    reported = properties.get("reported") or {}
    return {
        "device_id": twin.get("deviceId"),
        "etag": twin.get("etag"),
        "status": twin.get("status"),
        "connection_state": twin.get("connectionState"),
        "last_activity_time": twin.get("lastActivityTime"),
        "tags": twin.get("tags") or {},
        "desired": desired,
        "reported": reported,
        "ota": {
            "desired": desired.get("ota") if isinstance(desired, dict) else None,
            "reported": reported.get("ota") if isinstance(reported, dict) else None,
        },
        "raw": twin,
    }


def get_device_twin(device_id: str | None = None) -> Dict[str, Any]:
    target_device_id = resolve_device_id(device_id)
    twin = _iot_hub_request("GET", f"/twins/{quote(target_device_id, safe='')}")
    return _normalize_twin(twin)


def patch_device_desired_properties(desired_patch: Dict[str, Any], device_id: str | None = None) -> Dict[str, Any]:
    if not isinstance(desired_patch, dict) or not desired_patch:
        raise RuntimeError("Desired property patch must be a non-empty JSON object")

    target_device_id = resolve_device_id(device_id)
    twin = _iot_hub_request(
        "PATCH",
        f"/twins/{quote(target_device_id, safe='')}",
        json_body={"properties": {"desired": desired_patch}},
        if_match="*",
    )
    return _normalize_twin(twin)


def patch_device_ota_target(ota_patch: Dict[str, Any], device_id: str | None = None) -> Dict[str, Any]:
    if not isinstance(ota_patch, dict) or not ota_patch:
        raise RuntimeError("OTA patch must be a non-empty JSON object")
    return patch_device_desired_properties({"ota": ota_patch}, device_id=device_id)


def schedule_ota_rollout(
    ota_patch: Dict[str, Any],
    query_condition: str,
    job_id: str | None = None,
    start_time: str | None = None,
    max_execution_time_in_seconds: int | None = None,
) -> Dict[str, Any]:
    if not isinstance(ota_patch, dict) or not ota_patch:
        raise RuntimeError("OTA patch must be a non-empty JSON object")

    condition = str(query_condition or "").strip()
    if not condition:
        raise RuntimeError("query_condition is required")

    resolved_job_id = str(job_id or "").strip()
    if not resolved_job_id:
        resolved_job_id = f"ota-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    body = {
        "jobId": resolved_job_id,
        "type": "scheduleUpdateTwin",
        "queryCondition": condition,
        "startTime": start_time or datetime.now(timezone.utc).isoformat(),
        "maxExecutionTimeInSeconds": int(
            max_execution_time_in_seconds or IOTHUB_OTA_MAX_EXECUTION_SECONDS
        ),
        "updateTwin": {
            "etag": "*",
            "properties": {
                "desired": {
                    "ota": ota_patch,
                }
            },
        },
    }
    return _iot_hub_request("PUT", f"/jobs/v2/{quote(resolved_job_id, safe='')}", json_body=body)


def get_job(job_id: str) -> Dict[str, Any]:
    resolved_job_id = str(job_id or "").strip()
    if not resolved_job_id:
        raise RuntimeError("job_id is required")
    return _iot_hub_request("GET", f"/jobs/v2/{quote(resolved_job_id, safe='')}")
