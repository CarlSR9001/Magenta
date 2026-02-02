# Tool Rules (Magenta)

This codifies the guarded flow: **observe → decide → draft → preflight → commit → postmortem**.
The rules are designed to prevent spam by enforcing a two‑phase commit and strict caps on side effects.

## Run First
- `rate_limit_check`
- `bsky_list_notifications`
- `load_agent_state` (cooldowns, per-user caps, dedupe)
- `get_local_time` (America/Chicago)
- `get_quiet_hours`
- `get_sleep_status`

## Constrain Tools
- `outbox_create_draft` must precede `preflight_check`.
- `preflight_check` must precede any commit tool.
- `outbox_finalize` must occur before exit.
- `memory_update_core` only after `S' >= core_threshold` (enforced in orchestrator).
- If `need_more_context == true`, allow one additional `bsky_get_thread` or `conversation_search` pass before exit.

## Required Before Exit
- `outbox_finalize` (commit or abort).
- `postmortem_write` after any commit (enforced in orchestrator).

## Max Count Per Step
- commit tools: max 1
- `conversation_search`: max 1 unless `need_more_context == true`
- thread fetch: cap N (2–4)

## Continue Loop
- Only loop if `need_more_context == true` AND `loops_remaining > 0`.
- Otherwise exit.

## Terminal Tools
- Any commit tool is terminal.
- `memory_update_core` can be terminal for deterministic runs.

## Commit Tools
- `bsky_publish_post`
- `bsky_publish_reply`
- `bsky_like`
- `bsky_follow`
- `bsky_mute`
- `bsky_block`

## Draft Tools
- `outbox_create_draft`
- `outbox_update_draft`
- `outbox_mark_aborted`
- `outbox_finalize`

## Preflight Tool
- `preflight_check`
