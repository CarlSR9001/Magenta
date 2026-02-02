"""Search Letta archival memory for prior context."""

from pydantic import BaseModel, Field


class ConversationSearchArgs(BaseModel):
    query: str = Field(..., description="Search query for archival memory")
    limit: int = Field(default=5, ge=1, le=20)


def conversation_search(query: str, limit: int = 5) -> str:
    import os
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
    response = client.agents.passages.list(
        agent_id=agent_id,
        search=query,
        limit=limit,
        ascending=False,
    )
    items = getattr(response, "items", response)  # Handle SyncArrayPage or plain list
    payload = [
        {
            "id": p.id,
            "content": getattr(p, "content", None),
            "tags": getattr(p, "tags", None),
            "created_at": getattr(p, "created_at", None),
        }
        for p in items
    ]
    return str(payload)
