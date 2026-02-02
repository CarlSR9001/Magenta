"""Control/meta tools for Letta tool rules."""

from typing import Optional

from pydantic import BaseModel, Field

class RateLimitArgs(BaseModel):
    ok: Optional[str] = Field(default=None, description="Optional flag; empty is treated as ok")
def rate_limit_check(ok: Optional[str] = None) -> str:
    if ok is None or ok == "" or str(ok).lower() in {"true", "1", "yes", "ok"}:
        return "ok"
    return "blocked"


class LoadStateArgs(BaseModel):
    note: str = Field(default="", description="Optional note/reason for loading state")


def load_agent_state(note: str = "") -> str:
    """Load the agent's Core Memory blocks."""
    import os
    from letta_client import Letta
    
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
        
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        
    try:
        response = client.agents.blocks.list(agent_id=agent_id)
        blocks = getattr(response, "items", response)
        
        output = []
        seen_labels = set()
        for b in blocks:
            label = getattr(b, "label", "unknown")
            if label in seen_labels:
                continue
            seen_labels.add(label)
            value = getattr(b, "value", "")
            output.append(f"== {label} ==\n{value}")
        return "\n\n".join(output) if output else "No memory blocks found."
    except Exception as e:
        return f"Error loading state: {e}"


class PostmortemArgs(BaseModel):
    summary: str = Field(..., description="The postmortem summary to write to archival memory")


def postmortem_write(summary: str) -> str:
    """Write a postmortem summary to archival memory."""
    import os
    from letta_client import Letta
    
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
        
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)

    try:
        client.agents.passages.create(
            agent_id=agent_id,
            text=summary,
            tags=["postmortem"]
        )
        return "Postmortem saved to archival memory."
    except Exception as e:
        return f"Error saving postmortem: {e}"
