# Magenta (agent skeleton)

Minimal, reusable scaffolding for a stateful agent that talks to:
- Letta (primary)
- Bluesky (AT Protocol)
- ElevenLabs
- Audio relay service

This is intentionally thin: only the connective tissue and examples so new agents can build quickly without inheriting Umbra-specific logic.

## Quick start
1. Copy the sample config:
   - `cp config.example.yaml config.yaml`
2. Fill in credentials.
3. (Optional) Create/attach tools in Letta:
   - `python register_tools.py --config config.yaml`
4. (Optional) Clear all tools from a Letta agent:
   - `python clear_tools.py --config config.yaml --agent-id <id>`

## What’s included
- `config_loader.py`: single source of truth for config + env overrides.
- `clients/`: API client helpers (Letta, Bluesky, ElevenLabs, relay audio).
- `tools/`: example Letta tool(s) and schemas.
- `register_tools.py`: registers tools and pushes env vars to Letta for tool execution.
- `clear_tools.py`: detaches all tools from a Letta agent (optional delete).
- `flow/`: observe→decide→draft→preflight→commit→postmortem orchestration primitives.
- `run_agent.py`: minimal runner that executes a single guarded cycle.
- `run_queue.py`: processes queued drafts (one commit max).
- `run_autonomy.py`: autonomous loop with jitter + RNG.
- `configure_tool_rules.py`: applies Letta tool rules for guarded flow.
- `flow/commit_handlers.py`: Bluesky side-effect handlers used by the runner.
- `SYSTEM_PROMPT.md`: system prompt for the Magenta agent.

## Usage snippets

### Letta
```python
from clients import get_letta_client, get_agent_id

client = get_letta_client()
agent_id = get_agent_id()
agent = client.agents.retrieve(agent_id=agent_id)
```

### Bluesky
```python
from clients import bluesky_login

client = bluesky_login()
feed = client.app.bsky.feed.get_timeline({"limit": 5})
```

### ElevenLabs
```python
from clients import text_to_speech

audio_bytes = text_to_speech("Hello from Magenta")
with open("sample.mp3", "wb") as f:
    f.write(audio_bytes)
```

### Relay audio
```python
from clients import relay_audio

result = relay_audio(text="Hello", caption="hello world")
```

## Notes
- Secrets can be set via `config.yaml` or env vars like `LETTA_API_KEY`, `BSKY_USERNAME`, etc.
- This repo deliberately avoids Umbra’s bot logic so you can compose your own flow cleanly.
- Memory writes are stored locally in `state/archival_memory.log` and `state/core_memory.log` by default.

## Flow usage (skeleton)
The flow enforces a strict two-phase commit: draft + preflight, then commit (terminal).

```python
from pathlib import Path
from flow import (
    DecisionPolicy,
    MemoryPolicy,
    OutboxStore,
    SalienceConfig,
    Toolset,
    AgentStateStore,
    TelemetryStore,
    run_once,
)

policy = DecisionPolicy(
    salience_config=SalienceConfig(weights={"delta_u": 0.4, "risk": -0.4}),
    j_weights={"voi": 1.0, "optionality": 0.5, "risk": 1.0, "fatigue": 1.0},
)

toolset = Toolset(outbox=OutboxStore(Path("outbox")), policy=policy, memory_policy=MemoryPolicy())
state_store = AgentStateStore(Path("state/agent_state.json"))
telemetry = TelemetryStore(Path("state/telemetry.jsonl"))

run_once(toolset, state_store, telemetry, toolset.outbox)
```

You will want to override `Toolset.observe()` and `Toolset.propose_actions()` with your own logic.

See `flow/TOOL_RULES.md` for the tool-rule policy contract.

## Run the agent
```bash
python /home/shankatsu/magenta/run_agent.py
```

This uses `MagentaAgent` (see `agent.py`) which:
- Pulls recent notifications
- Uses Letta to propose 1-3 candidate actions
- Drafts + preflights the chosen action
- Commits via Bluesky API if allowed

## Process queued drafts
```bash
python /home/shankatsu/magenta/run_queue.py
```

## Autonomous loop (no cron)
```bash
python /home/shankatsu/magenta/run_autonomy.py --min-seconds 45 --max-seconds 120
```

## Pilot bridge (drive harness + Letta admin)
Run the pilot runner (file queue):
```bash
python /home/shankatsu/magenta/pilot_runner.py --follow
```

Append commands to `state/pilot_commands.jsonl`, results land in `state/pilot_outputs.jsonl`.

Example: fetch recent agent messages (read-only mirror)
```json
{"id":"msg-1","type":"letta_admin","op":"get_recent_messages","args":{"limit":20}}
```

Example: clean mirror (assistant/user only)
```json
{"id":"msg-2","type":"letta_admin","op":"get_recent_messages_clean","args":{"limit":20}}
```

Example: talk to Magenta (via Letta messages)
```json
{"id":"talk-1","type":"letta_admin","op":"send_message","args":{"content":"Quick check-in: summarize your top 3 open commitments."}}
```

Example: list core memory blocks
```json
{"id":"mem-1","type":"letta_admin","op":"list_blocks","args":{"include_content":false}}
```

Example: read a block
```json
{"id":"mem-2","type":"letta_admin","op":"get_block","args":{"label":"zeitgeist","line_numbers":true}}
```

Example: replace lines in a block
```json
{"id":"mem-3","type":"letta_admin","op":"replace_block_lines","args":{"label":"zeitgeist","start_line":1,"end_line":1,"new_content":"**Active Discourse Themes (2026-02-02):**"}}
```

Example: queue a draft
```json
{"id":"draft-1","type":"harness_action","mode":"queue","draft":{"type":"reply","target_uri":"at://...","text":"Hello","intent":"follow up","confidence":0.8,"salience":0.5,"metadata":{"reply_to":{"root":{"uri":"...","cid":"..."},"parent":{"uri":"...","cid":"..."}}}}}
```

Example: direct commit (bypass preflight)
```json
{"id":"commit-1","type":"harness_action","mode":"commit","bypass_preflight":true,"draft":{"type":"post","text":"Quick note","intent":"pilot test","confidence":1.0,"salience":0.2}}
```

## Upload tools + configure Letta rules
1. Register tools with Letta:
```bash
python /home/shankatsu/magenta/register_tools.py --config /home/shankatsu/magenta/config.yaml
```
2. Apply tool rules:
```bash
python /home/shankatsu/magenta/configure_tool_rules.py
```
3. (Optional) Clear existing tools from the Magenta agent first:
```bash
python /home/shankatsu/magenta/clear_tools.py --config /home/shankatsu/magenta/config.yaml --agent-id agent-f7fee7dc-d199-4092-ac8c-ee863467f284
```

## System prompt
Use `SYSTEM_PROMPT.md` as the system prompt for the Letta agent.
