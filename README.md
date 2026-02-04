# Magenta

Magenta is a stateful, multi‑platform social agent built around Letta. It includes:
- A guarded decision loop (observe → decide → draft → preflight → commit)
- A local heartbeat/interoception system
- Tooling for Bluesky and Moltbook
- Optional voice bridges (Discord + Twilio)

This repo is the working implementation (not just a scaffold).

---

## What Magenta does

- Monitors social signals (Bluesky + Moltbook) and decides on responses.
- Writes drafts to an outbox, then commits via tool rules.
- Maintains local memory state, summaries, and interoception pressure.
- Can speak and listen via Discord voice (optional) and phone calls (optional).

---

## Repo structure

- `agent.py`: core Magenta agent implementation.
- `heartbeat_v2.py`: main interoception/heartbeat loop.
- `flow/`: decision system + preflight/commit guards.
- `tools/`: Letta tools (Bluesky, Moltbook, Discord, Twilio, memory).
- `interoception/`: limbic system, signal scoring, pressure.
- `voice/`: realtime speech bridge (Discord voice + Twilio streams).
- `outbox/`, `state/`, `logs/`: local state + artifacts.
- `SYSTEM_PROMPT.md`: system prompt used for Letta.

---

## Quick start (local)

1) Create config:
```
cp config.example.yaml config.local.yaml
```
2) Fill in credentials in `config.local.yaml`.
3) Create venv + install deps:
```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```
4) Register tools with Letta:
```
python register_tools.py
python configure_tool_rules.py
```
5) Run a single cycle:
```
python run_agent.py
```

---

## Heartbeat (recommended)

Systemd service for ongoing interoception + social checks:

```
# Service file is /etc/systemd/system/magenta-heartbeat.service
systemctl status magenta-heartbeat.service
systemctl restart magenta-heartbeat.service
```

Logs:
```
/home/shankatsu/magenta/logs/heartbeat_v2.log
```

---

## Voice (optional)

### Discord voice
- `voice/discord_realtime_bridge.py` connects to a voice channel.
- Live TTS is generated through OpenAI Realtime.

Config in `voice_config.yaml`:
- `discord_voice.guild_id`
- `discord_voice.channel_id`
- `openai.api_base`
- `realtime.model` / `realtime.voice`

Service:
```
systemctl status magenta-discord-voice.service
systemctl restart magenta-discord-voice.service
```

### Twilio phone calls
- `voice/twilio_realtime_server.py` accepts Twilio Media Streams.

Service:
```
systemctl status magenta-voice-bridge.service
systemctl restart magenta-voice-bridge.service
```

---

## Tools + rules

Tool registration:
```
python register_tools.py
```

Tool rules enforcement:
```
python configure_tool_rules.py
```

Clear tools:
```
python clear_tools.py --agent-id <id>
```

---

## Pilot runner (admin harness)

Allows Letta admin ops and direct messages via a JSONL file queue:

```
python pilot_runner.py --follow
```

Commands go to `state/pilot_commands.jsonl` and results in `state/pilot_outputs.jsonl`.

---

## Troubleshooting

### “BSKY_USERNAME and BSKY_PASSWORD must be set”
Set credentials in `config.local.yaml`, or provide env vars for the runtime process.

### “MOLTBOOK_API_KEY not set”
Set `moltbook.api_key` in `config.local.yaml` or set `MOLTBOOK_API_KEY` in the process env.

### Outbox drafts stuck
Use the outbox tools or run the cleanup cycle in `heartbeat_v2.py`.

---

## Security notes

- Do **not** commit secrets.
- Keep keys in `config.local.yaml` or process env.
- Systemd services can load env files if you choose to use them, but avoid committing those files.

---

## Key entrypoints

- `run_agent.py` — single decision cycle
- `run_queue.py` — process queued drafts
- `run_autonomy.py` — continuous loop (with jitter)
- `heartbeat_v2.py` — interoception + social signal loop
- `discord_bot.py` — Discord text bot (optional)

---

If you want a minimal or production‑hardened variant, open an issue or PR with the target constraints.
