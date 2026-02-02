#!/usr/bin/env python3
"""Set the Letta agent system prompt from SYSTEM_PROMPT.md."""

from pathlib import Path

from letta_client import Letta

from config_loader import get_letta_config, get_config


def main() -> None:
    get_config("config.yaml")
    cfg = get_letta_config()
    prompt_path = Path("SYSTEM_PROMPT.md")
    prompt = prompt_path.read_text(encoding="utf-8")

    params = {"api_key": cfg["api_key"], "timeout": cfg.get("timeout", 600)}
    if cfg.get("base_url"):
        params["base_url"] = cfg["base_url"]

    client = Letta(**params)
    client.agents.update(agent_id=cfg["agent_id"], system=prompt)
    print("System prompt updated.")


if __name__ == "__main__":
    main()
