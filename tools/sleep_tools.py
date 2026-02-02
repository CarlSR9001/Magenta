"""Sleep status tools stored in Letta core block."""

import json
from typing import Optional

from pydantic import BaseModel, Field


# Default sleep hours: 11 PM - 7 AM local time
DEFAULT_SLEEP_HOURS = {
    "start_hour": 23,  # 11 PM
    "end_hour": 7,     # 7 AM
    "timezone": "America/Chicago",
}

# Hours of inactivity after which user is assumed asleep
INACTIVITY_SLEEP_THRESHOLD_HOURS = 4


class SleepStatusArgs(BaseModel):
    status: str = Field(default="", description="asleep | awake | unknown")
    note: Optional[str] = Field(default=None, description="Optional note")
    tz: str = Field(default="America/Chicago")


def set_sleep_status(status: str = "", note: Optional[str] = None, tz: str = "America/Chicago") -> str:
    if not status:
        return "error: missing_status"
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

    payload = {
        "status": status,
        "note": note,
        "updated_at": datetime.datetime.now(zone).isoformat(),
        "timezone": tz,
    }

    block_label = "user_sleep_state"
    try:
        block = client.agents.blocks.retrieve(agent_id, block_label)
        client.agents.blocks.update(block_label, agent_id=agent_id, value=json.dumps(payload))
        return "updated"
    except Exception:
        # Create and attach
        new_block = client.blocks.create(
            label=block_label,
            value=json.dumps(payload),
            limit=2000,
            description="User sleep state for Magenta",
        )
        client.agents.blocks.attach(agent_id, str(new_block.id))
        return "created"


class GetSleepStatusArgs(BaseModel):
    pass


def _is_in_default_sleep_window(tz: str = None) -> bool:
    """Check if current time falls within default sleep hours."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz or DEFAULT_SLEEP_HOURS["timezone"])
    except Exception:
        zone = datetime.timezone.utc

    now = datetime.datetime.now(zone)
    current_hour = now.hour
    start_hour = DEFAULT_SLEEP_HOURS["start_hour"]
    end_hour = DEFAULT_SLEEP_HOURS["end_hour"]

    # Handle overnight window (e.g., 23:00 - 07:00)
    if start_hour > end_hour:
        return current_hour >= start_hour or current_hour < end_hour
    else:
        return start_hour <= current_hour < end_hour


def _infer_sleep_from_activity() -> dict:
    """Infer sleep status from last activity time if no explicit state exists."""
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
        if hours_since_activity >= INACTIVITY_SLEEP_THRESHOLD_HOURS:
            return {
                "status": "asleep",
                "inferred": True,
                "reason": f"no_activity_for_{hours_since_activity:.1f}_hours",
            }

    return {}


def get_sleep_status() -> str:
    """Get current sleep status (explicit or inferred from time/activity).

    Priority order:
    1. Explicit sleep state (user_sleep_state block)
    2. Active quiet hours (user_quiet_hours block) - implies asleep
    3. Time-based inference (default sleep window)
    """
    import os
    import json
    import datetime
    from pathlib import Path

    # Constants (must be inside function for Letta sandbox)
    DEFAULT_SLEEP_START = 23  # 11 PM
    DEFAULT_SLEEP_END = 7     # 7 AM
    DEFAULT_TZ = "America/Chicago"
    INACTIVITY_THRESHOLD_HOURS = 4

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

    # Check for explicit sleep state in block (highest priority)
    block_label = "user_sleep_state"
    try:
        block = client.agents.blocks.retrieve(agent_id, block_label)
        value = block.value or "{}"
        data = json.loads(value)
        if data.get("status"):
            return value
    except Exception:
        pass

    # Check for active quiet hours - if quiet hours set, user is asleep
    # This ensures "going to bed" → set_quiet_hours → implies asleep
    try:
        quiet_block = client.agents.blocks.retrieve(agent_id, "user_quiet_hours")
        quiet_value = quiet_block.value or "{}"
        quiet_data = json.loads(quiet_value)
        if quiet_data.get("status") == "quiet" and quiet_data.get("end"):
            end_time = datetime.datetime.fromisoformat(quiet_data["end"])
            now = datetime.datetime.now(datetime.timezone.utc)
            if now < end_time:
                # Quiet hours active = user is asleep
                return json.dumps({
                    "status": "asleep",
                    "inferred": True,
                    "reason": "quiet_hours_active",
                    "quiet_until": quiet_data["end"],
                    "note": quiet_data.get("note"),
                })
    except Exception:
        pass

    # No explicit state - infer from time and activity
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(DEFAULT_TZ)
    except Exception:
        zone = datetime.timezone.utc

    now = datetime.datetime.now(zone)
    current_hour = now.hour

    # Check if in default sleep window (handles overnight: 23:00-07:00)
    in_sleep_window = current_hour >= DEFAULT_SLEEP_START or current_hour < DEFAULT_SLEEP_END

    if in_sleep_window:
        return json.dumps({
            "status": "asleep",
            "inferred": True,
            "reason": "default_sleep_hours",
            "window": f"{DEFAULT_SLEEP_START}:00-{DEFAULT_SLEEP_END}:00",
        })
    else:
        return json.dumps({
            "status": "awake",
            "inferred": True,
            "reason": "outside_default_sleep_hours",
        })


def is_sleep_active() -> bool:
    """Returns True if user is currently asleep (explicit or inferred)."""
    import json
    try:
        data = json.loads(get_sleep_status())
        return data.get("status") == "asleep"
    except Exception:
        return False
