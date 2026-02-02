# Session Notes: 2026-01-31 Interoception & Platform Fixes

## Summary
Fixed multiple issues with Magenta's interoception system and platform confusion.

## Issues Fixed

### 1. UNCANNY Signal Spam
**Problem**: UNCANNY was firing every ~100 seconds due to fast accumulation.
**Fix** (in `interoception/signals.py` and `interoception/pressure.py`):
- Changed `base_interval_seconds` from 0 to 1800 (30 min)
- Changed `accumulation_rate` from 0.005 to 0.001
- Added 10-minute hard cooldown (no bypass)

### 2. Interoception Tools Not Working
**Problem**: Tools returned "state not found" because they used local file paths but run in Letta's cloud sandbox.
**Fix** (in `tools/interoception_tools.py`):
- Changed from local file (`state/interoception.json`) to Letta archival memory
- Tools now read/write state via `client.agents.passages` API
- Marker: `[INTEROCEPTION_STATE]` prefix in archival passages

### 3. Heartbeat State Sync
**Fix** (in `heartbeat_v2.py`):
- Added `sync_state_to_archival()` function
- Syncs state to Letta archival memory every 5 ticks and after signal emissions
- Tools and heartbeat now share same state source

### 4. Platform Confusion (Bluesky vs Moltbook)
**Problem**: Magenta kept trying to reply to Bluesky users on Moltbook and vice versa.
**Fix** (in `SYSTEM_PROMPT.md` and `interoception/limbic.py`):
- Added explicit PLATFORM → TOOL mapping table
- Bluesky → `bsky_publish_reply(text, parent_uri, parent_cid)`
- Moltbook → `moltbook_add_comment(post_id, content)`
- Added ✓/✗ examples of correct/wrong usage
- Rule: NEVER switch platforms if blocked - shorten or escalate instead

### 5. Tool Schema Errors
**Problem**: Magenta using wrong parameter names (`uri` instead of `parent_uri`, `text` instead of `content`).
**Fix**: Added Tool Schemas section to SYSTEM_PROMPT.md with exact parameter names.

## Key Files Modified
- `/home/shankatsu/magenta/interoception/signals.py` - UNCANNY config
- `/home/shankatsu/magenta/interoception/pressure.py` - Cooldown logic
- `/home/shankatsu/magenta/interoception/limbic.py` - SOCIAL signal prompt
- `/home/shankatsu/magenta/tools/interoception_tools.py` - Archival memory backend
- `/home/shankatsu/magenta/heartbeat_v2.py` - State sync to archival
- `/home/shankatsu/magenta/SYSTEM_PROMPT.md` - Platform rules and tool schemas

## Tool Schemas (Quick Reference)

```python
# Bluesky reply
bsky_publish_reply(
    text: str,           # max 300 chars
    parent_uri: str,     # AT Protocol URI
    parent_cid: str,     # CID of parent post
    root_uri: str = "",
    root_cid: str = "",
    lang: str = "en-US"
)

# Moltbook comment
moltbook_add_comment(
    post_id: str,        # Post ID
    content: str,        # NOT "text"!
    parent_id: str = None
)
```

## Platform Rule
```
BLUESKY notification → bsky_publish_reply
MOLTBOOK notification → moltbook_add_comment
NEVER cross-platform reply - they won't see it!
```

## Commands to Restart Services
```bash
# Restart heartbeat
pkill -9 -f heartbeat_v2.py
nohup .venv/bin/python heartbeat_v2.py >> logs/heartbeat_v2.log 2>&1 &

# Re-register tools after code changes
.venv/bin/python register_tools.py --tools <tool_names> --no-env

# Update system prompt
.venv/bin/python set_system_prompt.py
```

## Hypercontext Skill
Installed `/hypercontext` skill for Claude Code session visualization.
Location: `~/.claude/skills/hypercontext.md`
Source: https://hypercontext.sh

## Hypercontext for Magenta
Adapted hypercontext for Letta agents.
Location: `/home/shankatsu/magenta/tools/hypercontext.py`

**Tools:**
- `hypercontext_map()` - Full ASCII visualization showing:
  - Context usage bar and runway
  - Signal pressures with heat ranking (recency)
  - Context slots (working memory)
  - Recent tool activity
  - System connectivity
  - Recent outcomes

- `hypercontext_compact()` - Dense markdown format for context recovery

**Example output:**
```
╔══════════════════════════════════════════════════════════════════════╗
║  HYPERCONTEXT — 2026-01-31 16:30 UTC                                ║
║  ctx ▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~20% (25k/128k)            ║
║  ▁▂▃▅▆▇█ velocity ─────────────────── runway: ~103k tokens          ║
╠══════════════════════════════════════════════════════════════════════╣
║  SIGNALS (pressure)            HEAT (recency)                       ║
║  SOCIAL     ▓▓▓▓░░░░░░ 0.45    ████ SOCIAL   (50)                  ║
║  MAINTENANCE ▓▓▓░░░░░░░ 0.30   ███░ MAINT    (25)                  ║
...
╚══════════════════════════════════════════════════════════════════════╝
```
