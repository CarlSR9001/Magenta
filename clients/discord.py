"""Discord client helpers."""

from __future__ import annotations

import logging
from typing import Optional

from config_loader import get_discord_config

logger = logging.getLogger(__name__)


def get_bot_token() -> str:
    """Get the Discord bot token from config."""
    cfg = get_discord_config()
    return cfg["bot_token"]


def get_guild_ids() -> list[str]:
    """Get allowed guild IDs (if restricted)."""
    cfg = get_discord_config()
    return cfg.get("guild_ids", [])
