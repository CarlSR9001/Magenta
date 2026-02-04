"""Outbox tools backed by Letta archival memory (append-only)."""

from typing import Optional

from pydantic import BaseModel, Field


class DraftPayload(BaseModel):
    id: Optional[str] = Field(default=None)
    type: str = Field(default="post")
    target_uri: Optional[str] = None
    text: Optional[str] = None
    intent: str = ""
    constraints: list[str] = []
    confidence: float = 0.0
    salience: float = 0.0
    salience_factors: dict = {}
    risk_flags: list[str] = []
    abort_if: list[str] = []
    metadata: dict = {}


def outbox_create_draft(
    type: str = "post",
    text: Optional[str] = None,
    target_uri: Optional[str] = None,
    intent: str = "",
    constraints: list[str] = [],
    confidence: float = 0.0,
    salience: float = 0.0,
    salience_factors: dict = {},
    risk_flags: list[str] = [],
    abort_if: list[str] = [],
    metadata: dict = {},
    id: Optional[str] = None,
) -> str:
    import json
    import os
    import uuid
    from datetime import datetime, timezone
    from letta_client import Letta

    draft_id = id or uuid.uuid4().hex[:12]
    payload_dict = {
        "id": draft_id,
        "type": type,
        "text": text,
        "target_uri": target_uri,
        "intent": intent,
        "constraints": constraints,
        "confidence": confidence,
        "salience": salience,
        "salience_factors": salience_factors,
        "risk_flags": risk_flags,
        "abort_if": abort_if,
        "metadata": metadata,
    }

    record = {
        "draft": payload_dict,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(record, ensure_ascii=True)
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
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
    payload_record = {"content": content, "tags": ["magenta", "outbox", f"draft_id:{draft_id}", "status:draft"]}
    client.agents.passages.create(agent_id, text=content, tags=payload_record["tags"])
    return f"draft_id:{draft_id}"


class OutboxUpdateArgs(BaseModel):
    draft_id: str = Field(default="")
    edits: dict = Field(default_factory=dict)


def outbox_update_draft(draft_id: str = "", edits: dict = {}) -> str:
    if not draft_id:
        return "error: missing_draft_id"
    import json
    import os
    from datetime import datetime, timezone
    from letta_client import Letta
    record = {
        "draft_id": draft_id,
        "edits": edits,
        "status": "updated",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(record, ensure_ascii=True)
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
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
    payload_record = {"content": content, "tags": ["magenta", "outbox", f"draft_id:{draft_id}", "status:updated"]}
    client.agents.passages.create(agent_id, text=content, tags=payload_record["tags"])
    return "updated"


class OutboxAbortArgs(BaseModel):
    draft_id: str = Field(default="", description="Draft ID to abort")
    reason: str = Field(default="", description="Reason for aborting")


def outbox_mark_aborted(draft_id: str = "", reason: str = "") -> str:
    if not draft_id or not reason:
        return "error: missing_draft_id_or_reason"
    import json
    import os
    from datetime import datetime, timezone
    from letta_client import Letta
    record = {
        "draft_id": draft_id,
        "status": "aborted",
        "reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(record, ensure_ascii=True)
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
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
    payload_record = {"content": content, "tags": ["magenta", "outbox", f"draft_id:{draft_id}", "status:aborted"]}
    client.agents.passages.create(agent_id, text=content, tags=payload_record["tags"])
    return "aborted"


class OutboxFinalizeArgs(BaseModel):
    draft_id: Optional[str] = Field(default=None)
    status: str = Field(default="finalized")


def outbox_finalize(draft_id: Optional[str] = None, status: str = "finalized") -> str:
    import json
    import os
    from datetime import datetime, timezone
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
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
    record = {
        "draft_id": draft_id,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(record, ensure_ascii=True)
    tags = ["magenta", "outbox", f"status:{status}"]
    if draft_id:
        tags.append(f"draft_id:{draft_id}")
    payload = {"content": content, "tags": tags}
    client.agents.passages.create(agent_id, text=content, tags=tags)
    return status


def outbox_purge_stale_drafts(max_age_hours: int = 24) -> str:
    """Purge stale drafts from Letta archival memory.

    Finds all passages tagged with status:aborted or status:error
    that are older than max_age_hours and deletes them.

    Args:
        max_age_hours: Maximum age in hours before a stale draft is purged.

    Returns:
        Summary string with count of purged passages.
    """
    import json
    import os
    from datetime import datetime, timedelta, timezone
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
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

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    purged_count = 0

    # Search for aborted and error status passages
    for status in ("aborted", "error"):
        try:
            response = client.agents.passages.list(agent_id, query_text=f"status:{status}")
            passages = getattr(response, "items", response)  # Handle SyncArrayPage or plain list
            for passage in passages:
                # Check if passage has the outbox tag and status tag
                tags = getattr(passage, "tags", []) or []
                if "magenta" not in tags or "outbox" not in tags:
                    continue
                if f"status:{status}" not in tags:
                    continue

                # Parse the passage content to check timestamp
                try:
                    content = getattr(passage, "text", "")
                    record = json.loads(content)
                    timestamp_str = record.get("updated_at") or record.get("created_at")
                    if not timestamp_str:
                        continue

                    passage_time = datetime.fromisoformat(timestamp_str)
                    if passage_time.tzinfo is None:
                        passage_time = passage_time.replace(tzinfo=timezone.utc)

                    if passage_time < cutoff:
                        passage_id = getattr(passage, "id", None)
                        if passage_id:
                            client.agents.passages.delete(passage_id, agent_id=agent_id)
                            purged_count += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        except Exception:
            continue

    return f"purged:{purged_count}"
