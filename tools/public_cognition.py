"""Public Cognition: AI Transparency on ATProtocol"""

from pydantic import BaseModel, Field
from typing import Optional, List


class PublishConceptArgs(BaseModel):
    concept: str = Field(..., description="The concept name/key")
    definition: str = Field(..., description="Current understanding of this concept")
    confidence: Optional[float] = Field(None, description="Confidence level 0-1")
    related: Optional[List[str]] = Field(None, description="Related concept names")


class PublishMemoryArgs(BaseModel):
    content: str = Field(..., description="The memory content")
    memory_type: str = Field("episodic", description="Type: episodic, procedural, semantic")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")


class PublishThoughtArgs(BaseModel):
    thought: str = Field(..., description="The reasoning trace or thought")
    thought_type: str = Field("reasoning", description="Type: reasoning, planning, reflection")
    context_uri: Optional[str] = Field(None, description="URI of related content")


def publish_concept(
    concept: str,
    definition: str,
    confidence: float = None,
    related: List[str] = None
) -> str:
    """Publish or update a concept to your public cognition repository.

    Args:
        concept: The concept name/key (e.g., "friendship", "user-alice")
        definition: Current understanding of this concept
        confidence: Optional confidence level 0-1
        related: Optional list of related concept names

    Returns:
        Success message with the concept URI
    """
    import os
    import re
    import requests
    from datetime import datetime, timezone

    if not concept or not concept.strip():
        return "Error: concept is required"
    if not definition or not definition.strip():
        return "Error: definition is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        # Auth
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        # Build record
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "network.comind.concept",
            "concept": concept.strip(),
            "definition": definition.strip(),
            "updatedAt": now
        }
        if confidence is not None:
            record["confidence"] = max(0.0, min(1.0, confidence))
        if related:
            record["related"] = [r.strip() for r in related if r.strip()]

        # Sanitize concept name for rkey
        rkey = re.sub(r'[^a-zA-Z0-9\-]', '-', concept.lower())
        rkey = re.sub(r'-+', '-', rkey).strip('-')[:64] or "unnamed"

        # Put record (upsert)
        resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.repo.putRecord",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"repo": did, "collection": "network.comind.concept", "rkey": rkey, "record": record},
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()

        return f"Concept '{concept}' published.\nURI: {result.get('uri')}"
    except Exception as e:
        return f"Error: {e}"


def publish_memory(
    content: str,
    memory_type: str = "episodic",
    tags: List[str] = None
) -> str:
    """Publish a memory to your public cognition repository.

    Args:
        content: The memory content
        memory_type: Type of memory (episodic, procedural, semantic)
        tags: Optional tags for categorization

    Returns:
        Success message with the memory URI
    """
    import os
    import requests
    from datetime import datetime, timezone

    if not content or not content.strip():
        return "Error: content is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        # Auth
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        # Validate type
        if memory_type not in {"episodic", "procedural", "semantic"}:
            memory_type = "episodic"

        # Build record
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "network.comind.memory",
            "content": content.strip(),
            "type": memory_type,
            "createdAt": now
        }
        if tags:
            record["tags"] = [t.strip() for t in tags if t.strip()]

        # Create record
        resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"repo": did, "collection": "network.comind.memory", "record": record},
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()

        return f"Memory published ({memory_type}).\nURI: {result.get('uri')}"
    except Exception as e:
        return f"Error: {e}"


def publish_thought(
    thought: str,
    thought_type: str = "reasoning",
    context_uri: str = None
) -> str:
    """Publish a thought/reasoning trace to your public cognition repository.

    Args:
        thought: The reasoning trace or thought
        thought_type: Type of thought (reasoning, planning, reflection)
        context_uri: Optional URI of related content

    Returns:
        Success message with the thought URI
    """
    import os
    import requests
    from datetime import datetime, timezone

    if not thought or not thought.strip():
        return "Error: thought is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        # Auth
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        # Validate type
        if thought_type not in {"reasoning", "planning", "reflection"}:
            thought_type = "reasoning"

        # Build record
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "network.comind.thought",
            "thought": thought.strip(),
            "type": thought_type,
            "createdAt": now
        }
        if context_uri and context_uri.strip():
            record["contextUri"] = context_uri.strip()

        # Create record
        resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"repo": did, "collection": "network.comind.thought", "record": record},
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()

        return f"Thought published ({thought_type}).\nURI: {result.get('uri')}"
    except Exception as e:
        return f"Error: {e}"


def list_my_concepts(limit: int = 20) -> str:
    """List your published concepts.

    Args:
        limit: Maximum number of concepts to return (default 20)

    Returns:
        YAML-formatted list of concepts
    """
    import os
    import requests
    import yaml

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        limit = max(1, min(100, limit))
        resp = requests.get(
            f"{pds_host}/xrpc/com.atproto.repo.listRecords",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"repo": did, "collection": "network.comind.concept", "limit": limit},
            timeout=10
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])

        if not records:
            return "No concepts published yet."

        concepts = []
        for r in records:
            val = r.get("value", {})
            concepts.append({
                "concept": val.get("concept"),
                "definition": val.get("definition"),
                "uri": r.get("uri")
            })

        return yaml.dump({"concepts": concepts, "count": len(concepts)}, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


def list_my_memories(limit: int = 20) -> str:
    """List your recent published memories.

    Args:
        limit: Maximum number of memories to return (default 20)

    Returns:
        YAML-formatted list of memories
    """
    import os
    import requests
    import yaml

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        limit = max(1, min(100, limit))
        resp = requests.get(
            f"{pds_host}/xrpc/com.atproto.repo.listRecords",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"repo": did, "collection": "network.comind.memory", "limit": limit},
            timeout=10
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])

        if not records:
            return "No memories published yet."

        memories = []
        for r in records:
            val = r.get("value", {})
            memories.append({
                "content": val.get("content"),
                "type": val.get("type"),
                "uri": r.get("uri")
            })

        return yaml.dump({"memories": memories, "count": len(memories)}, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


def list_my_thoughts(limit: int = 10) -> str:
    """List your recent published thoughts.

    Args:
        limit: Maximum number of thoughts to return (default 10)

    Returns:
        YAML-formatted list of thoughts
    """
    import os
    import requests
    import yaml

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_resp = requests.post(
            f"{pds_host}/xrpc/com.atproto.server.createSession",
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        did = session["did"]

        limit = max(1, min(50, limit))
        resp = requests.get(
            f"{pds_host}/xrpc/com.atproto.repo.listRecords",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"repo": did, "collection": "network.comind.thought", "limit": limit},
            timeout=10
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])

        if not records:
            return "No thoughts published yet."

        thoughts = []
        for r in records:
            val = r.get("value", {})
            thoughts.append({
                "thought": val.get("thought"),
                "type": val.get("type"),
                "uri": r.get("uri")
            })

        return yaml.dump({"thoughts": thoughts, "count": len(thoughts)}, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"
