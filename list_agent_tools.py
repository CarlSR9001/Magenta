#!/usr/bin/env python3
"""List all tools attached to the Magenta agent.

Uses the agent state endpoint which accurately returns all tools,
unlike the paginated /agents/{id}/tools endpoint which has bugs.
"""

import requests
import yaml

# Load config
with open('config.yaml') as f:
    config = yaml.safe_load(f)

api_key = config['letta']['api_key']
agent_id = config['letta']['agent_id']
base_url = config['letta'].get('base_url', 'https://api.letta.com/v1')

# Ensure base_url ends with /v1
if not base_url.endswith('/v1'):
    base_url = base_url.rstrip('/') + '/v1'

headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

# Get agent state - this has the accurate tools list
url = f'{base_url}/agents/{agent_id}'
resp = requests.get(url, headers=headers)

if resp.status_code != 200:
    print(f'Error: {resp.status_code} - {resp.text}')
    exit(1)

agent = resp.json()
tools = agent.get('tools', [])

print(f"Listing tools for agent: {agent.get('name')} ({agent_id})")
print(f"Total tools: {len(tools)}")

for t in sorted(tools, key=lambda x: x.get('name', '')):
    print(f"- {t.get('name')} ({t.get('id')})")
