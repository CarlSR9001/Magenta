"""Tools for inspecting agent context window usage."""

from typing import Optional
from pydantic import BaseModel, Field


class ContextUsageArgs(BaseModel):
    limit: int = Field(default=50, ge=1, le=100, description="Number of recent messages to inspect")


def view_context_usage(limit: int = 50) -> str:
    """
    Get a quick overview of context window usage.

    For detailed breakdown including blocks and tools, use view_context_budget instead.
    This is a lighter-weight check for message counts and basic estimates.

    Args:
        limit: Number of recent messages to inspect (default 50)

    Returns:
        Summary of message counts, types, and estimated token usage
    """
    import os
    import json
    from letta_client import Letta

    CONTEXT_WINDOW_SIZE = 128000

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return "Error: LETTA_API_KEY and LETTA_AGENT_ID must be set"

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        client = Letta(api_key=api_key) if api_key else Letta()

    try:
        # Fetch messages
        response = client.agents.messages.list(agent_id=agent_id, limit=limit)
        messages = getattr(response, "items", [])

        if not messages:
            return "Context is empty."

        count = len(messages)

        # Message type breakdown (inline logic, no nested functions)
        type_counts = {"user": 0, "assistant": 0, "tool": 0, "system": 0, "other": 0}
        total_chars = 0

        for m in messages:
            # Get message type inline
            msg_type = "unknown"
            for attr in ["role", "message_type", "type"]:
                val = getattr(m, attr, None)
                if val:
                    msg_type = str(val).lower()
                    break

            # Categorize
            if msg_type in type_counts:
                type_counts[msg_type] += 1
            elif msg_type in ("tool_call", "tool_result", "function", "function_call"):
                type_counts["tool"] += 1
            else:
                type_counts["other"] += 1

            # Get content length inline
            content = getattr(m, "content", None)
            if content:
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            total_chars += len(item["text"])
                        elif hasattr(item, "text"):
                            total_chars += len(item.text)

        # Calculate estimates
        est_tokens = total_chars // 4
        usage_percent = (est_tokens / CONTEXT_WINDOW_SIZE) * 100

        # Memory pressure
        if usage_percent < 25:
            pressure = "LOW"
        elif usage_percent < 60:
            pressure = "MEDIUM"
        else:
            pressure = "HIGH"

        # Build type breakdown string
        type_parts = []
        for t in ["user", "assistant", "tool", "system", "other"]:
            if type_counts[t] > 0:
                type_parts.append(f"{t}: {type_counts[t]}")
        type_breakdown = ", ".join(type_parts)

        # Get timestamps if available
        newest_time = getattr(messages[0], "created_at", None) if messages else None
        oldest_time = getattr(messages[-1], "created_at", None) if messages else None

        # Build output
        lines = [
            "Context Usage (Quick View)",
            "=" * 26,
            f"Messages: {count} ({type_breakdown})",
            f"Est. Tokens: ~{est_tokens:,} ({usage_percent:.1f}% of {CONTEXT_WINDOW_SIZE:,})",
            f"Memory Pressure: {pressure}",
            "",
        ]

        if newest_time:
            lines.append(f"Newest: {newest_time}")
        if oldest_time:
            lines.append(f"Oldest: {oldest_time}")

        lines.append("")
        lines.append("Tip: Use view_context_budget for detailed breakdown.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"
