from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def pacific_now() -> datetime:
    return datetime.now(PACIFIC_TZ)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text or text.startswith("0001-01-01T00:00:00"):
            return None

        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_pacific_timestamp(value: Any, fallback: str = "") -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return fallback
    return parsed.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
