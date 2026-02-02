"""Helpers to fetch draft payloads from Letta passages."""

from typing import Optional


def find_draft_passage(client, agent_id: str, draft_id: str, limit: int = 50):
    """Return the first passage tagged with the draft_id, or None."""
    if not draft_id:
        return None

    passages = None
    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=f"draft_id:{draft_id}",
            limit=limit,
        )
    except TypeError:
        passages = client.agents.passages.list(agent_id=agent_id, limit=limit)

    items = getattr(passages, "items", passages) or []
    for passage in items:
        tags = getattr(passage, "tags", []) or []
        if f"draft_id:{draft_id}" in tags:
            return passage

    for passage in items:
        text = getattr(passage, "text", "") or getattr(passage, "content", "")
        if f"draft_id:{draft_id}" in text:
            return passage

    return None

