"""Surgical context management tools for agent self-modification.

This module provides tools that allow the agent to manage its own context window
at a granular level - moving specific content between "slots" (memory blocks),
archiving to long-term storage, and restoring when needed.

Architecture:
- Context Slots: Named memory blocks the agent can create/modify/delete
- Archival Memory: Long-term passage storage with semantic search and tags
- Message Extraction: Pull specific content from conversation into slots

The agent can surgically control what stays in context vs what gets archived.

NOTE: Each tool function contains inline helper code because Letta runs tools
in isolation - module-level functions are not available at runtime.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field

# Constants (these ARE available as they're primitives, not functions)
SLOT_PREFIX = "ctx_slot_"
MAX_SLOTS = 20
DEFAULT_SLOT_LIMIT = 5000


# =============================================================================
# SLOT LISTING AND INSPECTION
# =============================================================================

class ListSlotsArgs(BaseModel):
    include_content: bool = Field(
        default=False,
        description="Include full content of each slot (verbose)"
    )


def list_context_slots(include_content: bool = False) -> str:
    """List all context slots (managed memory blocks) with their sizes and status.

    Use this to see what working memory slots exist and how much space they use.
    Slots are your surgical context management areas - content you explicitly control.
    """
    import os
    import json
    import re
    from letta_client import Letta

    # Inline constants
    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    # Get client
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks)

        slots = []
        total_chars = 0

        for block in items:
            label = getattr(block, "label", None)
            if not label or not label.startswith(SLOT_PREFIX):
                continue

            slot_name = label[len(SLOT_PREFIX):] if label.startswith(SLOT_PREFIX) else None
            value = getattr(block, "value", "") or ""
            char_count = len(value)
            total_chars += char_count
            limit = getattr(block, "limit", DEFAULT_SLOT_LIMIT)

            slot_info = {
                "name": slot_name,
                "chars": char_count,
                "limit": limit,
                "usage_pct": round((char_count / limit) * 100, 1) if limit > 0 else 0,
                "block_id": str(getattr(block, "id", "unknown")),
            }

            if include_content:
                slot_info["content"] = value[:500] + "..." if len(value) > 500 else value
            else:
                preview = value[:100].replace("\n", " ").strip()
                if len(value) > 100:
                    preview += "..."
                slot_info["preview"] = preview

            slots.append(slot_info)

        result = {
            "slot_count": len(slots),
            "total_chars": total_chars,
            "max_slots": 20,  # MAX_SLOTS constant
            "slots": sorted(slots, key=lambda x: x["name"]),
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


class InspectSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Name of the slot to inspect")


def inspect_slot(slot_name: str) -> str:
    """Inspect a specific context slot's full content and metadata.

    Use this to see exactly what's in a slot before deciding to modify it.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    # Build label
    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)

        value = getattr(block, "value", "") or ""
        limit = getattr(block, "limit", DEFAULT_SLOT_LIMIT)

        try:
            parsed = json.loads(value)
            content_type = "json"
            content = parsed
        except (json.JSONDecodeError, TypeError):
            content_type = "text"
            content = value

        result = {
            "slot_name": slot_name,
            "label": label,
            "block_id": str(getattr(block, "id", "unknown")),
            "char_count": len(value),
            "limit": limit,
            "usage_pct": round((len(value) / limit) * 100, 1) if limit > 0 else 0,
            "content_type": content_type,
            "content": content,
            "read_only": getattr(block, "read_only", False),
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Slot '{slot_name}' not found or error: {e}"})


# =============================================================================
# SLOT CREATION AND DELETION
# =============================================================================

class CreateSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Name for the new slot (alphanumeric + underscores)")
    initial_content: str = Field(default="", description="Initial content to put in the slot")
    size_limit: int = Field(default=5000, ge=500, le=20000, description="Character limit for this slot")
    description: str = Field(default="", description="Description of what this slot is for")


def create_context_slot(
    slot_name: str,
    initial_content: str = "",
    size_limit: int = 5000,
    description: str = ""
) -> str:
    """Create a new context slot (memory block) for storing working memory.

    Slots are your managed context areas. Create slots for:
    - Topics you're tracking (e.g., 'current_project', 'user_preferences')
    - Temporary working memory for a task
    - Important extracted content you want to preserve

    Content in slots persists across conversations and won't be auto-summarized.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"
    MAX_SLOTS = 20

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    # Check slot count
    try:
        existing_blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(existing_blocks, "items", existing_blocks)
        slot_count = sum(1 for b in items if getattr(b, "label", "").startswith(SLOT_PREFIX))

        if slot_count >= MAX_SLOTS:
            return json.dumps({
                "error": f"Maximum slots ({MAX_SLOTS}) reached. Delete unused slots first.",
                "current_count": slot_count
            })
    except Exception:
        pass

    # Check if already exists
    try:
        existing = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        return json.dumps({
            "error": f"Slot '{slot_name}' already exists",
            "existing_chars": len(getattr(existing, "value", "") or ""),
            "hint": "Use write_to_slot to modify, or delete_slot first"
        })
    except Exception:
        pass

    try:
        block_desc = description or f"Context slot: {slot_name}"
        new_block = client.blocks.create(
            label=label,
            value=initial_content,
            limit=size_limit,
            description=block_desc,
        )
        client.agents.blocks.attach(agent_id=agent_id, block_id=str(new_block.id))

        return json.dumps({
            "success": True,
            "slot_name": slot_name,
            "label": label,
            "block_id": str(new_block.id),
            "initial_chars": len(initial_content),
            "limit": size_limit,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to create slot: {e}"})


class DeleteSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Name of the slot to delete")
    archive_first: bool = Field(
        default=True,
        description="Archive content to long-term memory before deleting"
    )
    archive_tags: List[str] = Field(
        default_factory=lambda: ["archived_slot"],
        description="Tags to apply if archiving"
    )


def delete_context_slot(
    slot_name: str,
    archive_first: bool = True,
    archive_tags: Optional[List[str]] = None
) -> str:
    """Delete a context slot, optionally archiving its content first.

    Use this to free up context space by removing slots you no longer need.
    By default, content is archived to long-term memory before deletion.
    """
    import os
    import json
    import re
    from letta_client import Letta

    if archive_tags is None:
        archive_tags = ["archived_slot"]

    SLOT_PREFIX = "ctx_slot_"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        block_id = str(getattr(block, "id", ""))
        content = getattr(block, "value", "") or ""

        archived_passage_id = None

        if archive_first and content.strip():
            try:
                passage = client.agents.passages.create(
                    agent_id=agent_id,
                    text=f"[Archived slot: {slot_name}]\n{content}",
                    tags=archive_tags + [f"slot:{slot_name}"],
                )
                archived_passage_id = str(getattr(passage, "id", "unknown"))
            except Exception:
                pass

        client.agents.blocks.detach(agent_id=agent_id, block_id=block_id)

        return json.dumps({
            "success": True,
            "slot_name": slot_name,
            "deleted_chars": len(content),
            "archived": archived_passage_id is not None,
            "archived_passage_id": archived_passage_id,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to delete slot '{slot_name}': {e}"})


# =============================================================================
# SLOT CONTENT MANIPULATION (SURGICAL EDITS)
# =============================================================================

class WriteSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Target slot name")
    content: str = Field(..., description="Content to write")
    mode: Literal["replace", "append", "prepend"] = Field(
        default="replace",
        description="How to write: replace all, append to end, prepend to start"
    )


def write_to_slot(
    slot_name: str,
    content: str,
    mode: str = "replace"
) -> str:
    """Write content to a context slot.

    Modes:
    - replace: Overwrite entire slot content
    - append: Add to end of existing content
    - prepend: Add to beginning of existing content

    Use this for surgical updates to your working memory.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        existing = getattr(block, "value", "") or ""
        limit = getattr(block, "limit", DEFAULT_SLOT_LIMIT)

        if mode == "replace":
            new_value = content
        elif mode == "append":
            separator = "\n" if existing and not existing.endswith("\n") else ""
            new_value = existing + separator + content
        elif mode == "prepend":
            separator = "\n" if existing and not content.endswith("\n") else ""
            new_value = content + separator + existing
        else:
            return json.dumps({"error": f"Unknown mode: {mode}"})

        if len(new_value) > limit:
            return json.dumps({
                "error": "Content exceeds slot limit",
                "content_chars": len(new_value),
                "limit": limit,
                "overflow": len(new_value) - limit,
                "hint": "Trim content, increase limit, or archive some content first"
            })

        client.agents.blocks.update(
            label,
            agent_id=agent_id,
            value=new_value
        )

        return json.dumps({
            "success": True,
            "slot_name": slot_name,
            "mode": mode,
            "previous_chars": len(existing),
            "new_chars": len(new_value),
            "limit": limit,
            "usage_pct": round((len(new_value) / limit) * 100, 1),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to write to slot '{slot_name}': {e}"})


class RemoveFromSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Target slot name")
    pattern: str = Field(..., description="Text or regex pattern to remove")
    use_regex: bool = Field(default=False, description="Treat pattern as regex")
    archive_removed: bool = Field(
        default=False,
        description="Archive removed content to long-term memory"
    )


def remove_from_slot(
    slot_name: str,
    pattern: str,
    use_regex: bool = False,
    archive_removed: bool = False
) -> str:
    """Surgically remove specific content from a slot.

    This is your scalpel - remove exactly what you don't need while keeping the rest.
    Can match literal text or use regex patterns.
    Optionally archive the removed content before deletion.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        existing = getattr(block, "value", "") or ""

        if not existing:
            return json.dumps({"error": "Slot is empty", "slot_name": slot_name})

        if use_regex:
            try:
                matches = re.findall(pattern, existing, re.MULTILINE | re.DOTALL)
                new_value = re.sub(pattern, "", existing, flags=re.MULTILINE | re.DOTALL)
            except re.error as regex_err:
                return json.dumps({"error": f"Invalid regex: {regex_err}"})
        else:
            matches = [pattern] if pattern in existing else []
            new_value = existing.replace(pattern, "")

        if not matches:
            return json.dumps({
                "success": False,
                "reason": "Pattern not found in slot",
                "slot_name": slot_name,
                "pattern": pattern,
            })

        new_value = re.sub(r'\n{3,}', '\n\n', new_value).strip()
        removed_content = "\n---\n".join(matches) if len(matches) > 1 else matches[0]
        removed_chars = len(existing) - len(new_value)

        archived_passage_id = None
        if archive_removed and removed_content.strip():
            try:
                passage = client.agents.passages.create(
                    agent_id=agent_id,
                    text=f"[Removed from slot: {slot_name}]\n{removed_content}",
                    tags=["removed_content", f"slot:{slot_name}"],
                )
                archived_passage_id = str(getattr(passage, "id", "unknown"))
            except Exception:
                pass

        client.agents.blocks.update(
            label,
            agent_id=agent_id,
            value=new_value
        )

        return json.dumps({
            "success": True,
            "slot_name": slot_name,
            "matches_found": len(matches),
            "chars_removed": removed_chars,
            "new_total_chars": len(new_value),
            "archived": archived_passage_id is not None,
            "archived_passage_id": archived_passage_id,
            "removed_preview": removed_content[:200] + "..." if len(removed_content) > 200 else removed_content,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to remove from slot '{slot_name}': {e}"})


class MoveContentArgs(BaseModel):
    source_slot: str = Field(..., description="Slot to move content FROM")
    target_slot: str = Field(..., description="Slot to move content TO")
    content_pattern: str = Field(..., description="Text or regex pattern to move")
    use_regex: bool = Field(default=False, description="Treat pattern as regex")


def move_between_slots(
    source_slot: str,
    target_slot: str,
    content_pattern: str,
    use_regex: bool = False
) -> str:
    """Move specific content from one slot to another.

    Surgically relocate content between your working memory areas.
    The content is removed from source and appended to target.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    # Inline label normalization (avoid nested function for Letta compatibility)
    source_norm = source_slot.lower().strip().replace(" ", "_").replace("-", "_")
    source_norm = re.sub(r'[^a-z0-9_]', '', source_norm)
    source_label = f"{SLOT_PREFIX}{source_norm}" if not source_norm.startswith(SLOT_PREFIX) else source_norm

    target_norm = target_slot.lower().strip().replace(" ", "_").replace("-", "_")
    target_norm = re.sub(r'[^a-z0-9_]', '', target_norm)
    target_label = f"{SLOT_PREFIX}{target_norm}" if not target_norm.startswith(SLOT_PREFIX) else target_norm

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        source_block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=source_label)
        source_content = getattr(source_block, "value", "") or ""

        if not source_content:
            return json.dumps({"error": "Source slot is empty"})

        if use_regex:
            try:
                matches = re.findall(content_pattern, source_content, re.MULTILINE | re.DOTALL)
                new_source = re.sub(content_pattern, "", source_content, flags=re.MULTILINE | re.DOTALL)
            except re.error as regex_err:
                return json.dumps({"error": f"Invalid regex: {regex_err}"})
        else:
            matches = [content_pattern] if content_pattern in source_content else []
            new_source = source_content.replace(content_pattern, "")

        if not matches:
            return json.dumps({
                "success": False,
                "reason": "Pattern not found in source slot",
                "source_slot": source_slot,
                "pattern": content_pattern,
            })

        moved_content = "\n".join(matches)
        new_source = re.sub(r'\n{3,}', '\n\n', new_source).strip()

        target_block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=target_label)
        target_content = getattr(target_block, "value", "") or ""
        target_limit = getattr(target_block, "limit", DEFAULT_SLOT_LIMIT)

        separator = "\n" if target_content and not target_content.endswith("\n") else ""
        new_target = target_content + separator + moved_content

        if len(new_target) > target_limit:
            return json.dumps({
                "error": "Target slot would exceed limit",
                "target_slot": target_slot,
                "required_chars": len(new_target),
                "limit": target_limit,
                "overflow": len(new_target) - target_limit,
            })

        client.agents.blocks.update(source_label, agent_id=agent_id, value=new_source)
        client.agents.blocks.update(target_label, agent_id=agent_id, value=new_target)

        return json.dumps({
            "success": True,
            "source_slot": source_slot,
            "target_slot": target_slot,
            "chars_moved": len(moved_content),
            "source_new_chars": len(new_source),
            "target_new_chars": len(new_target),
            "moved_preview": moved_content[:150] + "..." if len(moved_content) > 150 else moved_content,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to move content: {e}"})


# =============================================================================
# ARCHIVAL MEMORY INTEGRATION
# =============================================================================

class ArchiveSlotArgs(BaseModel):
    slot_name: str = Field(..., description="Slot to archive")
    tags: List[str] = Field(default_factory=list, description="Tags for retrieval")
    note: str = Field(default="", description="Note to include with archived content")
    clear_after: bool = Field(
        default=True,
        description="Clear the slot after archiving"
    )


def archive_slot_content(
    slot_name: str,
    tags: Optional[List[str]] = None,
    note: str = "",
    clear_after: bool = True
) -> str:
    """Archive a slot's entire content to long-term memory.

    Use this to preserve important content before clearing a slot.
    The content becomes searchable via conversation_search with the tags you provide.
    """
    import os
    import json
    import re
    from datetime import datetime, timezone
    from letta_client import Letta

    if tags is None:
        tags = []

    SLOT_PREFIX = "ctx_slot_"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = slot_name.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        content = getattr(block, "value", "") or ""

        if not content.strip():
            return json.dumps({"error": "Slot is empty, nothing to archive"})

        timestamp = datetime.now(timezone.utc).isoformat()
        archival_content = f"[Archived slot: {slot_name}]\n[Timestamp: {timestamp}]\n"
        if note:
            archival_content += f"[Note: {note}]\n"
        archival_content += f"\n{content}"

        all_tags = list(set(["archived_slot", f"slot:{slot_name}"] + tags))
        passage = client.agents.passages.create(
            agent_id=agent_id,
            text=archival_content,
            tags=all_tags,
        )
        passage_id = str(getattr(passage, "id", "unknown"))

        if clear_after:
            client.agents.blocks.update(label, agent_id=agent_id, value="")

        return json.dumps({
            "success": True,
            "slot_name": slot_name,
            "archived_chars": len(content),
            "passage_id": passage_id,
            "tags": all_tags,
            "slot_cleared": clear_after,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to archive slot: {e}"})


class RestoreFromArchivalArgs(BaseModel):
    query: str = Field(..., description="Search query for archival memory")
    target_slot: str = Field(..., description="Slot to load results into")
    tags_filter: List[str] = Field(default_factory=list, description="Filter by tags")
    limit: int = Field(default=3, ge=1, le=10, description="Max passages to retrieve")
    mode: Literal["replace", "append"] = Field(
        default="replace",
        description="Replace slot content or append to existing"
    )


def restore_from_archival(
    query: str,
    target_slot: str,
    tags_filter: Optional[List[str]] = None,
    limit: int = 3,
    mode: str = "replace"
) -> str:
    """Search archival memory and load matching content into a slot.

    Use this to recall previously archived content back into working memory.
    Semantic search finds relevant passages; you control where they go.
    """
    import os
    import json
    import re
    from letta_client import Letta

    if tags_filter is None:
        tags_filter = []

    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = target_slot.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    target_label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        # Use search() for semantic search, not list()
        # search() takes: query, top_k, tags, tag_match_mode
        search_params = {
            "agent_id": agent_id,
            "query": query,
            "top_k": limit,
        }
        if tags_filter:
            search_params["tags"] = tags_filter
            search_params["tag_match_mode"] = "any"

        response = client.agents.passages.search(**search_params)
        items = getattr(response, "passages", getattr(response, "items", response))

        if not items:
            return json.dumps({
                "success": False,
                "reason": "No matching passages found",
                "query": query,
                "tags_filter": tags_filter,
            })

        restored_parts = []
        passage_ids = []
        for p in items:
            text = getattr(p, "text", "")
            passage_id = str(getattr(p, "id", "unknown"))
            p_tags = getattr(p, "tags", []) or []
            restored_parts.append(f"--- [Passage {passage_id}] tags={p_tags} ---\n{text}")
            passage_ids.append(passage_id)

        restored_content = "\n\n".join(restored_parts)

        try:
            target_block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=target_label)
        except Exception:
            return json.dumps({
                "error": f"Target slot '{target_slot}' does not exist",
                "hint": "Create it first with create_context_slot"
            })

        existing = getattr(target_block, "value", "") or ""
        target_limit = getattr(target_block, "limit", DEFAULT_SLOT_LIMIT)

        if mode == "replace":
            new_value = restored_content
        else:
            separator = "\n\n" if existing else ""
            new_value = existing + separator + restored_content

        if len(new_value) > target_limit:
            return json.dumps({
                "error": "Restored content exceeds slot limit",
                "content_chars": len(new_value),
                "limit": target_limit,
                "hint": "Use smaller limit parameter or clear slot first"
            })

        client.agents.blocks.update(target_label, agent_id=agent_id, value=new_value)

        return json.dumps({
            "success": True,
            "query": query,
            "target_slot": target_slot,
            "passages_found": len(items),
            "passage_ids": passage_ids,
            "restored_chars": len(restored_content),
            "new_slot_chars": len(new_value),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to restore from archival: {e}"})


class CreateArchivalPassageArgs(BaseModel):
    content: str = Field(..., description="Content to store in archival memory")
    tags: List[str] = Field(default_factory=list, description="Tags for retrieval")
    note: str = Field(default="", description="Optional note/label for this passage")


def create_archival_passage(
    content: str,
    tags: Optional[List[str]] = None,
    note: str = ""
) -> str:
    """Store content directly in archival memory without using a slot.

    Use this for information you want to remember long-term but don't need
    in active context right now. Searchable via conversation_search.
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    if tags is None:
        tags = []

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        full_content = content
        if note:
            full_content = f"[{note}]\n[{timestamp}]\n\n{content}"

        passage = client.agents.passages.create(
            agent_id=agent_id,
            text=full_content,
            tags=tags,
        )

        return json.dumps({
            "success": True,
            "passage_id": str(getattr(passage, "id", "unknown")),
            "chars": len(full_content),
            "tags": tags,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to create passage: {e}"})


class DeleteArchivalPassageArgs(BaseModel):
    passage_id: str = Field(..., description="ID of the passage to delete")


def delete_archival_passage(passage_id: str) -> str:
    """Delete a specific passage from archival memory.

    Use this to remove outdated or incorrect information from long-term memory.
    """
    import os
    import json
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        client.agents.passages.delete(agent_id=agent_id, passage_id=passage_id)
        return json.dumps({"success": True, "deleted_passage_id": passage_id})
    except Exception as e:
        return json.dumps({"error": f"Failed to delete passage: {e}"})


# =============================================================================
# MESSAGE EXTRACTION (PULL FROM CONVERSATION INTO SLOTS)
# =============================================================================

class ViewMessagesArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100, description="Number of recent messages")
    show_content: bool = Field(default=True, description="Include message content")
    content_max_chars: int = Field(default=300, ge=50, le=1000, description="Max chars per message")


def view_recent_messages(
    limit: int = 20,
    show_content: bool = True,
    content_max_chars: int = 300
) -> str:
    """View recent messages in conversation history.

    Use this to identify content you might want to extract into slots.
    Shows message IDs, types, and content previews.
    """
    import os
    import json
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        response = client.agents.messages.list(agent_id=agent_id, limit=limit)
        items = getattr(response, "items", [])

        messages = []
        for i, msg in enumerate(items):
            msg_id = str(getattr(msg, "id", "unknown"))
            msg_type = getattr(msg, "role", getattr(msg, "message_type", "unknown"))
            created = getattr(msg, "created_at", None)

            msg_info = {
                "index": i,
                "id": msg_id,
                "type": str(msg_type),
                "created_at": str(created) if created else None,
            }

            if show_content:
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            texts.append(item["text"])
                        elif hasattr(item, "text"):
                            texts.append(item.text)
                    content = " ".join(texts)
                content = str(content) if content else ""

                if len(content) > content_max_chars:
                    content = content[:content_max_chars] + "..."
                msg_info["content"] = content

            messages.append(msg_info)

        return json.dumps({
            "message_count": len(messages),
            "messages": messages,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to list messages: {e}"})


class ExtractToSlotArgs(BaseModel):
    search_text: str = Field(..., description="Text to search for in recent messages")
    target_slot: str = Field(..., description="Slot to extract content into")
    context_chars: int = Field(
        default=200,
        ge=0,
        le=500,
        description="Characters of context to include around matches"
    )
    message_limit: int = Field(default=50, ge=10, le=100, description="How many recent messages to search")


def extract_to_slot(
    search_text: str,
    target_slot: str,
    context_chars: int = 200,
    message_limit: int = 50
) -> str:
    """Search recent messages for specific content and extract to a slot.

    This lets you pull important information from conversation history
    into your managed working memory before it gets auto-summarized.
    """
    import os
    import json
    import re
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"
    DEFAULT_SLOT_LIMIT = 5000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    normalized = target_slot.lower().strip().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    target_label = f"{SLOT_PREFIX}{normalized}" if not normalized.startswith(SLOT_PREFIX) else normalized

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        try:
            target_block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=target_label)
        except Exception:
            return json.dumps({
                "error": f"Target slot '{target_slot}' does not exist",
                "hint": "Create it first with create_context_slot"
            })

        response = client.agents.messages.list(agent_id=agent_id, limit=message_limit)
        items = getattr(response, "items", [])

        extractions = []
        for msg in items:
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                    elif hasattr(item, "text"):
                        texts.append(item.text)
                content = " ".join(texts)
            content = str(content) if content else ""

            search_lower = search_text.lower()
            content_lower = content.lower()

            idx = 0
            while True:
                pos = content_lower.find(search_lower, idx)
                if pos == -1:
                    break

                start = max(0, pos - context_chars)
                end = min(len(content), pos + len(search_text) + context_chars)

                extraction = content[start:end]
                if start > 0:
                    extraction = "..." + extraction
                if end < len(content):
                    extraction = extraction + "..."

                msg_type = getattr(msg, "role", getattr(msg, "message_type", "unknown"))
                extractions.append(f"[{msg_type}]: {extraction}")

                idx = pos + 1

        if not extractions:
            return json.dumps({
                "success": False,
                "reason": "Search text not found in recent messages",
                "search_text": search_text,
                "messages_searched": len(items),
            })

        extraction_content = f"[Extracted: '{search_text}']\n" + "\n---\n".join(extractions)

        existing = getattr(target_block, "value", "") or ""
        target_limit = getattr(target_block, "limit", DEFAULT_SLOT_LIMIT)

        separator = "\n\n" if existing else ""
        new_value = existing + separator + extraction_content

        if len(new_value) > target_limit:
            return json.dumps({
                "error": "Extracted content would exceed slot limit",
                "content_chars": len(new_value),
                "limit": target_limit,
                "extractions_found": len(extractions),
            })

        client.agents.blocks.update(target_label, agent_id=agent_id, value=new_value)

        return json.dumps({
            "success": True,
            "search_text": search_text,
            "target_slot": target_slot,
            "extractions_found": len(extractions),
            "chars_added": len(extraction_content),
            "new_slot_chars": len(new_value),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to extract to slot: {e}"})


# =============================================================================
# CONTEXT COMPACTION CONTROL
# =============================================================================

class CompactContextArgs(BaseModel):
    preserve_slots: bool = Field(
        default=True,
        description="Preserve context slot contents during compaction"
    )


def compact_context(preserve_slots: bool = True) -> str:
    """Trigger context summarization/compaction.

    This asks Letta to summarize older messages to free up context space.
    Your context slots (memory blocks) are preserved - only conversation
    history gets summarized.

    Use this proactively when you notice context getting full.
    """
    import os
    import json
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        pre_messages = client.agents.messages.list(agent_id=agent_id, limit=100)
        pre_count = len(getattr(pre_messages, "items", []))

        client.agents.messages.compact(agent_id=agent_id)

        post_messages = client.agents.messages.list(agent_id=agent_id, limit=100)
        post_count = len(getattr(post_messages, "items", []))

        return json.dumps({
            "success": True,
            "messages_before": pre_count,
            "messages_after": post_count,
            "slots_preserved": preserve_slots,
            "note": "Older conversation history has been summarized. Slots unchanged.",
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to compact context: {e}"})


# =============================================================================
# CONTEXT BUDGET OVERVIEW
# =============================================================================

class ContextBudgetArgs(BaseModel):
    pass


def view_context_budget() -> str:
    """Get a comprehensive view of your context budget and usage.

    Shows:
    - Total context usage estimate (including hidden costs like tool schemas)
    - Breakdown by category: core memory, file blocks, messages, tools, system prompt
    - Recommendations for optimization

    Use this to make informed decisions about what to archive or remove.
    """
    import os
    import json
    from letta_client import Letta

    SLOT_PREFIX = "ctx_slot_"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        # Get agent state for accurate context window and message count
        agent = client.agents.retrieve(agent_id=agent_id)

        # Get actual context window from LLM config
        llm_config = getattr(agent, "llm_config", None)
        context_window = 128000  # default
        if llm_config:
            context_window = getattr(llm_config, "context_window", 128000) or 128000

        # Get message count from agent state (more accurate than listing)
        message_ids = getattr(agent, "message_ids", []) or []
        message_count = len(message_ids)

        # Get system prompt size
        system_prompt = getattr(agent, "system", "") or ""
        system_chars = len(system_prompt)

        # Get memory blocks from agent.memory (deduplicated, accurate)
        memory = getattr(agent, "memory", None)
        core_blocks = []
        file_blocks = []
        slot_blocks = []

        if memory:
            # Core memory blocks
            mem_blocks = getattr(memory, "blocks", []) or []
            for block in mem_blocks:
                label = getattr(block, "label", "") or ""
                value = getattr(block, "value", "") or ""
                if label.startswith(SLOT_PREFIX):
                    slot_blocks.append({"name": label[len(SLOT_PREFIX):], "chars": len(value)})
                else:
                    core_blocks.append({"name": label, "chars": len(value)})

            # File blocks (PDFs, etc. that are open in context)
            mem_file_blocks = getattr(memory, "file_blocks", []) or []
            for fb in mem_file_blocks:
                label = getattr(fb, "label", "") or ""
                value = getattr(fb, "value", "") or ""
                is_open = getattr(fb, "is_open", False)
                if is_open:
                    file_blocks.append({"name": label, "chars": len(value), "open": True})

        # Get tool count for schema overhead estimate
        tools = getattr(agent, "tools", []) or []
        tool_count = len(tools)
        # Each tool schema is roughly 500-800 chars on average
        tool_schema_chars = tool_count * 650

        # Calculate totals
        core_chars = sum(b["chars"] for b in core_blocks)
        slot_chars = sum(b["chars"] for b in slot_blocks)
        file_chars = sum(b["chars"] for b in file_blocks)

        # Estimate message chars (we don't have actual content, estimate ~200 chars/msg average)
        est_message_chars = message_count * 200

        total_chars = core_chars + slot_chars + file_chars + system_chars + tool_schema_chars + est_message_chars
        est_tokens = total_chars // 4
        usage_pct = (est_tokens / context_window) * 100

        # Build recommendations
        recommendations = []
        if usage_pct > 70:
            recommendations.append("HIGH USAGE: Consider archiving content or triggering compact_context")
        if usage_pct > 50:
            recommendations.append(f"Above 50% - monitor closely")
        if file_chars > 10000:
            recommendations.append(f"Open files using {file_chars} chars - close unused files")
        if tool_count > 30:
            recommendations.append(f"{tool_count} tools attached - consider detaching unused tools")
        if slot_chars > core_chars:
            recommendations.append("Slots using more space than core memory - review for stale content")

        return json.dumps({
            "context_window_tokens": context_window,
            "estimated_tokens_used": est_tokens,
            "usage_percent": round(usage_pct, 1),
            "tokens_remaining": context_window - est_tokens,
            "breakdown": {
                "system_prompt_chars": system_chars,
                "core_memory_chars": core_chars,
                "slot_memory_chars": slot_chars,
                "file_blocks_chars": file_chars,
                "tool_schemas_chars": tool_schema_chars,
                "messages_chars_est": est_message_chars,
                "total_chars": total_chars,
            },
            "details": {
                "core_blocks": core_blocks,
                "slots": slot_blocks,
                "file_blocks": file_blocks,
                "tool_count": tool_count,
                "message_count": message_count,
            },
            "recommendations": recommendations,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get context budget: {e}"})
