#!/usr/bin/env python3
"""Configure Letta tool rules for Magenta agent."""

from letta_client import Letta

from config_loader import get_letta_config, get_config


def build_rules():
    """
    Build simplified tool rules for Magenta.
    
    IMPORTANT: Previous rules with parent_last_tool were too restrictive and caused
    ToolConstraintError when trying to call bsky_get_thread. 
    
    Now using a simpler approach similar to Umbra:
    - No run_first restrictions (tools can be called in any order)
    - No parent_last_tool restrictions (tools are freely callable)
    - Keep max_count_per_step to prevent spam
    - Keep exit_loop for commit tools (commits are terminal)
    """
    commit_tools = [
        "bsky_publish_post",
        "bsky_publish_reply",
        "bsky_like",
        "bsky_follow",
        "bsky_mute",
        "bsky_block",
    ]

    rules = [
        # Max count limits to prevent spam/loops
        {
            "type": "max_count_per_step",
            "tool_name": "bsky_get_thread",
            "max_count_limit": 10,  # Allow reasonable thread fetching
        },
        {
            "type": "max_count_per_step",
            "tool_name": "bsky_list_notifications",
            "max_count_limit": 3,
        },
        {
            "type": "max_count_per_step",
            "tool_name": "conversation_search",
            "max_count_limit": 2,
        },
        {
            "type": "max_count_per_step",
            "tool_name": "get_local_time",
            "max_count_limit": 2,
        },
    ]

    # One commit max per step + terminal commit tools
    for tool in commit_tools:
        rules.append(
            {
                "type": "max_count_per_step",
                "tool_name": tool,
                "max_count_limit": 1,
            }
        )
        rules.append(
            {
                "type": "exit_loop",
                "tool_name": tool,
            }
        )

    return rules


def main():
    get_config("config.yaml")
    letta_cfg = get_letta_config()

    client_params = {"api_key": letta_cfg["api_key"], "timeout": letta_cfg.get("timeout", 600)}
    if letta_cfg.get("base_url"):
        client_params["base_url"] = letta_cfg["base_url"]

    client = Letta(**client_params)
    rules = build_rules()

    client.agents.update(agent_id=letta_cfg["agent_id"], tool_rules=rules)
    print("Tool rules updated.")


if __name__ == "__main__":
    main()
