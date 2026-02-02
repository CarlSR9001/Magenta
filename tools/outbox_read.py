"""Outbox read tools - retrieve and inspect drafts from Letta archival memory."""

from typing import Optional
from pydantic import BaseModel, Field


class ListDraftsArgs(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Filter by status: draft, updated, finalized, aborted (or None for all)"
    )
    limit: int = Field(default=20, ge=1, le=100, description="Max drafts to return")


class GetDraftArgs(BaseModel):
    draft_id: str = Field(..., description="The draft ID to retrieve")


def list_outbox_drafts(status: Optional[str] = None, limit: int = 20) -> str:
    """
    List drafts in the outbox (Letta archival memory).

    Use this to see what's queued, what's been finalized, or what was aborted.
    Essential for the queue/defer workflow - you can't manage what you can't see.

    Args:
        status: Filter by status (draft, updated, finalized, aborted) or None for all
        limit: Maximum number of drafts to return (default 20)

    Returns:
        YAML-formatted list of drafts with their metadata
    """
    import os
    import json
    import yaml

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return "Error: LETTA_API_KEY and LETTA_AGENT_ID must be set"

    from letta_client import Letta
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        except TypeError:
            client = Letta()

    try:
        # Search for outbox passages
        # Try with query_text first, fall back to listing all
        try:
            response = client.agents.passages.list(agent_id, query_text="magenta outbox")
        except Exception:
            response = client.agents.passages.list(agent_id)

        passages = getattr(response, "items", response) or []

        # Filter and parse drafts
        drafts = []
        seen_ids = set()

        for passage in passages:
            tags = getattr(passage, "tags", []) or []

            # Must be an outbox passage
            if "magenta" not in tags or "outbox" not in tags:
                continue

            # Filter by status if specified
            if status:
                if f"status:{status}" not in tags:
                    continue

            # Parse the passage content
            try:
                text = getattr(passage, "text", "")
                record = json.loads(text)

                # Get draft_id from record or tags
                draft_id = record.get("draft_id") or record.get("draft", {}).get("id")
                if not draft_id:
                    for tag in tags:
                        if tag.startswith("draft_id:"):
                            draft_id = tag.split(":", 1)[1]
                            break

                if not draft_id or draft_id in seen_ids:
                    continue
                seen_ids.add(draft_id)

                # Build draft summary
                draft_info = {
                    "draft_id": draft_id,
                    "status": record.get("status", "unknown"),
                }

                # Add draft content if present
                if "draft" in record:
                    draft = record["draft"]
                    draft_info["type"] = draft.get("type", "post")
                    if draft.get("text"):
                        # Truncate long text
                        text_preview = draft["text"][:100]
                        if len(draft["text"]) > 100:
                            text_preview += "..."
                        draft_info["text_preview"] = text_preview
                    if draft.get("target_uri"):
                        draft_info["target_uri"] = draft["target_uri"]
                    if draft.get("intent"):
                        draft_info["intent"] = draft["intent"]
                    draft_info["confidence"] = draft.get("confidence", 0)
                    draft_info["salience"] = draft.get("salience", 0)

                # Add timestamps
                if record.get("created_at"):
                    draft_info["created_at"] = record["created_at"]
                if record.get("updated_at"):
                    draft_info["updated_at"] = record["updated_at"]

                # Add reason if aborted
                if record.get("reason"):
                    draft_info["abort_reason"] = record["reason"]

                drafts.append(draft_info)

                if len(drafts) >= limit:
                    break

            except (json.JSONDecodeError, TypeError):
                continue

        if not drafts:
            return yaml.dump({"drafts": [], "count": 0, "message": "No drafts found"})

        # Sort by created_at descending (newest first)
        drafts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return yaml.dump({
            "drafts": drafts[:limit],
            "count": len(drafts[:limit]),
            "filtered_by": status or "all"
        }, default_flow_style=False, sort_keys=False)

    except Exception as e:
        return f"Error listing drafts: {e}"


def get_draft(draft_id: str) -> str:
    """
    Get a specific draft by ID from the outbox.

    Use this to review a draft before finalizing, or to check what was
    queued earlier. Returns the full draft payload including all metadata.

    Args:
        draft_id: The draft ID (e.g., "a63c7efb2a85")

    Returns:
        YAML-formatted draft details or error message
    """
    import os
    import json
    import yaml

    if not draft_id:
        return "Error: draft_id is required"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return "Error: LETTA_API_KEY and LETTA_AGENT_ID must be set"

    from letta_client import Letta
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        except TypeError:
            client = Letta()

    try:
        # Search for passages with this draft_id
        try:
            response = client.agents.passages.list(agent_id, query_text=f"draft_id:{draft_id}")
        except Exception:
            response = client.agents.passages.list(agent_id)

        passages = getattr(response, "items", response) or []

        # Find the most recent passage for this draft
        matching_passages = []
        for passage in passages:
            tags = getattr(passage, "tags", []) or []
            text = getattr(passage, "text", "")

            # Check if this passage is for our draft
            if f"draft_id:{draft_id}" in tags or f'"draft_id": "{draft_id}"' in text or f'"id": "{draft_id}"' in text:
                try:
                    record = json.loads(text)
                    matching_passages.append({
                        "record": record,
                        "passage_id": getattr(passage, "id", None),
                        "tags": tags,
                    })
                except json.JSONDecodeError:
                    continue

        if not matching_passages:
            return f"Error: Draft '{draft_id}' not found"

        # Get the most recent state (last update wins)
        # Sort by updated_at or created_at (using lambda to avoid inner function)
        matching_passages.sort(
            key=lambda p: p["record"].get("updated_at") or p["record"].get("created_at") or "",
            reverse=True
        )
        latest = matching_passages[0]
        record = latest["record"]

        # Build comprehensive response
        result = {
            "draft_id": draft_id,
            "status": record.get("status", "unknown"),
            "passage_id": latest["passage_id"],
        }

        # Add full draft content if present
        if "draft" in record:
            result["draft"] = record["draft"]

        # Add other metadata
        if "edits" in record:
            result["edits"] = record["edits"]
        if record.get("reason"):
            result["abort_reason"] = record["reason"]
        if record.get("created_at"):
            result["created_at"] = record["created_at"]
        if record.get("updated_at"):
            result["updated_at"] = record["updated_at"]

        # Show history if multiple passages exist
        if len(matching_passages) > 1:
            result["history_count"] = len(matching_passages)
            result["history"] = [
                {
                    "status": p["record"].get("status"),
                    "timestamp": p["record"].get("updated_at") or p["record"].get("created_at") or ""
                }
                for p in matching_passages[:5]  # Last 5 state changes
            ]

        return yaml.dump(result, default_flow_style=False, sort_keys=False)

    except Exception as e:
        return f"Error retrieving draft: {e}"
