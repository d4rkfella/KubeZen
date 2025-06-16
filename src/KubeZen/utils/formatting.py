from datetime import datetime, timezone
from typing import Any, Union, Optional


def _get_datetime_from_metadata(dt_obj: Union[datetime, str, None]) -> datetime | None:
    """Safely parse a datetime object or string from metadata."""
    if not dt_obj:
        return None
        
    if isinstance(dt_obj, datetime):
        return dt_obj
        
    if isinstance(dt_obj, str):
        if dt_obj.endswith("Z"):
            dt_obj = dt_obj[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(dt_obj)
        except ValueError:
            pass
    return None


def format_age(timestamp: Optional[datetime | dict[str, Any] | str]) -> str:
    """Formats a timestamp into a human-readable age string.
    
    Args:
        timestamp: The timestamp to format. Can be:
            - A datetime object
            - A dict containing a 'creationTimestamp' or 'creation_timestamp' key
            - An ISO format string
            - None
    
    Returns:
        A string representing the age, e.g. "2d", "3h", "5m", etc.
        Returns "n/a" if the timestamp is None or invalid.
    """
    dt = None
    
    if isinstance(timestamp, dict):
        ts_str_or_obj = timestamp.get("creationTimestamp") or timestamp.get(
            "creation_timestamp"
        )
        dt = _get_datetime_from_metadata(ts_str_or_obj)
    else:
        dt = _get_datetime_from_metadata(timestamp)

    if not dt:
        return "n/a"

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    age_delta = now - dt
    seconds = age_delta.total_seconds()

    if seconds < 0:
        return "0s"  # Should not happen with correct clocks, but handle it.

    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24

    # --- Tiered Age Formatting Logic ---
    if minutes < 2:  # 0 to 2 minutes -> show seconds
        return f"{int(seconds)}s"

    if minutes < 10:  # 2 to 10 minutes -> show minutes and seconds
        mins = int(minutes)
        secs = int(seconds % 60)
        return f"{mins}m{secs}s"

    if hours < 1:  # 10 minutes to 1 hour -> show minutes only
        return f"{int(minutes)}m"

    if hours < 10:  # 1 to 10 hours -> show hours and minutes
        hrs = int(hours)
        mins = int(minutes % 60)
        return f"{hrs}h{mins}m"

    if hours < 24:  # 10 to 24 hours -> show hours only
        return f"{int(hours)}h"

    if days < 10:  # 1 to 10 days -> show days and hours
        ds = int(days)
        hrs = int(hours % 24)
        return f"{ds}d{hrs}h"

    # Over 10 days -> show days only
    return f"{int(days)}d"
