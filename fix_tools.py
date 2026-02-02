#!/usr/bin/env python3
"""
Complete tool reset script that:
1. Gets all tools currently attached
2. Detaches them completely
3. Waits for API to sync
4. Creates all tools fresh
5. Attaches them one by one
6. Verifies each attachment
"""

import sys
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

def get_all_attached_tools():
    """Get all tools attached to this agent"""
    tools = []
    for tool in client.agents.tools.list(agent_id=agent_id):
        tools.append(tool)
    return tools

print(f"=== STEP 1: Get all attached tools for agent {agent_id} ===")
attached = get_all_attached_tools()
print(f"Found {len(attached)} attached tools")

print("\n=== STEP 2: Detach ALL tools ===")
detached_count = 0
for tool in attached:
    try:
        client.agents.tools.detach(agent_id=agent_id, tool_id=tool.id)
        print(f"  Detached: {tool.name}")
        detached_count += 1
    except Exception as e:
        print(f"  Failed to detach {tool.name}: {e}")

print(f"\nDetached {detached_count} tools")

# Give API time to sync
print("\n=== STEP 3: Waiting 3s for API sync... ===")
time.sleep(3)

# Verify clean slate
attached_after = get_all_attached_tools()
print(f"Tools remaining after detach: {len(attached_after)}")

# Double-detach any remaining
if attached_after:
    print("  Attempting to detach remaining tools...")
    for tool in attached_after:
        try:
            client.agents.tools.detach(agent_id=agent_id, tool_id=tool.id)
            print(f"    Detached: {tool.name}")
        except Exception as e:
            pass  # May already be detached
    time.sleep(2)

# Verify clean
attached_clean = get_all_attached_tools()
if attached_clean:
    print(f"WARNING: {len(attached_clean)} tools still attached")
else:
    print("Agent has 0 tools attached - clean slate!")

print(f"\n=== STEP 4: Register and attach {len(TOOL_CONFIGS)} tools ===")
success_count = 0
failed = []

for tool_config in TOOL_CONFIGS:
    func = tool_config["func"]
    tool_name = func.__name__
    try:
        # Upsert the tool (create or update)
        created_tool = client.tools.upsert_from_function(
            func=func,
            args_schema=tool_config["args_schema"],
            tags=tool_config.get("tags", []),
        )
        
        # Attach to agent
        client.agents.tools.attach(agent_id=agent_id, tool_id=created_tool.id)
        print(f"  ✓ {tool_name} ({created_tool.id})")
        success_count += 1
    except Exception as e:
        print(f"  ✗ {tool_name}: {e}")
        failed.append(tool_name)

print(f"\nSuccessfully attached {success_count}/{len(TOOL_CONFIGS)} tools")
if failed:
    print(f"Failed tools: {failed}")

# Give API time to sync
print("\n=== STEP 5: Waiting 3s for final sync... ===")
time.sleep(3)

print("\n=== STEP 6: Final verification ===")
final_tools = get_all_attached_tools()
print(f"Agent now has {len(final_tools)} tools attached:")

tool_names = sorted(set(t.name for t in final_tools))
for name in tool_names:
    count = len([t for t in final_tools if t.name == name])
    if count > 1:
        print(f"  - {name} (x{count} duplicates!)")
    else:
        print(f"  - {name}")

# Check for expected tools
expected = set(t["func"].__name__ for t in TOOL_CONFIGS)
found = set(t.name for t in final_tools)
missing = expected - found
if missing:
    print(f"\n⚠️  MISSING TOOLS: {missing}")
else:
    print(f"\n✓ All {len(expected)} expected tools are attached!")
