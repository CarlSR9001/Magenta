import logging
from letta_client import Letta
from config_loader import get_letta_config
from register_tools import TOOL_CONFIGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

letta_config = get_letta_config()
client = Letta(api_key=letta_config["api_key"], base_url=letta_config.get("base_url", "https://api.letta.com"))
agent_id = letta_config["agent_id"]

print(f"--- STEP 1: DETACHING ALL TOOLS FROM AGENT {agent_id} ---")
all_attached = []
response = client.agents.tools.list(agent_id=agent_id)
while True:
    items = getattr(response, "items", [])
    if not items:
        break
    all_attached.extend(items)
    # Most Letta lists are paginated with 'after'
    last_id = items[-1].id
    response = client.agents.tools.list(agent_id=agent_id, after=last_id)
    if not getattr(response, "items", []):
        break

print(f"Found {len(all_attached)} attached tools.")
for t in all_attached:
    try:
        print(f"Detaching {t.name} ({t.id})...")
        client.agents.tools.detach(agent_id=agent_id, tool_id=t.id)
    except Exception as e:
        print(f"Failed to detach {t.name}: {e}")

print(f"\n--- STEP 2: REGISTERING AND ATTACHING TOOLS FROM TOOL_CONFIGS ---")
for tool_config in TOOL_CONFIGS:
    func = tool_config["func"]
    tool_name = func.__name__
    try:
        print(f"Upserting {tool_name}...")
        created_tool = client.tools.upsert_from_function(
            func=func,
            args_schema=tool_config["args_schema"],
            tags=tool_config["tags"],
        )
        print(f"Attaching {created_tool.name} ({created_tool.id})...")
        client.agents.tools.attach(agent_id=agent_id, tool_id=created_tool.id)
        print(f"✓ {tool_name} processed.")
    except Exception as e:
        print(f"✗ Error processing {tool_name}: {e}")

print("\n--- FINAL VERIFICATION ---")
final_tools = []
response = client.agents.tools.list(agent_id=agent_id)
while True:
    items = getattr(response, "items", [])
    if not items:
        break
    final_tools.extend(items)
    last_id = items[-1].id
    response = client.agents.tools.list(agent_id=agent_id, after=last_id)
    if not getattr(response, "items", []):
        break

print(f"Agent now has {len(final_tools)} tools.")
for t in sorted(final_tools, key=lambda x: x.name):
    print(f"- {t.name}")
