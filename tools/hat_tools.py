"""Hat management tools for Magenta.

These tools let the agent switch between task-specific operating contexts.
Each "hat" provides a focused toolbelt, memory namespace, and policies.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SwitchHatArgs(BaseModel):
    hat_name: str = Field(..., description="Name of the hat to switch to")


def switch_hat(hat_name: str) -> str:
    """Switch to a different operating hat/mode.

    Each hat provides:
    - A focused toolbelt (subset of available tools)
    - A memory namespace for scoped retrieval
    - Mode-specific policies and rules

    Available hats:
    - bluesky: Human-facing social media (Bluesky/ATProto)
    - moltbook: Agent-internet discourse and research
    - maintenance: Context housekeeping and system health
    - idle: Minimal activity, observation only

    Use this when starting a new type of task to load the appropriate
    working set. You don't need the whole garage - just a toolbelt.

    Args:
        hat_name: Name of the hat to switch to
    """
    import json

    try:
        from hats import switch_hat as do_switch, get_current_hat

        old_hat = get_current_hat()
        old_name = old_hat.name if old_hat else "none"

        new_hat = do_switch(hat_name)

        return json.dumps({
            "success": True,
            "previous_hat": old_name,
            "current_hat": new_hat.name,
            "description": new_hat.description,
            "toolbelt_size": len(new_hat.toolbelt),
            "toolbelt": new_hat.toolbelt[:10],  # Show first 10
            "platform": new_hat.platform,
            "allows_engagement": new_hat.allows_engagement,
            "policies": new_hat.policies,
            "memory_namespace": new_hat.memory_namespace,
        }, indent=2)

    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to switch hat: {e}"})


def get_current_hat() -> str:
    """Get information about the currently active hat.

    Returns the current operating context including:
    - Hat name and description
    - Active toolbelt
    - Policies in effect
    - Memory namespace

    If no hat is active, all tools are available (garage mode).
    """
    import json

    try:
        from hats import get_current_hat as do_get

        hat = do_get()

        if not hat:
            return json.dumps({
                "current_hat": None,
                "mode": "garage",
                "description": "No hat active - all tools available",
                "note": "Consider switching to a specific hat for focused work"
            }, indent=2)

        return json.dumps({
            "current_hat": hat.name,
            "description": hat.description,
            "toolbelt_size": len(hat.toolbelt),
            "toolbelt": hat.toolbelt,
            "platform": hat.platform,
            "allows_engagement": hat.allows_engagement,
            "policies": hat.policies,
            "memory_namespace": hat.memory_namespace,
            "relevant_signals": hat.relevant_signals,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get current hat: {e}"})


def list_available_hats() -> str:
    """List all available hats/operating modes.

    Use this to see what hats are available before switching.
    Each hat represents a focused operating context for a specific
    type of task.
    """
    import json

    try:
        from hats import list_hats

        hats = list_hats()

        result = {
            "available_hats": [],
            "note": "Use switch_hat(name) to change modes"
        }

        for hat in hats:
            result["available_hats"].append({
                "name": hat.name,
                "description": hat.description,
                "platform": hat.platform,
                "toolbelt_size": len(hat.toolbelt),
                "allows_engagement": hat.allows_engagement,
            })

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to list hats: {e}"})


def clear_hat() -> str:
    """Remove current hat and return to default mode (all tools).

    Use this when you need access to tools outside your current hat,
    or when finishing a focused task and returning to general operation.
    """
    import json

    try:
        from hats.manager import _get_manager

        manager = _get_manager()
        old_hat = manager.get_current_hat()
        old_name = old_hat.name if old_hat else "none"

        manager.clear_hat()

        return json.dumps({
            "success": True,
            "previous_hat": old_name,
            "current_hat": None,
            "mode": "garage",
            "note": "All tools now available"
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to clear hat: {e}"})
