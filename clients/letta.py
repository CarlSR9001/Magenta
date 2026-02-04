"""Letta client helpers."""

from __future__ import annotations

from typing import Optional

from letta_client import Letta

from config_loader import get_letta_config


def get_letta_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Letta:
    cfg = get_letta_config()
    client_params = {
        "api_key": api_key or cfg["api_key"],
        "timeout": timeout or cfg.get("timeout", 600),
    }
    resolved_base_url = base_url or cfg.get("base_url")
    if resolved_base_url:
        client_params["base_url"] = resolved_base_url
    try:
        return Letta(**client_params)
    except TypeError:
        client_params.pop("api_key", None)
        if api_key or cfg.get("api_key"):
            client_params["token"] = api_key or cfg["api_key"]
        return Letta(**client_params)


def get_agent_id(override: Optional[str] = None) -> str:
    if override:
        return override
    return get_letta_config()["agent_id"]
