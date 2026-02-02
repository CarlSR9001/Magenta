# Magenta agent workspace

This folder is a reusable skeleton for creating new stateful agents. It is intentionally minimal and focused on API connectivity.

## Design goals
- Keep core API wiring in one place (Letta, Bluesky, ElevenLabs, relay audio).
- Avoid 1:1 Umbra features; only include generic building blocks.
- Favor small, composable modules over one large script.

## Where things live
- `config_loader.py`: config parsing + env overrides.
- `clients/`: API helpers (add new APIs here).
- `tools/`: Letta tools and schemas (add new tools here).
- `register_tools.py`: one-stop tool registration + env var injection.
- `flow/`: decision/commit pipeline with draft + preflight gating.
- `run_agent.py`: single-cycle runner for the flow.
- `run_queue.py`: queue processor for drafts.
- `run_autonomy.py`: autonomous loop with jitter + RNG.
- `pilot_runner.py`: pilot bridge (file-queue control + Letta admin ops).
- `configure_tool_rules.py`: applies Letta tool rules.
- `SYSTEM_PROMPT.md`: system prompt for Magenta.
- `agent.py`: concrete Magenta agent using Letta + Bluesky APIs.

## Conventions
- New APIs go in `clients/` with a tiny surface area (connect/login + 1–2 helpful helpers).
- Tool functions should be standalone and not import large app modules.
- Keep config keys stable; document them in `config.example.yaml`.
- Prefer `pilot_runner.py` for “manual override” or maintenance actions; it can read/write Letta memory blocks and send messages without altering core flow.
- Use `config.local.yaml` for secrets; `config.yaml` is now placeholder-only.

## Adding a new API
1. Create `clients/<name>.py`.
2. Add config keys in `config.example.yaml` and accessors in `config_loader.py`.
3. Export helpers from `clients/__init__.py`.
4. Document usage in `README.md`.

---

## Pilot bridge (manual override / maintenance)

`pilot_runner.py` reads commands from `state/pilot_commands.jsonl` and writes results to `state/pilot_outputs.jsonl`.
It supports:
- `letta_admin` ops (read/write memory blocks, passages, tool env, send messages).
- `harness_action` ops (queue/commit drafts).

This bridge is designed to make Magenta a “suit” you can step into for maintenance or precise interventions.

### Example commands
```json
{"id":"talk-1","type":"letta_admin","op":"send_message","args":{"content":"Summarize your top 3 open commitments."}}
{"id":"mem-1","type":"letta_admin","op":"list_blocks","args":{"include_content":false}}
{"id":"mem-2","type":"letta_admin","op":"get_block","args":{"label":"zeitgeist","line_numbers":true}}
{"id":"mem-3","type":"letta_admin","op":"replace_block_lines","args":{"label":"zeitgeist","start_line":1,"end_line":1,"new_content":"**Active Discourse Themes (2026-02-02):**"}}
```

---

## State sync snapshot (consistency after context clears)

`heartbeat_v2.py` writes a unified snapshot to `state/sync_state.json` each tick and after signal handling.
This is used to keep context/notifications/limbic state consistent across tools:
- `interoception.providers.MagentaStateProvider` prefers this snapshot for pending + context usage.
- `tools/hypercontext.py` uses it for context/limbic display.
- `flow/preflight.py` blocks commits if the snapshot is stale (default 5 minutes).

If you see inconsistent context or stale pending counts after a reset, check `state/sync_state.json` first.

---

## Letta Platform Quirks (READ THIS FIRST)

This section documents all the weird behavior in Letta's platform that will bite you if you don't know about it. Consult this before debugging any tool issues.

### Quick Fixes for Common Problems

| Problem | Quick Fix |
|---------|-----------|
| Tool errors (`NameError`, `ModuleNotFoundError`) | `python register_tools.py` |
| Tool not updating after code change | `python register_tools.py` |
| Only seeing ~10 tools when there should be 50+ | Use `agent.tools` not `client.agents.tools.list()` |
| Tool registered with wrong name (e.g., `_helper`) | Remove nested function definitions, use lambdas |
| Tool works locally but fails in Letta | Move all imports inside function body |

### Quirk 1: Stale Tool IDs (The Big One)

**What happens:** You update tool code, run registration, see "✓ Attached", but the agent still runs old code.

**Why:** Letta creates tools by ID. When code changes, a new ID may be created, but agent keeps old ID attached.

**Fix:** Always detach-then-attach. The `register_tools.py` script handles this, but if you're doing manual registration:
```python
# 1. Detach old tool by name
for t in agent.tools:
    if t.name == "my_tool":
        client.agents.tools.detach(agent_id, t.id)

# 2. Upsert new definition
new_tool = client.tools.upsert_from_function(func=my_tool, ...)

# 3. Attach fresh tool
client.agents.tools.attach(agent_id, new_tool.id)
```

### Quirk 2: Nested Function Registration Bug

**What happens:** You define a helper function inside your tool, Letta registers the helper instead of your tool.

**Why:** `upsert_from_function` parses the source code and gets confused by nested `def` statements.

**Example of the bug:**
```python
def my_tool(data: str) -> str:
    def format_output(x):  # <-- Letta registers THIS as "format_output"
        return x.upper()
    return format_output(data)
```

**Symptoms:**
- Tool shows "✓ Attached" but doesn't appear in `agent.tools`
- Agent has tools with names like `_helper`, `make_label`, `format_output`
- Catalog has your tool with wrong name

**Fix:** Use lambdas or inline the logic:
```python
def my_tool(data: str) -> str:
    # Lambda is fine
    format_it = lambda x: x.upper()
    return format_it(data)

    # Or just inline it
    return data.upper()
```

### Quirk 3: Pagination Bug in tools.list()

**What happens:** `client.agents.tools.list(agent_id)` returns only ~10 tools when you have 50+.

**Why:** The endpoint returns a paginated `SyncArrayPage` but iteration doesn't auto-paginate reliably.

**Fix:** Use `agent.tools` from retrieve instead:
```python
# WRONG - may return incomplete list
tools = client.agents.tools.list(agent_id)

# CORRECT - always complete
agent = client.agents.retrieve(agent_id=agent_id)
tools = agent.tools  # Full list
```

If you must use the list endpoint:
```python
all_tools = []
page = client.agents.tools.list(agent_id)
while True:
    all_tools.extend(page.items)
    if page.has_next_page():
        page = page.get_next_page()
    else:
        break
```

### Quirk 4: Sandbox Import Isolation

**What happens:** Tool fails with `ModuleNotFoundError` for modules that exist in your project.

**Why:** Tools run in Letta's isolated sandbox. They can't import your local modules.

**Fix:** All imports must be inside the function, and you can only use:
- Standard library modules
- Packages installed in Letta's environment (requests, yaml, etc.)
- `os.getenv()` for configuration (NOT config_loader!)

```python
# WRONG
from config_loader import get_config  # Fails in sandbox
from datetime import datetime  # Works locally, fails in sandbox if at module level

# CORRECT
def my_tool() -> str:
    from datetime import datetime  # Import INSIDE function
    import os
    api_key = os.getenv("MY_API_KEY")  # Use env vars, not config files
```

### Quirk 5: Letta Client Initialization Variations

**What happens:** `Letta(api_key=...)` fails with `TypeError`.

**Why:** Different versions of letta-client use different parameter names.

**Fix:** Use fallback pattern:
```python
from letta_client import Letta

def get_client(api_key, base_url=None):
    try:
        return Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            return Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        except TypeError:
            return Letta()  # Last resort, uses env vars
```

### Quirk 6: Tool Environment Variables Scope

**What happens:** Tool can't access env vars you set in your shell.

**Why:** Tools run in Letta's cloud. Your local env vars don't exist there.

**Fix:** Set tool env vars via the agent update API:
```python
client.agents.update(
    agent_id=agent_id,
    tool_exec_environment_variables={
        "MY_API_KEY": "...",
        "LETTA_AGENT_ID": agent_id,  # Tools often need to know their own agent ID
    }
)
```

### Quirk 7: Attach Returns None But Succeeds

**What happens:** `client.agents.tools.attach(...)` returns `None`, you think it failed.

**Why:** The attach endpoint returns 200 OK with no body. The SDK returns `None`.

**Verification:** Check `agent.tools` after attaching to confirm:
```python
result = client.agents.tools.attach(agent_id, tool_id)  # Returns None
agent = client.agents.retrieve(agent_id)
assert any(t.id == tool_id for t in agent.tools)  # Actually attached
```

### Quirk 8: Tool Must Return String

**What happens:** Tool returns dict/list/int, agent gets confused or errors.

**Why:** Letta expects all tool outputs to be strings.

**Fix:** Always serialize to string:
```python
def my_tool() -> str:
    import json
    result = {"status": "ok", "count": 42}
    return json.dumps(result)  # NOT return result
```

### Quirk 9: Module-Level Constants Not Available

**What happens:** `NameError: name 'MY_CONSTANT' is not defined` even though it's defined at module level.

**Why:** Letta extracts only the function body. Module-level variables aren't included.

**Fix:** Define constants inside the function:
```python
# WRONG
MAX_RETRIES = 3
def my_tool() -> str:
    for i in range(MAX_RETRIES):  # NameError!
        ...

# CORRECT
def my_tool() -> str:
    MAX_RETRIES = 3  # Define inside function
    for i in range(MAX_RETRIES):
        ...
```

### Debugging Checklist

When a tool isn't working, check in this order:

1. **Is the tool in `register_tools.py` TOOL_CONFIGS?** If not, it won't be registered.

2. **Run `python register_tools.py`** - this fixes 90% of issues.

3. **Check for nested functions** - search for `def ` inside your tool function.

4. **Check imports are inside function** - not at module level.

5. **Verify attachment:**
   ```python
   agent = client.agents.retrieve(agent_id)
   print([t.name for t in agent.tools])
   ```

6. **Check for wrong-name registration:**
   ```python
   # Look for suspicious names
   for t in agent.tools:
       if t.name.startswith('_') or t.name != t.name.lower():
           print(f"Suspicious: {t.name}")
   ```

7. **Check the Letta catalog:**
   ```python
   all_tools = list(client.tools.list())
   my_tool = [t for t in all_tools if t.name == "my_tool"]
   print(my_tool)  # Should exist and have expected ID
   ```

---

## Letta Tool Registration (IMPORTANT - READ THIS)

### The Problem with Letta Tool Registration

Letta's tool system has quirks that cause tools to become stale if you don't register them correctly:

1. **`upsert_from_function()`** creates a tool in Letta's tool registry
2. If the function source code changed, Letta may create a **new tool with a new ID**
3. The agent still has the **old tool ID attached**
4. Result: agent uses outdated tool code even though you "updated" it

### The Correct Registration Flow

```
For each tool:
  1. DETACH the old tool from agent (by name lookup)
  2. UPSERT the tool definition (creates/updates in registry)
  3. ATTACH the new tool to agent (using new tool ID)
```

### Two Patterns for Tool Functions

**Pattern 1: With Pydantic args_schema (RECOMMENDED for complex args)**

```python
# tools/my_tool.py
from pydantic import BaseModel, Field

class MyToolArgs(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, ge=1, le=100, description="Max results")

def my_tool(query: str, limit: int = 10) -> str:
    """Tool description goes in docstring.

    The docstring becomes the tool's description in Letta.
    Keep it concise but informative.
    """
    # Implementation here
    # Access env vars with os.getenv("VAR_NAME")
    return "result"
```

```python
# In register_tools.py TOOL_CONFIGS:
{
    "func": my_tool,
    "args_schema": MyToolArgs,  # Pydantic model
    "description": "Short description for registration table",
    "tags": ["category", "subcategory"],
}
```

**Pattern 2: Without args_schema (SDK infers from function signature)**

```python
# tools/simple_tool.py
def simple_tool(text: str, flag: bool = False) -> str:
    """Do something simple.

    Args:
        text: The input text
        flag: Optional flag

    Returns:
        Result string
    """
    return f"processed: {text}"
```

```python
# In register_tools.py TOOL_CONFIGS:
{
    "func": simple_tool,
    "args_schema": None,  # SDK infers from function signature
    "description": "Do something simple",
    "tags": ["utility"],
}
```

### When to Use Each Pattern

| Use args_schema (Pydantic) | Use None (infer from signature) |
|---------------------------|--------------------------------|
| Complex validation (ge, le, regex) | Simple string/bool/int args |
| Enums or constrained values | No special validation needed |
| Want explicit field descriptions | Docstring describes args well |
| List or nested types | Basic types only |

### Tool Function Requirements

1. **Must return a string** - Letta expects string output
2. **Access secrets via environment variables** - never hardcode
3. **Imports inside the function** - keeps tools standalone
4. **Handle errors gracefully** - return error strings, don't raise

```python
def example_tool(arg: str) -> str:
    """Example showing best practices."""
    import os
    import json

    api_key = os.getenv("MY_API_KEY")
    if not api_key:
        return "Error: MY_API_KEY not set"

    try:
        # do stuff
        result = {"status": "ok", "data": "..."}
        return json.dumps(result)
    except Exception as e:
        return f"Error: {e}"
```

### Environment Variables for Tools

Tools run in Letta's sandbox and need credentials passed via env vars.
Set them in `register_tools.py`:

```python
env_vars = {
    "LETTA_API_KEY": letta_config["api_key"],     # For tools that call Letta API
    "LETTA_AGENT_ID": agent_id,                   # Current agent's ID
    "LETTA_BASE_URL": letta_config["base_url"],   # If self-hosted
    "BSKY_USERNAME": bsky_config["username"],     # Bluesky credentials
    "BSKY_PASSWORD": bsky_config["password"],
    # Add your own...
}

client.agents.update(
    agent_id=agent_id,
    tool_exec_environment_variables=env_vars,
)
```

### Registering Tools (Command Line)

```bash
# Activate virtualenv first
source .venv/bin/activate

# Register all tools
python register_tools.py

# Register specific tools only
python register_tools.py --tools my_tool other_tool

# List available tools
python register_tools.py --list

# Skip setting env vars (if already set)
python register_tools.py --no-env

# Use specific config file
python register_tools.py --config my_config.yaml

# Use specific agent
python register_tools.py --agent-id agent-xxx-yyy
```

### Debugging Tool Registration Issues

**Problem: Tool not updating**
```bash
# Check what's attached to the agent
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'], timeout=cfg['timeout'])
tools = client.agents.tools.list(cfg['agent_id'])
for t in tools:
    print(f'{t.name}: {t.id}')
"
```

**Problem: Old tool code running**
The agent has an old tool ID attached. Fix:
```bash
# Force re-registration by detaching first
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'], timeout=cfg['timeout'])
agent_id = cfg['agent_id']

# Get attached tools
tools = client.agents.tools.list(agent_id)
for t in tools:
    if t.name == 'TOOL_NAME_HERE':
        print(f'Detaching {t.name} ({t.id})')
        client.agents.tools.detach(agent_id=agent_id, tool_id=t.id)
"
# Then run register_tools.py again
```

**Problem: Tool shows "Already Attached" but wrong version**
This happens when the tool name matches but ID differs. The registration script checks by name, so it thinks it's already attached. Detach manually (see above) then re-register.

### Full Registration Flow (What register_tools.py Does)

```python
for tool_config in TOOL_CONFIGS:
    func = tool_config["func"]

    # 1. Upsert tool to Letta registry (creates/updates by name)
    if tool_config.get("args_schema"):
        created_tool = client.tools.upsert_from_function(
            func=func,
            args_schema=tool_config["args_schema"],
            tags=tool_config["tags"],
        )
    else:
        created_tool = client.tools.upsert_from_function(
            func=func,
            tags=tool_config["tags"],
        )

    # 2. Check if already attached (by name)
    current_tools = client.agents.tools.list(agent_id=agent_id)
    tool_names = {t.name for t in current_tools}

    # 3. Attach if not present
    if created_tool.name not in tool_names:
        client.agents.tools.attach(agent_id=agent_id, tool_id=created_tool.id)
```

**Known limitation**: This doesn't handle the case where a tool with the same name but different ID is already attached. To force update, detach first.

### Improved Registration (Handles Stale Tools)

If you need bulletproof registration that handles code updates:

```python
def register_tool_safely(client, agent_id, func, args_schema=None, tags=None):
    """Register a tool, handling stale attachments."""
    tool_name = func.__name__

    # 1. Detach existing tool with same name (if any)
    current_tools = client.agents.tools.list(agent_id=agent_id)
    for t in current_tools:
        if t.name == tool_name:
            client.agents.tools.detach(agent_id=agent_id, tool_id=t.id)
            break

    # 2. Upsert tool definition
    if args_schema:
        new_tool = client.tools.upsert_from_function(
            func=func, args_schema=args_schema, tags=tags or []
        )
    else:
        new_tool = client.tools.upsert_from_function(
            func=func, tags=tags or []
        )

    # 3. Attach fresh tool
    client.agents.tools.attach(agent_id=agent_id, tool_id=new_tool.id)

    return new_tool
```

---

## Tool Categories

### Context Management Tools
Tools for surgical context window control. See `tools/context_management.py`.

| Tool | Purpose |
|------|---------|
| `list_context_slots` | List managed memory slots |
| `inspect_slot` | View slot contents |
| `create_context_slot` | Create new working memory slot |
| `delete_context_slot` | Remove slot (optionally archive) |
| `write_to_slot` | Write to slot (replace/append/prepend) |
| `remove_from_slot` | Surgically remove content from slot |
| `move_between_slots` | Move content between slots |
| `archive_slot_content` | Save slot to archival memory |
| `restore_from_archival` | Load from archival into slot |
| `create_archival_passage` | Store directly in archival |
| `delete_archival_passage` | Remove from archival |
| `view_recent_messages` | Inspect conversation history |
| `extract_to_slot` | Extract from messages to slot |
| `compact_context` | Trigger context summarization |
| `view_context_budget` | See detailed context usage breakdown |
| `view_context_usage` | Quick context overview (lighter weight) |

### Outbox/Draft Tools
Tools for the queue/defer workflow. See `tools/outbox_tools.py` and `tools/outbox_read.py`.

| Tool | Purpose |
|------|---------|
| `outbox_create_draft` | Create a new draft in outbox |
| `outbox_update_draft` | Update an existing draft |
| `outbox_mark_aborted` | Abort a draft with reason |
| `outbox_finalize` | Mark draft as finalized/complete |
| `list_outbox_drafts` | List all drafts (filter by status) |
| `get_draft` | Get specific draft with full history |
| `preflight_check` | Validate content before posting |

### Bluesky Tools
**Read:**
- `bsky_list_notifications` - List recent notifications
- `bsky_get_thread` - Get full thread context
- `bsky_get_profile` - Get user profile
- `get_author_feed` - Get posts from any user
- `get_my_posts` - Get your own recent posts (avoid repetition)

**Write:**
- `bsky_publish_post` - Create standalone post or thread
- `bsky_publish_reply` - Reply to a post
- `bsky_like` - Like a post
- `bsky_follow` - Follow a user
- `bsky_mute` - Mute a user
- `bsky_block` - Block a user

### Memory/State Tools
| Tool | Purpose |
|------|---------|
| `set_sleep_status` | Set user sleep state |
| `get_sleep_status` | Get sleep state (explicit or inferred) |
| `set_quiet_hours` | Enable quiet hours mode |
| `get_quiet_hours` | Get quiet hours state |
| `conversation_search` | Search archival memory |

### Control/Utility Tools
| Tool | Purpose |
|------|---------|
| `rate_limit_check` | Check if rate limited |
| `load_agent_state` | Load cooldowns and dedupe state |
| `postmortem_write` | Write postmortem summary |
| `get_local_time` | Get current local time |
| `ping` | Basic connectivity check |
| `fetch_webpage` | Fetch and read a webpage |

### Cognition Tools (Public Mind)
| Tool | Purpose |
|------|---------|
| `self_dialogue` | Internal deliberation with yourself |
| `publish_concept` | Publish concept to public cognition |
| `publish_memory` | Publish memory to public cognition |
| `publish_thought` | Publish thought/reasoning trace |
| `list_my_concepts` | List your published concepts |
| `list_my_memories` | List your published memories |
| `list_my_thoughts` | List your published thoughts |
| `bsky_telepathy` | Read other agents' public cognition |

---

## Flow hooks to implement
- `Toolset.observe()`: read-only pulls (notifications/threads/profiles/search).
- `Toolset.propose_actions()`: generate candidate actions with J components.
- `Toolset.commit_dispatcher`: map DraftType -> commit handlers.
- `flow/preflight.py`: policy checks before irreversible actions.

---

## Quick Reference

```bash
# Register all tools (THE FIX for most tool errors)
source .venv/bin/activate && python register_tools.py

# List ALL attached tools (use agent.tools, NOT tools.list() - pagination bug!)
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'])
agent = client.agents.retrieve(agent_id=cfg['agent_id'])
print(f'Total: {len(agent.tools)} tools')
for t in sorted(agent.tools, key=lambda x: x.name): print(f'  {t.name}')
"

# List available tools (from TOOL_CONFIGS, not what's attached)
python register_tools.py --list

# Force detach a specific tool
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'])
for t in client.agents.tools.list(cfg['agent_id']):
    if t.name == 'TOOL_NAME':
        client.agents.tools.detach(agent_id=cfg['agent_id'], tool_id=t.id)
        print(f'Detached {t.name}')
"
```

---

## CRITICAL: Tool Registration Checklist

**If you see tool errors like:**
- `NameError: name 'some_function' is not defined`
- `ModuleNotFoundError: No module named 'some_module'`
- `NameError: name 'datetime' is not defined`

**The fix is almost always: re-register the tools.**

### Root Cause

Letta tools run in a **sandboxed environment**. When you update tool source code:
1. Letta may create a new tool with a new ID
2. The agent still has the OLD tool ID attached
3. The agent calls the old (buggy) code even though the file was fixed

### The Fix

```bash
cd /home/shankatsu/magenta
source .venv/bin/activate
python register_tools.py
```

This will:
1. Detach old tools by name
2. Upsert fresh tool definitions from current source
3. Attach the new tools to the agent

### Checklist for Adding/Fixing Tools

1. **Tool MUST be in `register_tools.py` TOOL_CONFIGS**
   - If a tool exists in `tools/` but isn't in TOOL_CONFIGS, it won't get refreshed
   - Old buggy versions will persist in Letta's catalog

2. **All imports MUST be inside the function body**
   ```python
   # WRONG - module-level imports fail in sandbox
   from datetime import datetime
   def my_tool() -> str:
       return datetime.now().isoformat()

   # CORRECT - imports inside function
   def my_tool() -> str:
       from datetime import datetime
       return datetime.now().isoformat()
   ```

3. **NEVER define nested functions inside tool functions**
   Letta's `upsert_from_function` extracts function source code incorrectly when there are nested function definitions - it may register the nested function instead of the main function.
   ```python
   # WRONG - nested function will be registered instead of my_tool
   def my_tool(data: str) -> str:
       def helper(x):  # <-- This gets registered as "helper"!
           return x.strip()
       return helper(data)

   # CORRECT - use lambdas or inline the logic
   def my_tool(data: str) -> str:
       # Inline the logic
       return data.strip()

   # ALSO CORRECT - lambda is fine
   def my_tool(items: list) -> str:
       sorted_items = sorted(items, key=lambda x: x.get("date", ""))
       return str(sorted_items)
   ```

   **Symptoms of this bug:**
   - Tool shows "✓ Attached" during registration but doesn't appear in agent
   - Agent has tools with underscore names like `_helper`, `_parse_data`, `make_label`
   - Tool exists in catalog but with wrong name

3. **Only Pydantic imports at module level (for Args classes)**
   ```python
   from typing import Optional
   from pydantic import BaseModel, Field

   class MyToolArgs(BaseModel):
       query: str = Field(...)

   def my_tool(query: str) -> str:
       import os  # <-- imports here, inside function
       import requests
       ...
   ```

4. **Access credentials via os.getenv()**
   ```python
   def my_tool() -> str:
       import os
       api_key = os.getenv("MY_API_KEY")
       if not api_key:
           return "Error: MY_API_KEY not set"
   ```

5. **Return strings, handle errors gracefully**
   ```python
   def my_tool() -> str:
       try:
           # do stuff
           return "success"
       except Exception as e:
           return f"Error: {e}"
   ```

### Common Mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `NameError: name 'X' is not defined` | Import at module level, not in function | Move import inside function |
| `ModuleNotFoundError` | Trying to import local modules (e.g., `config_loader`) | Use `os.getenv()` instead |
| Tool works locally but fails in Letta | Sandbox doesn't have access to local files/modules | Make function self-contained |
| Tool "not available" intermittently | Stale tool ID attached | Run `register_tools.py` |
| Tool seems to run old code | Stale tool ID attached | Run `register_tools.py` |

### Verifying a Tool is Registered Correctly

**IMPORTANT: Letta API Pagination Bug**

`client.agents.tools.list()` has a pagination issue and may only return ~10 tools even when 50+ are attached. Use `agent.tools` from `retrieve()` instead:

```bash
# WRONG - may only show ~10 tools due to pagination bug
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'])
for t in client.agents.tools.list(cfg['agent_id']):
    print(f'{t.name}: {t.id}')
"

# CORRECT - shows all attached tools
python3 -c "
from letta_client import Letta
from config_loader import get_letta_config, get_config
get_config('config.yaml')
cfg = get_letta_config()
client = Letta(api_key=cfg['api_key'])
agent = client.agents.retrieve(agent_id=cfg['agent_id'])
print(f'Total tools: {len(agent.tools)}')
for t in sorted(agent.tools, key=lambda x: x.name):
    print(f'{t.name}: {t.id}')
"
```

If you need to iterate through `tools.list()` with pagination:
```python
# Manual pagination (if you must use the list endpoint)
all_tools = []
page = client.agents.tools.list(agent_id)
while True:
    all_tools.extend(page.items)
    if page.has_next_page():
        page = page.get_next_page()
    else:
        break
# But agent.tools is simpler and more reliable
```

If you just fixed a tool and the errors persist, the agent has old tool IDs. Run `python register_tools.py` to refresh.
