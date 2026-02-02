"""Hypercontext - Spatial context awareness for Magenta.

Adapted from hypercontext.sh for Letta agents. Renders session state as ASCII map
showing pressures, context, slots, tools, and systems.

Usage (from agent):
  hypercontext_map()           - Full visualization
  hypercontext_compact()       - Dense format for context recovery
"""

from typing import Optional
from pydantic import BaseModel, Field


class HypercontextArgs(BaseModel):
    """Args for hypercontext visualization."""
    mode: str = Field(
        default="full",
        description="Visualization mode: 'full' or 'compact'"
    )


def hypercontext_map() -> str:
    """Generate full hypercontext visualization of current session state.

    Shows:
    - Context usage bar and runway
    - Signal pressures (internal drives) with heat ranking
    - Context slots (working memory)
    - Recent tool activity
    - System connectivity status
    - Recent outcomes and open items

    Use this to understand your current state at a glance.
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")

    if not api_key or not agent_id:
        return "ERROR: LETTA_API_KEY and LETTA_AGENT_ID must be set"

    try:
        client = Letta(api_key=api_key)
    except Exception as e:
        return f"ERROR: Failed to connect to Letta: {e}"

    now = datetime.now(timezone.utc)

    # =========================================================================
    # COLLECT DATA
    # =========================================================================

    # 1. Context budget
    context_pct = 0
    context_tokens = 0
    max_tokens = 128000
    message_count = 0
    sync_context = None
    try:
        from pathlib import Path
        sync_path = Path("state/sync_state.json")
        if sync_path.exists():
            sync_context = json.loads(sync_path.read_text(encoding="utf-8"))
    except Exception:
        sync_context = None
    if sync_context and sync_context.get("context"):
        try:
            context_pct = int(sync_context["context"].get("usage_pct", 0))
        except Exception:
            context_pct = 0
    else:
        try:
            agent = client.agents.retrieve(agent_id=agent_id)
            messages = list(client.agents.messages.list(agent_id=agent_id, limit=200))
            message_count = len(messages)
            # Estimate: 500 tokens per message average
            context_tokens = message_count * 500
            context_pct = min(100, int((context_tokens / max_tokens) * 100))
        except Exception:
            pass

    # 2. Context slots
    slots = []
    try:
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks) if blocks else []
        for block in items:
            label = getattr(block, "label", "")
            if label.startswith("ctx_slot_"):
                value = getattr(block, "value", "") or ""
                limit = getattr(block, "limit", 5000)
                slots.append({
                    "name": label[9:],  # Remove "ctx_slot_" prefix
                    "chars": len(value),
                    "limit": limit,
                    "modified": len(value) > 0,
                })
    except Exception:
        pass

    # 3. Interoception state (from archival)
    pressures = {}
    total_emissions = 0
    last_wake = None
    quiet_until = None
    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search="[INTEROCEPTION_STATE]",
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []
        for passage in items:
            text = getattr(passage, "text", "")
            if text.startswith("[INTEROCEPTION_STATE]"):
                state = json.loads(text[len("[INTEROCEPTION_STATE]"):].strip())
                pressures = state.get("pressures", {})
                total_emissions = state.get("total_emissions", 0)
                last_wake = state.get("last_wake")
                quiet_until = state.get("quiet_until")
                break
    except Exception:
        pass

    if sync_context and sync_context.get("limbic"):
        try:
            last_wake = sync_context["limbic"].get("last_wake", last_wake)
            total_emissions = sync_context["limbic"].get("total_emissions", total_emissions)
            quiet_until = sync_context["limbic"].get("quiet_until", quiet_until)
        except Exception:
            pass

    # 4. Recent tool activity (from messages)
    tool_counts = {}
    recent_outcomes = []
    try:
        for msg in messages[:50]:  # Last 50 messages
            msg_type = getattr(msg, "message_type", "")
            if msg_type == "tool_call_message":
                # Extract tool name from message
                content = getattr(msg, "content", "") or ""
                if "(" in content:
                    tool_name = content.split("(")[0].strip()
                    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
            elif msg_type == "tool_return_message":
                content = getattr(msg, "content", "") or ""
                if "success" in content.lower():
                    recent_outcomes.append("✓")
                elif "error" in content.lower():
                    recent_outcomes.append("✗")
    except Exception:
        pass

    # =========================================================================
    # BUILD VISUALIZATION
    # =========================================================================

    # Context bar (35 chars)
    bar_filled = int((context_pct / 100) * 35)
    bar_empty = 35 - bar_filled
    ctx_bar = "▓" * bar_filled + "░" * bar_empty
    runway = max_tokens - context_tokens

    # Velocity sparkline (based on emissions)
    velocity = "▁▂▃▄▅▆▇█"[:min(8, total_emissions // 10 + 1)] if total_emissions > 0 else "▁"

    # Current time
    time_str = now.strftime("%Y-%m-%d %H:%M UTC")

    # Build pressure heat map (sorted by recency)
    pressure_items = []
    for signal_name, pstate in pressures.items():
        pressure = pstate.get("pressure", 0)
        emissions = pstate.get("emission_count", 0)
        last_emitted = pstate.get("last_emitted")

        # Calculate recency (seconds ago)
        recency = float('inf')
        if last_emitted:
            try:
                then = datetime.fromisoformat(last_emitted)
                recency = (now - then).total_seconds()
            except Exception:
                pass

        # Heat bars based on recency (< 5min = hot, > 1hr = cold)
        if recency < 300:
            heat = "████"
        elif recency < 900:
            heat = "███░"
        elif recency < 1800:
            heat = "██░░"
        elif recency < 3600:
            heat = "█░░░"
        else:
            heat = "░░░░"

        pressure_items.append({
            "name": signal_name.upper(),
            "pressure": pressure,
            "emissions": emissions,
            "heat": heat,
            "recency": recency,
        })

    # Sort by recency (most recent first)
    pressure_items.sort(key=lambda x: x["recency"])

    # Build slots display
    slot_lines = []
    for slot in slots[:6]:  # Max 6 slots
        marker = "◆" if slot["modified"] else "◇"
        name = slot["name"][:12].ljust(12)
        slot_lines.append(f"  {name} {marker}")

    # Build tools display
    tool_lines = []
    sorted_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
    max_count = max((c for _, c in sorted_tools), default=1)
    for tool_name, count in sorted_tools:
        bar_len = int((count / max_count) * 8)
        bar = "█" * bar_len
        name = tool_name[:12].ljust(12)
        tool_lines.append(f"  {name} {bar.ljust(8)} {count}")

    # Systems status
    systems = [
        ("Letta", "✓"),  # We're connected if we got here
        ("Bluesky", "?"),  # Would need to check
        ("Moltbook", "?"),
    ]

    # Quiet mode indicator
    quiet_str = ""
    if quiet_until:
        try:
            until = datetime.fromisoformat(quiet_until)
            if until > now:
                remaining = (until - now).total_seconds() / 3600
                quiet_str = f" [QUIET {remaining:.1f}h]"
        except Exception:
            pass

    # =========================================================================
    # RENDER ASCII
    # =========================================================================

    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════════════╗")
    lines.append(f"║  HYPERCONTEXT — {time_str}{quiet_str.ljust(20)}  ║")
    lines.append(f"║  ctx {ctx_bar} ~{context_pct}% ({context_tokens//1000}k/{max_tokens//1000}k)     ║")
    lines.append(f"║  {velocity.ljust(10)} velocity ─────────────── runway: ~{runway//1000}k tokens      ║")
    lines.append("╠══════════════════════════════════════════════════════════════════════╣")
    lines.append("║                                                                      ║")
    lines.append("║  SIGNALS (pressure)            HEAT (recency)                       ║")

    # Show top 6 signals
    for i, p in enumerate(pressure_items[:6]):
        pbar_len = int(p["pressure"] * 10)
        pbar = "▓" * pbar_len + "░" * (10 - pbar_len)
        name = p["name"][:10].ljust(10)
        line = f"║  {name} {pbar} {p['pressure']:.2f}    {p['heat']} {p['name'][:8].ljust(8)} ({p['emissions']})    ║"
        lines.append(line)

    lines.append("║                                                                      ║")
    lines.append("║  SLOTS (memory)          TOOLS (recent)       SYSTEMS               ║")

    # Combine slots, tools, systems
    max_rows = max(len(slot_lines), len(tool_lines), len(systems))
    for i in range(max_rows):
        slot_col = slot_lines[i] if i < len(slot_lines) else "                "
        tool_col = tool_lines[i] if i < len(tool_lines) else "                        "
        sys_col = f"  {systems[i][0]} {systems[i][1]}" if i < len(systems) else "         "
        lines.append(f"║{slot_col.ljust(22)}{tool_col.ljust(26)}{sys_col.ljust(18)}║")

    lines.append("║                                                                      ║")

    # Recent outcomes
    outcome_str = "".join(recent_outcomes[-20:]) if recent_outcomes else "(no recent outcomes)"
    lines.append(f"║  OUTCOMES: {outcome_str.ljust(55)} ║")
    lines.append(f"║  EMISSIONS: {total_emissions} total | MESSAGES: {message_count}".ljust(71) + "║")

    lines.append("║                                                                      ║")
    lines.append("╚══════════════════════════════════════════════════════════════════════╝")

    return "\n".join(lines)


def hypercontext_compact() -> str:
    """Generate compact hypercontext for context recovery.

    Dense markdown format suitable for continuation prompts.
    Use this when context is high or for session handoff.
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")

    if not api_key or not agent_id:
        return "ERROR: LETTA_API_KEY and LETTA_AGENT_ID must be set"

    try:
        client = Letta(api_key=api_key)
    except Exception as e:
        return f"ERROR: {e}"

    now = datetime.now(timezone.utc)

    # Collect minimal data
    context_pct = 0
    message_count = 0
    try:
        messages = list(client.agents.messages.list(agent_id=agent_id, limit=200))
        message_count = len(messages)
        context_pct = min(100, int((message_count * 500 / 128000) * 100))
    except Exception:
        pass

    # Get pressures
    pressures = {}
    total_emissions = 0
    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search="[INTEROCEPTION_STATE]",
            limit=1
        )
        items = getattr(passages, "items", passages) if passages else []
        for passage in items:
            text = getattr(passage, "text", "")
            if text.startswith("[INTEROCEPTION_STATE]"):
                state = json.loads(text[len("[INTEROCEPTION_STATE]"):].strip())
                pressures = state.get("pressures", {})
                total_emissions = state.get("total_emissions", 0)
                break
    except Exception:
        pass

    # Get slots
    slots = []
    try:
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks) if blocks else []
        for block in items:
            label = getattr(block, "label", "")
            if label.startswith("ctx_slot_"):
                value = getattr(block, "value", "") or ""
                slots.append(f"{label[9:]}: {len(value)} chars")
    except Exception:
        pass

    # Build compact output
    lines = [
        f"# Hypercontext — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"ctx: ~{context_pct}% | runway: ~{(128000 - message_count*500)//1000}k | msgs: {message_count} | emissions: {total_emissions}",
        "",
        "## Signals",
    ]

    # Top pressures
    sorted_pressures = sorted(
        pressures.items(),
        key=lambda x: x[1].get("pressure", 0),
        reverse=True
    )[:5]
    for name, pstate in sorted_pressures:
        p = pstate.get("pressure", 0)
        e = pstate.get("emission_count", 0)
        lines.append(f"- {name.upper()}: {p:.2f} ({e} emissions)")

    lines.append("")
    lines.append("## Slots")
    for slot in slots[:5]:
        lines.append(f"- {slot}")

    lines.append("")
    lines.append("## Platform Rule")
    lines.append("- BLUESKY → bsky_publish_reply(text, parent_uri, parent_cid)")
    lines.append("- MOLTBOOK → moltbook_add_comment(post_id, content)")

    return "\n".join(lines)
