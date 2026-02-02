#!/usr/bin/env python3
"""Attach named tools to Magenta agent."""

from letta_client import Letta

from config_loader import get_letta_config, get_config


def main():
    get_config('config.yaml')
    cfg = get_letta_config()
    params = {'token': cfg['api_key'], 'timeout': cfg.get('timeout',600)}
    if cfg.get('base_url'):
        params['base_url'] = cfg['base_url']
    client = Letta(**params)

    agent_id = cfg['agent_id']
    agent = client.agents.retrieve(agent_id=agent_id)

    needed = [
        'rate_limit_check','load_agent_state','bsky_list_notifications','bsky_get_thread','bsky_get_profile',
        'outbox_create_draft','outbox_update_draft','outbox_mark_aborted','outbox_finalize','preflight_check',
        'bsky_publish_post','bsky_publish_reply','bsky_like','bsky_follow','bsky_mute','bsky_block','postmortem_write','ping'
    ]

    all_tools = client.tools.list()
    name_to_id = {t.name: str(t.id) for t in all_tools}

    current = client.agents.tools.list(agent_id=str(agent.id))
    attached = {t.name for t in current}

    for name in needed:
        if name in attached:
            continue
        tool_id = name_to_id.get(name)
        if not tool_id:
            print(f"Missing tool in catalog: {name}")
            continue
        client.agents.tools.attach(agent_id=str(agent.id), tool_id=tool_id)
        print(f"Attached: {name}")


if __name__ == '__main__':
    main()
