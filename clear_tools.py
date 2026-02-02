#!/usr/bin/env python3
"""Detach all tools from a Letta agent (optionally delete tool definitions)."""

import logging

from letta_client import Letta
from rich.console import Console

from config_loader import get_letta_config, get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


def clear_tools(agent_id: str, delete_tools: bool = False) -> None:
    letta_config = get_letta_config()

    client_params = {
        "api_key": letta_config["api_key"],
        "timeout": letta_config["timeout"],
    }
    if letta_config.get("base_url"):
        client_params["base_url"] = letta_config["base_url"]

    client = Letta(**client_params)

    agent = client.agents.retrieve(agent_id=agent_id)
    tools = client.agents.tools.list(agent_id=str(agent.id))

    if not tools:
        console.print("No tools attached.")
        return

    console.print(f"Detaching {len(tools)} tool(s) from {agent.name} ({agent_id})")

    for tool in tools:
        try:
            client.agents.tools.detach(agent_id=str(agent.id), tool_id=str(tool.id))
            console.print(f"- Detached: {tool.name} ({tool.id})")

            if delete_tools:
                client.tools.delete(tool_id=str(tool.id))
                console.print(f"  Deleted tool definition: {tool.name}")
        except Exception as exc:
            console.print(f"- Failed: {tool.name} ({tool.id}) -> {exc}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detach tools from a Letta agent")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    parser.add_argument("--agent-id", required=True, help="Agent ID to clear")
    parser.add_argument("--delete", action="store_true", help="Also delete tool definitions")

    args = parser.parse_args()
    get_config(args.config)

    clear_tools(args.agent_id, delete_tools=args.delete)
