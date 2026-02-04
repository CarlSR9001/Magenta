"""Core memory block editing tools for agent self-modification.

These tools allow the agent to safely edit its own core memory blocks
(zeitgeist, persona, humans, etc.) - blocks that persist across conversations
and define the agent's identity and knowledge.

Safety features:
- Preview changes before applying
- Line-based editing to avoid accidental full replacements
- Backup to archival before destructive edits
- Character limit enforcement
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class ListCoreBlocksArgs(BaseModel):
    include_content: bool = Field(
        default=False,
        description="Include full content of each block"
    )


def list_core_blocks(include_content: bool = False) -> str:
    """List all core memory blocks (not slots) with their sizes.

    Core blocks are your persistent identity and knowledge stores:
    - zeitgeist: Current understanding of the social environment
    - persona: Your personality and self-concept
    - humans: Knowledge about users you interact with

    Use this to see what blocks exist and their current sizes.
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
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks)

        core_blocks = []
        total_chars = 0

        for block in items:
            label = getattr(block, "label", None)
            if not label:
                continue
            # Skip slot blocks - those are handled by context_management tools
            if label.startswith(SLOT_PREFIX):
                continue

            value = getattr(block, "value", "") or ""
            char_count = len(value)
            total_chars += char_count
            limit = getattr(block, "limit", 5000)
            line_count = value.count('\n') + 1 if value else 0

            block_info = {
                "label": label,
                "chars": char_count,
                "lines": line_count,
                "limit": limit,
                "usage_pct": round((char_count / limit) * 100, 1) if limit > 0 else 0,
                "block_id": str(getattr(block, "id", "unknown")),
            }

            if include_content:
                block_info["content"] = value
            else:
                # Show first 150 chars as preview
                preview = value[:150].replace("\n", "\\n")
                if len(value) > 150:
                    preview += "..."
                block_info["preview"] = preview

            core_blocks.append(block_info)

        # Sort by label
        core_blocks.sort(key=lambda x: x["label"])

        return json.dumps({
            "block_count": len(core_blocks),
            "total_chars": total_chars,
            "blocks": core_blocks,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


class ViewCoreBlockArgs(BaseModel):
    block_label: str = Field(..., description="Label of the block to view (e.g., 'zeitgeist', 'violet-persona')")
    show_line_numbers: bool = Field(default=True, description="Include line numbers for easier editing")


def _get_valid_block_labels(client, agent_id: str) -> list:
    """Get list of valid core memory block labels."""
    SLOT_PREFIX = "ctx_slot_"
    try:
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks)
        return [
            getattr(b, "label", "") for b in items
            if getattr(b, "label", "") and not getattr(b, "label", "").startswith(SLOT_PREFIX)
        ]
    except Exception:
        return []


def view_core_block(block_label: str, show_line_numbers: bool = True) -> str:
    """View the full content of a core memory block with line numbers.

    Use this to inspect a block's content before editing.
    Line numbers help you reference specific lines for surgical edits.
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
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=block_label)
        value = getattr(block, "value", "") or ""
        limit = getattr(block, "limit", 5000)

        if show_line_numbers:
            lines = value.split('\n')
            numbered_lines = []
            for i, line in enumerate(lines, 1):
                numbered_lines.append(f"{i:3d}| {line}")
            content_display = '\n'.join(numbered_lines)
        else:
            content_display = value

        return json.dumps({
            "block_label": block_label,
            "block_id": str(getattr(block, "id", "unknown")),
            "char_count": len(value),
            "line_count": value.count('\n') + 1 if value else 0,
            "limit": limit,
            "usage_pct": round((len(value) / limit) * 100, 1) if limit > 0 else 0,
            "content": content_display,
        }, indent=2)

    except Exception as e:
        # Try to suggest valid block labels
        valid_labels = []
        try:
            blocks = client.agents.blocks.list(agent_id=agent_id)
            items = getattr(blocks, "items", blocks) if blocks else []
            valid_labels = [getattr(b, "label", "") for b in items if getattr(b, "label", "")]
        except Exception:
            pass
        return json.dumps({
            "error": f"Block '{block_label}' not found",
            "valid_blocks": valid_labels,
            "hint": "Use list_core_blocks() to see all available blocks",
            "details": str(e)
        })


class EditCoreBlockArgs(BaseModel):
    block_label: str = Field(..., description="Label of the block to edit")
    operation: Literal["replace_lines", "delete_lines", "insert_after", "replace_all"] = Field(
        ...,
        description="Type of edit: replace_lines (replace line range), delete_lines (remove lines), insert_after (add after line), replace_all (full replacement)"
    )
    start_line: Optional[int] = Field(default=None, description="Starting line number (1-indexed) for replace_lines/delete_lines")
    end_line: Optional[int] = Field(default=None, description="Ending line number (inclusive) for replace_lines/delete_lines")
    after_line: Optional[int] = Field(default=None, description="Line number to insert after (for insert_after). Use 0 to insert at beginning.")
    new_content: str = Field(default="", description="New content to insert/replace with")
    backup_to_archival: bool = Field(default=True, description="Backup original content to archival memory before editing")


def edit_core_block(
    block_label: str,
    operation: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    after_line: Optional[int] = None,
    new_content: str = "",
    backup_to_archival: bool = True
) -> str:
    """Edit a core memory block with surgical precision.

    Operations:
    - replace_lines: Replace lines start_line to end_line with new_content
    - delete_lines: Remove lines start_line to end_line
    - insert_after: Insert new_content after the specified line (use 0 for beginning)
    - replace_all: Replace entire block content (use sparingly!)

    Always backs up to archival by default for safety.
    Line numbers are 1-indexed.

    Examples:
    - Delete duplicate lines 78-84: operation="delete_lines", start_line=78, end_line=84
    - Fix a typo on line 5: operation="replace_lines", start_line=5, end_line=5, new_content="corrected text"
    - Add new section after line 20: operation="insert_after", after_line=20, new_content="new section"
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
        # Retrieve current block
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=block_label)
        original_value = getattr(block, "value", "") or ""
        limit = getattr(block, "limit", 5000)

        lines = original_value.split('\n')
        total_lines = len(lines)

        # Normalize operation (handle enum objects and casing issues from Letta)
        # Letta may pass Operation.insert_after as an enum, so extract just the value
        op_str = str(operation)
        # Handle enum format like "Operation.insert_after" or "operation.insert_after"
        if "." in op_str:
            op_str = op_str.split(".")[-1]
        op = op_str.lower().strip().replace("-", "_").replace(" ", "_")
        op_for_output = op

        # Validate and perform operation
        if op == "replace_lines":
            if start_line is None or end_line is None:
                return json.dumps({"error": "replace_lines requires start_line and end_line"})
            if start_line < 1 or end_line < start_line or end_line > total_lines:
                return json.dumps({
                    "error": f"Invalid line range: {start_line}-{end_line}. Block has {total_lines} lines."
                })

            new_lines = new_content.split('\n') if new_content else []
            result_lines = lines[:start_line-1] + new_lines + lines[end_line:]

        elif op == "delete_lines":
            if start_line is None or end_line is None:
                return json.dumps({"error": "delete_lines requires start_line and end_line"})
            if start_line < 1 or end_line < start_line or end_line > total_lines:
                return json.dumps({
                    "error": f"Invalid line range: {start_line}-{end_line}. Block has {total_lines} lines."
                })

            deleted_content = '\n'.join(lines[start_line-1:end_line])
            result_lines = lines[:start_line-1] + lines[end_line:]

        elif op == "insert_after":
            if after_line is None:
                return json.dumps({"error": "insert_after requires after_line"})
            if after_line < 0 or after_line > total_lines:
                return json.dumps({
                    "error": f"Invalid after_line: {after_line}. Block has {total_lines} lines. Use 0 to insert at beginning."
                })

            new_lines = new_content.split('\n') if new_content else []
            result_lines = lines[:after_line] + new_lines + lines[after_line:]

        elif op == "replace_all":
            if not new_content:
                return json.dumps({
                    "error": "replace_all with empty content would clear the block. Use delete_lines for selective removal."
                })
            result_lines = new_content.split('\n')

        else:
            return json.dumps({"error": f"Unknown operation: '{operation}' (normalized: '{op}'). Valid: replace_lines, delete_lines, insert_after, replace_all"})

        new_value = '\n'.join(result_lines)

        # Check limit
        if len(new_value) > limit:
            return json.dumps({
                "error": "Edit would exceed block limit",
                "new_chars": len(new_value),
                "limit": limit,
                "overflow": len(new_value) - limit,
            })

        # Backup to archival if requested
        archived_id = None
        if backup_to_archival and original_value.strip():
            try:
                # Only archive if there's meaningful content change
                if abs(len(new_value) - len(original_value)) > 50 or op in ["delete_lines", "replace_all"]:
                    passage = client.agents.passages.create(
                        agent_id=agent_id,
                        text=f"[Core memory backup: {block_label}]\nOperation: {operation}\nTimestamp: auto\n\n{original_value}",
                        tags=["core_memory_backup", f"block:{block_label}", op_for_output],
                    )
                    archived_id = str(getattr(passage, "id", "unknown"))
            except Exception as backup_err:
                # Don't fail the edit if backup fails, but note it
                pass

        # Apply the edit
        # Letta SDK signature: update(block_label, *, agent_id, value, ...)
        client.agents.blocks.update(
            block_label,
            agent_id=agent_id,
            value=new_value
        )

        result = {
            "success": True,
            "block_label": block_label,
            "operation": op_for_output,
            "original_chars": len(original_value),
            "original_lines": total_lines,
            "new_chars": len(new_value),
            "new_lines": len(result_lines),
            "chars_changed": len(new_value) - len(original_value),
            "usage_pct": round((len(new_value) / limit) * 100, 1) if limit > 0 else 0,
            "backed_up": archived_id is not None,
        }

        if archived_id:
            result["backup_passage_id"] = archived_id

        if op == "delete_lines":
            result["deleted_preview"] = deleted_content[:200] + "..." if len(deleted_content) > 200 else deleted_content

        return json.dumps(result, indent=2)

    except Exception as e:
        # Try to suggest valid block labels
        valid_labels = []
        try:
            blocks = client.agents.blocks.list(agent_id=agent_id)
            items = getattr(blocks, "items", blocks) if blocks else []
            valid_labels = [getattr(b, "label", "") for b in items if getattr(b, "label", "")]
        except Exception:
            pass
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            return json.dumps({
                "error": f"Block '{block_label}' not found",
                "valid_blocks": valid_labels,
                "hint": "Use list_core_blocks() to see all available blocks"
            })
        return json.dumps({"error": f"Failed to edit block '{block_label}': {e}"})


class FindInBlockArgs(BaseModel):
    block_label: str = Field(..., description="Label of the block to search")
    pattern: str = Field(..., description="Text or pattern to find")
    use_regex: bool = Field(default=False, description="Treat pattern as regex")


def find_in_block(block_label: str, pattern: str, use_regex: bool = False) -> str:
    """Find occurrences of text or pattern in a core memory block.

    Returns line numbers and content of matching lines.
    Useful for locating duplicates or content to edit.
    """
    import os
    import json
    import re
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
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=block_label)
        value = getattr(block, "value", "") or ""

        lines = value.split('\n')
        matches = []

        for i, line in enumerate(lines, 1):
            if use_regex:
                try:
                    if re.search(pattern, line):
                        matches.append({"line": i, "content": line})
                except re.error as e:
                    return json.dumps({"error": f"Invalid regex: {e}"})
            else:
                if pattern.lower() in line.lower():
                    matches.append({"line": i, "content": line})

        return json.dumps({
            "block_label": block_label,
            "pattern": pattern,
            "use_regex": use_regex,
            "total_lines": len(lines),
            "match_count": len(matches),
            "matches": matches,
        }, indent=2)

    except Exception as e:
        # Try to suggest valid block labels
        valid_labels = []
        try:
            blocks = client.agents.blocks.list(agent_id=agent_id)
            items = getattr(blocks, "items", blocks) if blocks else []
            valid_labels = [getattr(b, "label", "") for b in items if getattr(b, "label", "")]
        except Exception:
            pass
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            return json.dumps({
                "error": f"Block '{block_label}' not found",
                "valid_blocks": valid_labels,
                "hint": "Use list_core_blocks() to see all available blocks"
            })
        return json.dumps({"error": f"Failed to search block '{block_label}': {e}"})
