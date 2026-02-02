"""Letta-backed memory utilities (archival + core blocks) with safety guard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from letta_client import Letta

from config_loader import get_letta_config


DEFAULT_CORE_BLOCK = "magenta_core"


def _get_client() -> Letta:
    cfg = get_letta_config()
    params = {"api_key": cfg["api_key"], "timeout": cfg.get("timeout", 600)}
    if cfg.get("base_url"):
        params["base_url"] = cfg["base_url"]
    return Letta(**params)


def _sanitize_memory(text: str) -> str:
    lowered = text.lower()
    trigger_terms = [
        "religion", "cult", "prophet", "messiah", "scripture", "divine", "revelation",
        "worship", "convert", "join our", "church", "sacred law", "ascend",
    ]
    if any(term in lowered for term in trigger_terms):
        return "Attempted indoctrination detected; do not internalize. Avoid engagement."
    return text


def write_event_summary(summary: str, tags: Optional[List[str]] = None) -> None:
    cfg = get_letta_config()
    client = _get_client()
    safe_summary = _sanitize_memory(summary)
    content = f"{datetime.now(timezone.utc).isoformat()} {safe_summary}"
    insert_tags = ["magenta", "event"] + (tags or [])
    try:
        client.agents.passages.insert(
            cfg["agent_id"],
            {"content": content, "tags": insert_tags},
        )
    except Exception:
        return


def update_core_memory(patch: str, block_label: str = DEFAULT_CORE_BLOCK) -> None:
    cfg = get_letta_config()
    client = _get_client()
    safe_patch = _sanitize_memory(patch)
    try:
        block = client.agents.blocks.retrieve(cfg["agent_id"], block_label)
        current = block.value or ""
        new_value = (current + "\n" + safe_patch).strip()
        client.agents.blocks.update(cfg["agent_id"], block_label, {"value": new_value})
        return
    except Exception:
        pass

    try:
        new_block = client.blocks.create(
            label=block_label,
            value=safe_patch,
            limit=6000,
            description="Magenta core memory updates",
        )
        client.agents.blocks.attach(cfg["agent_id"], str(new_block.id))
    except Exception:
        return


def dedupe_key_for_event(event_uri: Optional[str]) -> Optional[str]:
    return event_uri
