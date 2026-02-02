import requests
from config_loader import get_letta_config

letta_config = get_letta_config()
api_key = letta_config["api_key"]
agent_id = letta_config["agent_id"]
base_url = letta_config.get("base_url", "https://api.letta.com").rstrip("/")

headers = {
    "Authorization": f"Bearer {api_key}"
}

print(f"Fetching tools for agent: {agent_id} via raw API")
url = f"{base_url}/v1/agents/{agent_id}/tools"
all_tools = []
params = {"limit": 100} # Try a larger limit

response = requests.get(url, headers=headers, params=params)
if response.status_code != 200:
    print(f"Error: {response.text}")
    exit(1)

data = response.json()
# Letta API usually returns a list or a dict with "items"
items = data if isinstance(data, list) else data.get("items", [])
all_tools.extend(items)

print(f"Total tools returned: {len(all_tools)}")
for t in sorted(all_tools, key=lambda x: x["name"] if isinstance(x, dict) else x.name):
    name = t["name"] if isinstance(t, dict) else t.name
    id = t["id"] if isinstance(t, dict) else t.id
    print(f"- {name} ({id})")
