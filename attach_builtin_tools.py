#!/usr/bin/env python3
"""Attach existing Letta tools by name (e.g., conversation_search)."""

from letta_client import Letta

from config_loader import get_letta_config, get_config


def main():
    get_config("config.yaml")
    cfg = get_letta_config()
    params = {"api_key": cfg["api_key"], "timeout": cfg.get("timeout", 600)}
    if cfg.get("base_url"):
        params["base_url"] = cfg["base_url"]
    client = Letta(**params)

    agent_id = cfg["agent_id"]
    agent = client.agents.retrieve(agent_id=agent_id)

    existing = client.tools.list()
    name_to_id = {t.name: str(t.id) for t in existing}

    to_attach = ["conversation_search"]
    for name in to_attach:
        tool_id = name_to_id.get(name)
        if not tool_id:
            print(f"Tool not found: {name}")
            continue
        client.agents.tools.attach(agent_id=str(agent.id), tool_id=tool_id)
        print(f"Attached: {name}")


if __name__ == "__main__":
    main()
