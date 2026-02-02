"""Local time tools (America/Chicago)."""

from pydantic import BaseModel, Field


class LocalTimeArgs(BaseModel):
    tz: str = Field(default="America/Chicago", description="IANA timezone name")


def get_local_time(tz: str = "America/Chicago") -> str:
    import datetime
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz)
    except Exception:
        zone = datetime.timezone.utc
        tz = "UTC"
    now = datetime.datetime.now(zone)
    return str({
        "now_iso": now.isoformat(),
        "timezone": tz,
        "utc_offset": now.strftime("%z"),
        "epoch": int(now.timestamp()),
    })
