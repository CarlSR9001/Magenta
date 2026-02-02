"""Bluesky client helpers (AT Protocol)."""

from __future__ import annotations

import logging
from typing import Optional

try:
    from atproto_client import Client
except ImportError:  # pragma: no cover - fallback for atproto package layout
    from atproto import Client

from config_loader import get_bluesky_config

logger = logging.getLogger(__name__)


def login(
    username: Optional[str] = None,
    password: Optional[str] = None,
    pds_uri: Optional[str] = None,
) -> Client:
    cfg = get_bluesky_config()
    handle = username or cfg["username"]
    secret = password or cfg["password"]
    base_url = pds_uri or cfg.get("pds_uri", "https://bsky.social")

    logger.info("Logging into Bluesky as %s via %s", handle, base_url)
    client = Client(base_url=base_url)
    client.login(handle, secret)
    return client
