from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def sanitize_timestamp_str(ts_str: str | None) -> str:
    """Sanitizes a timestamp string to use 'Z' for UTC timezone."""
    if not ts_str:
        return ""
    if ts_str.endswith("+00:00"):
        return ts_str[:-6] + "Z"
    return ts_str


def is_valid_port(value: str) -> bool:
    """Validate if a string is a valid port number."""
    try:
        port = int(value)
        return 1 <= port <= 65535
    except (ValueError, TypeError):
        return False
