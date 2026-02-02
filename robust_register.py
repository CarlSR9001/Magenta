#!/usr/bin/env python3
"""Robust tool registration - batch upsert then batch attach, skip verification during registration."""

import time
import logging
from letta_client import Letta
from config_loader import get_letta_config, get_config
from register_tools import TOOL_CONFIGS

logging.basicConfig(level=logging.WARNING)
get_config("config.yaml")

letta_config = get_letta_config()
client = Letta(
    api_key=letta_config["api_key"],
    base_url=letta_config.get("base_url", "https://api.letta.com"),
    timeout=letta_config.get("timeout", 600)
)
agent_id = letta_config["agent_id"]


def list_attached_tools():
    """Simple list of attached tools - just first page is enough for verification."""
    try:
        result = client.agents.tools.list(agent_id=agent_id, limit=100)
        if hasattr(result, 'items'):
            return list(result.items) if result.items else []
        return list(result) if result else []
    except:
        return []


print(f"=== TOOL REGISTRATION FOR {agent_id} ===\n")

# Step 1: Detach all
print("Step 1: Detaching existing tools...")
for _ in range(3):
    tools = list_attached_tools()
    if not tools:
        break
    for t in tools:
        try:
            client.agents.tools.detach(agent_id=agent_id, tool_id=t.id)
        except:
            pass
    time.sleep(1)
print(f"  Done\n")

# Step 2: Upsert all tools first (creates/updates in Letta's tool registry)
print(f"Step 2: Upserting {len(TOOL_CONFIGS)} tools...")
tool_ids = {}
for i, cfg in enumerate(TOOL_CONFIGS, 1):
    func = cfg["func"]
    name = func.__name__
    try:
        if cfg.get("args_schema"):
            t = client.tools.upsert_from_function(func=func, args_schema=cfg["args_schema"], tags=cfg.get("tags", []))
        else:
            t = client.tools.upsert_from_function(func=func, tags=cfg.get("tags", []))
        tool_ids[name] = t.id
        print(f"  [{i:2d}] ✓ {name}")
    except Exception as e:
        print(f"  [{i:2d}] ✗ {name}: {e}")
print()

# Step 3: Batch attach all tools
print(f"Step 3: Attaching {len(tool_ids)} tools to agent...")
for name, tid in tool_ids.items():
    try:
        client.agents.tools.attach(agent_id=agent_id, tool_id=tid)
    except Exception as e:
        print(f"  ⚠ {name}: {e}")

# Wait for API consistency
print("  Waiting for API sync...")
time.sleep(5)

# Step 4: Verify and retry missing
print("\nStep 4: Verifying and retrying missing...")
attached = {t.name for t in list_attached_tools()}
missing = set(tool_ids.keys()) - attached

if missing:
    print(f"  {len(missing)} missing, retrying...")
    for name in missing:
        tid = tool_ids.get(name)
        if tid:
            for _ in range(3):
                try:
                    client.agents.tools.attach(agent_id=agent_id, tool_id=tid)
                    time.sleep(1)
                except:
                    pass
    time.sleep(3)

# Final check
final = list_attached_tools()
final_names = sorted(t.name for t in final)
print(f"\n=== RESULT: {len(final_names)} tools attached ===")
for n in final_names:
    print(f"  - {n}")

expected = set(tool_ids.keys())
found = set(final_names)
still_missing = expected - found
if still_missing:
    print(f"\n⚠️  MISSING: {still_missing}")
else:
    print("\n✓ All tools attached!")
