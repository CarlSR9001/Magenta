"""Quiet hours mode tools (7-hour window by default)."""

import json
from typing import Optional

from pydantic import BaseModel, Field


# Default quiet hours window configuration
DEFAULT_QUIET_HOURS = {
    "start_hour": 22,  # 10 PM
    "end_hour": 8,     # 8 AM
    "timezone": "America/Chicago",
}

# Default quiet period duration when triggered by inactivity
DEFAULT_QUIET_DURATION_HOURS = 7


class QuietHoursArgs(BaseModel):
    hours: int = Field(default=7, ge=1, le=24)
    note: Optional[str] = Field(default=None)
    tz: str = Field(default="America/Chicago")


def set_quiet_hours(hours: int = 7, note: Optional[str] = None, tz: str = "America/Chicago") -> str:
    import os
    import json
    import datetime
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz)
    except Exception:
        zone = datetime.timezone.utc
        tz = "UTC"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")

    from letta_client import Letta
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
        except TypeError:
            try:
                client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
            except TypeError:
                client = Letta()

    now = datetime.datetime.now(zone)
    quiet_until = now + datetime.timedelta(hours=hours)
    payload = {
        "status": "quiet",
        "note": note,
        "start": now.isoformat(),
        "end": quiet_until.isoformat(),
        "timezone": tz,
        "hours": hours,
    }

    block_label = "user_quiet_hours"
    try:
        block = client.agents.blocks.retrieve(agent_id, block_label)
        client.agents.blocks.update(block_label, agent_id=agent_id, value=json.dumps(payload))
        return "updated"
    except Exception:
        new_block = client.blocks.create(
            label=block_label,
            value=json.dumps(payload),
            limit=2000,
            description="User quiet hours for Magenta",
        )
        client.agents.blocks.attach(agent_id, str(new_block.id))
        return "created"


class GetQuietHoursArgs(BaseModel):
    pass


def _is_in_default_quiet_window(tz: str = None) -> bool:
    """Check if current time falls within default quiet hours window."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz or DEFAULT_QUIET_HOURS["timezone"])
    except Exception:
        zone = datetime.timezone.utc

    now = datetime.datetime.now(zone)
    current_hour = now.hour
    start_hour = DEFAULT_QUIET_HOURS["start_hour"]
    end_hour = DEFAULT_QUIET_HOURS["end_hour"]

    # Handle overnight window (e.g., 22:00 - 08:00)
    if start_hour > end_hour:
        return current_hour >= start_hour or current_hour < end_hour
    else:
        return start_hour <= current_hour < end_hour


def _infer_quiet_from_activity() -> dict:
    """Infer quiet hours from last activity time (7 hours from last activity)."""
    import datetime
    from pathlib import Path

    # Check various activity indicators
    activity_files = [
        Path("state/agent_state.json"),
        Path("state/schedules.json"),
        Path("outbox"),
    ]

    latest_activity = None
    for f in activity_files:
        try:
            if f.exists():
                mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime, tz=datetime.timezone.utc)
                if latest_activity is None or mtime > latest_activity:
                    latest_activity = mtime
        except Exception:
            pass

    if latest_activity:
        now = datetime.datetime.now(datetime.timezone.utc)
        hours_since_activity = (now - latest_activity).total_seconds() / 3600

        # If within 7 hours of last activity ending (assumed quiet period)
        if hours_since_activity < DEFAULT_QUIET_DURATION_HOURS:
            quiet_end = latest_activity + datetime.timedelta(hours=DEFAULT_QUIET_DURATION_HOURS)
            if now < quiet_end:
                return {
                    "status": "quiet",
                    "inferred": True,
                    "reason": "activity_based_quiet_window",
                    "end": quiet_end.isoformat(),
                }

    return {}


def get_quiet_hours() -> str:
    """Get current quiet hours status (explicit or inferred from time)."""
    import os
    import json
    import datetime

    # Constants (must be inside function for Letta sandbox)
    DEFAULT_QUIET_START = 22  # 10 PM
    DEFAULT_QUIET_END = 8     # 8 AM
    DEFAULT_TZ = "America/Chicago"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    from letta_client import Letta
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        except TypeError:
            client = Letta()

    # Check for explicit quiet hours in block
    block_label = "user_quiet_hours"
    try:
        block = client.agents.blocks.retrieve(agent_id, block_label)
        value = block.value or "{}"
        data = json.loads(value)

        # Check if explicit quiet hours are still active
        if data.get("status") == "quiet" and data.get("end"):
            try:
                end_time = datetime.datetime.fromisoformat(data["end"])
                now = datetime.datetime.now(datetime.timezone.utc)
                if now < end_time:
                    return value
            except Exception:
                pass
    except Exception:
        pass

    # No explicit state or expired - check time-based defaults
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(DEFAULT_TZ)
    except Exception:
        zone = datetime.timezone.utc

    now = datetime.datetime.now(zone)
    current_hour = now.hour

    # Check if in default quiet window (handles overnight: 22:00-08:00)
    in_quiet_window = current_hour >= DEFAULT_QUIET_START or current_hour < DEFAULT_QUIET_END

    if in_quiet_window:
        # Calculate when quiet hours end
        if current_hour >= DEFAULT_QUIET_START:
            # After start, ends tomorrow
            end_time = now.replace(hour=DEFAULT_QUIET_END, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        else:
            # Before end, ends today
            end_time = now.replace(hour=DEFAULT_QUIET_END, minute=0, second=0, microsecond=0)

        return json.dumps({
            "status": "quiet",
            "inferred": True,
            "reason": "default_quiet_hours",
            "window": f"{DEFAULT_QUIET_START}:00-{DEFAULT_QUIET_END}:00",
            "end": end_time.isoformat(),
        })
    else:
        return json.dumps({
            "status": "active",
            "inferred": True,
            "reason": "outside_quiet_hours",
        })


def is_quiet_hours_active() -> bool:
    """Returns True if quiet hours are currently active (explicit or inferred)."""
    import json
    try:
        data = json.loads(get_quiet_hours())
        return data.get("status") == "quiet"
    except Exception:
        return False
