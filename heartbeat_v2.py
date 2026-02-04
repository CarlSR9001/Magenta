#!/usr/bin/env python3
"""Interoception-based heartbeat for Magenta agent.

This is the v2 heartbeat that uses the interoception layer instead of
cron-based scheduling. The agent wakes up when internal pressure demands
attention, not when the clock says it's time.

Key differences from heartbeat.py:
- No fixed schedules - signals emerge from accumulated pressure
- Different signal types trigger different behaviors
- RNG jitter provides biological variability
- External state (notifications, errors, context usage) influences signals
- Quiet mode suppresses all non-critical signals

To migrate from heartbeat.py:
1. Stop heartbeat.py
2. Start heartbeat_v2.py
3. State is separate - interoception state is in state/interoception.json

To run both during transition:
- They use different state files
- But they'll both wake the agent, so pick one
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from letta_client import Letta

from config_loader import get_config, get_letta_config
from interoception import (
    LimbicLayer,
    MagentaStateProvider,
    Signal,
    EmittedSignal,
    InteroceptionStateStore,
    InteroceptionState,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Marker for interoception state in Letta archival memory
INTEROCEPTION_STATE_MARKER = "[INTEROCEPTION_STATE]"
SYNC_STATE_PATH = Path("state/sync_state.json")


def _detect_outcome(response: str) -> str:
    """Detect the outcome of agent action from response text.

    Returns one of: 'high_engagement', 'acknowledged', 'skipped', 'error'

    This is more sophisticated than simple keyword matching:
    - Handles JSON tool results from Moltbook ({"status": "success"/"error"})
    - Detects explicit skips/passes
    - Better error pattern matching
    """
    import re

    response_lower = response.lower()

    # Check for JSON-formatted tool results (Moltbook style)
    # Look for {"status": "error"} or {"status": "success"} patterns
    json_error_pattern = r'"status"\s*:\s*"error"'
    json_success_pattern = r'"status"\s*:\s*"success"'

    if re.search(json_error_pattern, response_lower):
        return "error"
    if re.search(json_success_pattern, response_lower):
        return "high_engagement"

    # Error indicators (expanded)
    error_patterns = [
        "error:", "error ", "failed", "couldn't", "unable to",
        "cannot", "can't", "not found", "invalid", "exception",
        "timeout", "refused", "denied", "blocked", "rate limit",
    ]
    if any(pattern in response_lower for pattern in error_patterns):
        return "error"

    # High engagement - actual actions taken
    engagement_patterns = [
        "posted", "replied", "created", "sent", "completed",
        "published", "commented", "liked", "followed", "shared",
        "success!", "url:", "https://",
    ]
    if any(pattern in response_lower for pattern in engagement_patterns):
        return "high_engagement"

    # Explicit skips/passes - agent decided not to act
    skip_patterns = [
        "skipping", "skipped", "nothing to", "no action",
        "no pending", "all clear", "healthy", "no notifications",
        "no items", "nothing needs", "decided not to",
        "will not", "won't", "passing on", "pass on", "deferring",
        "not responding", "choosing not to", "chose not to",
    ]
    if any(pattern in response_lower for pattern in skip_patterns):
        return "skipped"

    # Default to acknowledged - agent processed but outcome unclear
    return "acknowledged"


def sync_quiet_from_archival(client: Letta, agent_id: str, limbic: "LimbicLayer") -> bool:
    """Sync quiet mode setting FROM archival memory TO local state.

    This allows the agent to set quiet mode via tools, and have the
    heartbeat respect it. Only syncs quiet_until to avoid conflicts.
    """
    import json

    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=INTEROCEPTION_STATE_MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []

        # Pick the most recent matching passage to avoid stale reads
        def _get_ts(passage):
            return getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(INTEROCEPTION_STATE_MARKER)]
        if not candidates:
            return False
        latest = max(candidates, key=lambda p: _get_ts(p) or "")

        text = getattr(latest, "text", "")
        json_str = text[len(INTEROCEPTION_STATE_MARKER):].strip()
        archival_state = json.loads(json_str)
        archival_quiet = archival_state.get("quiet_until")

        # If archival has quiet mode set and local doesn't, apply it
        if archival_quiet and not limbic.state.quiet_until:
            limbic.state.quiet_until = archival_quiet
            logger.info(f"Synced quiet mode from archival: until {archival_quiet}")
            return True
        # If archival cleared quiet mode but local still has it, clear it
        elif not archival_quiet and limbic.state.quiet_until:
            limbic.state.quiet_until = None
            logger.info("Cleared quiet mode from archival sync")
            return True
        return False
    except Exception as e:
        logger.debug(f"Failed to sync quiet from archival: {e}")
        return False


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def sync_state_from_archival(client: Letta, agent_id: str, limbic: "LimbicLayer") -> bool:
    """Sync full state FROM archival memory TO local state if archival is newer.

    This allows Letta cloud tools (which mutate archival state) to influence
    the local heartbeat's behavior.
    """
    import json

    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=INTEROCEPTION_STATE_MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []

        def _get_ts(passage):
            return getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(INTEROCEPTION_STATE_MARKER)]
        if not candidates:
            return False
        latest = max(candidates, key=lambda p: _get_ts(p) or "")
        text = getattr(latest, "text", "")
        json_str = text[len(INTEROCEPTION_STATE_MARKER):].strip()
        archival_state = json.loads(json_str)

        local_state = limbic.state.to_dict()

        # Merge per-signal state based on most recent last_updated timestamp
        local_pressures = local_state.get("pressures", {})
        archival_pressures = archival_state.get("pressures", {})
        merged_pressures = {}

        all_signal_keys = set(local_pressures.keys()) | set(archival_pressures.keys())
        for signal in all_signal_keys:
            remote_p = archival_pressures.get(signal, {})
            local_p = local_pressures.get(signal, {})
            remote_updated = _parse_iso(remote_p.get("last_updated"))
            local_updated = _parse_iso(local_p.get("last_updated"))

            if local_updated is None or (remote_updated and remote_updated > local_updated):
                merged = remote_p
            else:
                merged = local_p

            # Merge known_pending and last_outcomes conservatively
            merged_pending = dict(local_p.get("known_pending", {}))
            merged_pending.update(remote_p.get("known_pending", {}))
            merged_outcomes = dict(local_p.get("last_outcomes", {}))
            merged_outcomes.update(remote_p.get("last_outcomes", {}))

            merged["known_pending"] = merged_pending
            merged["last_outcomes"] = merged_outcomes
            merged["emission_count"] = max(
                int(local_p.get("emission_count", 0)),
                int(remote_p.get("emission_count", 0)),
            )

            # Prefer newer last_emitted / last_action when available
            remote_emitted = _parse_iso(remote_p.get("last_emitted"))
            local_emitted = _parse_iso(local_p.get("last_emitted"))
            if local_emitted is None or (remote_emitted and remote_emitted > local_emitted):
                merged["last_emitted"] = remote_p.get("last_emitted")

            remote_action = _parse_iso(remote_p.get("last_action"))
            local_action = _parse_iso(local_p.get("last_action"))
            if local_action is None or (remote_action and remote_action > local_action):
                merged["last_action"] = remote_p.get("last_action")

            merged_pressures[signal] = merged

        local_state["pressures"] = merged_pressures
        local_state["quiet_until"] = archival_state.get("quiet_until", local_state.get("quiet_until"))

        # Prefer newer global timestamps
        remote_last_wake = _parse_iso(archival_state.get("last_wake"))
        local_last_wake = _parse_iso(local_state.get("last_wake"))
        if local_last_wake is None or (remote_last_wake and remote_last_wake > local_last_wake):
            local_state["last_wake"] = archival_state.get("last_wake")

        local_state["total_emissions"] = max(
            int(local_state.get("total_emissions", 0)),
            int(archival_state.get("total_emissions", 0)),
        )

        limbic.state = InteroceptionState.from_dict(local_state)
        limbic.accumulator.state = limbic.state
        limbic._save_state()
        return True
    except Exception as e:
        logger.debug(f"Failed to sync full state from archival: {e}")
        return False


def sync_state_to_archival(client: Letta, agent_id: str, state_dict: dict) -> bool:
    """Sync interoception state to Letta archival memory.

    This allows Letta cloud tools to read the same state that the
    local heartbeat process maintains.
    """
    import json

    try:
        # First, delete any existing state passages
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=INTEROCEPTION_STATE_MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []

        for passage in items:
            text = getattr(passage, "text", "")
            if text.startswith(INTEROCEPTION_STATE_MARKER):
                passage_id = getattr(passage, "id", None)
                if passage_id:
                    try:
                        # Correct API: delete(memory_id, agent_id=...)
                        client.agents.passages.delete(str(passage_id), agent_id=agent_id)
                    except Exception:
                        pass

        # Create new state passage
        state_json = json.dumps(state_dict, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{INTEROCEPTION_STATE_MARKER}\n{state_json}"
        )
        logger.debug("Synced interoception state to archival memory")
        return True
    except Exception as e:
        logger.warning(f"Failed to sync state to archival: {e}")
        return False


def write_sync_snapshot(provider: MagentaStateProvider, limbic: LimbicLayer) -> None:
    """Write a unified local snapshot to keep tools consistent after resets."""
    try:
        pending = provider.get_pending_notifications()
    except Exception:
        pending = {}
    try:
        context_usage = provider.get_context_usage()
    except Exception:
        context_usage = 0.0
    try:
        state = provider._load_agent_state()
    except Exception:
        state = {}

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": {
            "usage_pct": round(context_usage * 100, 2),
            "usage_fraction": context_usage,
        },
        "pending": pending,
        "processed_notifications_count": len(state.get("processed_notifications", [])),
        "last_commit_at": state.get("last_commit_at"),
        "limbic": {
            "last_wake": limbic.state.last_wake,
            "total_emissions": limbic.state.total_emissions,
            "quiet_until": limbic.state.quiet_until,
        },
    }

    SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_PATH.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_agent_with_signal(
    client: Letta,
    agent_id: str,
    emitted: EmittedSignal,
    limbic: LimbicLayer,
) -> bool:
    """Send the signal prompt to the agent and handle response.

    Returns True if successful, False otherwise.
    """
    prompt = limbic.get_prompt_for_signal(emitted)

    logger.info(f"Waking agent with {emitted.signal.value} signal")
    logger.debug(f"Prompt: {prompt[:200]}...")

    try:
        # Use streaming API for better reliability
        last_assistant_msg = None
        for chunk in client.agents.messages.stream(
            agent_id=agent_id,
            messages=[{"role": "user", "content": prompt}]
        ):
            if getattr(chunk, "message_type", None) == "assistant_message":
                content = getattr(chunk, "content", "")
                if content:
                    last_assistant_msg = content

        if last_assistant_msg:
            logger.info(f"Agent response: {last_assistant_msg[:200]}...")

            # Record outcome based on response - improved heuristics
            outcome = _detect_outcome(last_assistant_msg)
            limbic.record_action(emitted.signal, outcome)

        return True
    except Exception as e:
        logger.error(f"Failed to run agent: {e}")
        limbic.record_action(emitted.signal, "error")
        return False


def run_queue_cycle() -> bool:
    """Process queued drafts (same as heartbeat.py)."""
    try:
        from flow import (
            AgentStateStore,
            DecisionPolicy,
            MemoryPolicy,
            OutboxStore,
            SalienceConfig,
            TelemetryStore,
            run_queue_once,
        )
        from flow.commit import CommitDispatcher
        from flow.commit_handlers import (
            commit_block,
            commit_follow,
            commit_like,
            commit_mute,
            commit_post,
            commit_reply,
        )
        from flow.models import DraftType
        from agent import MagentaAgent

        policy = DecisionPolicy(
            salience_config=SalienceConfig(weights={"delta_u": 0.4, "risk": -0.4}),
            j_weights={
                "voi": 1.0,
                "optionality": 0.5,
                "risk": 1.0,
                "fatigue": 1.0,
            },
            low_action_threshold=0.0,
            high_action_threshold=0.2,
            queue_threshold=0.05,
        )
        outbox = OutboxStore(Path("outbox"))
        dispatcher = CommitDispatcher({
            DraftType.POST: commit_post,
            DraftType.REPLY: commit_reply,
            DraftType.QUOTE: commit_post,
            DraftType.LIKE: commit_like,
            DraftType.FOLLOW: commit_follow,
            DraftType.MUTE: commit_mute,
            DraftType.BLOCK: commit_block,
        })
        toolset = MagentaAgent(
            outbox=outbox,
            policy=policy,
            memory_policy=MemoryPolicy(),
            commit_dispatcher=dispatcher,
        )
        state_store = AgentStateStore(Path("state/agent_state.json"))
        telemetry = TelemetryStore(Path("state/telemetry.jsonl"))

        run_queue_once(toolset, state_store, telemetry, outbox)
        return True
    except Exception as e:
        logger.error(f"Queue cycle failed: {e}")
        return False


def run_cleanup_cycle() -> bool:
    """Cleanup stale drafts (same as heartbeat.py)."""
    try:
        from flow import OutboxStore
        from tools.outbox_tools import outbox_purge_stale_drafts

        outbox = OutboxStore(Path("outbox"))
        fs_purged = outbox.purge_stale_drafts(max_age_hours=24)
        logger.info(f"Filesystem outbox: purged {fs_purged} stale drafts")

        try:
            result = outbox_purge_stale_drafts(max_age_hours=24)
            logger.info(f"Letta archival: {result}")
        except Exception as e:
            logger.warning(f"Letta archival cleanup skipped: {e}")

        return True
    except Exception as e:
        logger.error(f"Cleanup cycle failed: {e}")
        return False


def mark_notifications_processed(outcome: str = "acknowledged") -> int:
    """Mark notifications based on how the agent handled the SOCIAL signal.

    Args:
        outcome: The outcome from the agent's response
            - 'high_engagement': Agent actively handled notifications - mark as processed
            - 'skipped'/'acknowledged': Agent saw them but didn't act - mark but note status
            - 'error': Something went wrong - don't mark anything (will retry)

    This is called after SOCIAL signals are handled, since Letta cloud tools
    cannot access local filesystem. The heartbeat marks them on behalf of the agent.
    """
    # If the agent errored, don't mark anything - let it retry next time
    if outcome == "error":
        logger.info("SOCIAL signal errored - not marking notifications (will retry)")
        return 0

    try:
        from notification_db import NotificationDB
        from flow.bsky_api import BskyApi
        from config_loader import get_bluesky_config

        bsky_cfg = get_bluesky_config()
        bsky = BskyApi(
            username=bsky_cfg.get("username"),
            password=bsky_cfg.get("password"),
            pds_uri=bsky_cfg.get("pds_uri"),
        )

        notifications = bsky.list_notifications(limit=50)
        db = NotificationDB()
        processed = db.get_all_processed_uris()

        # Determine status based on outcome
        if outcome == "high_engagement":
            status = "agent_handled"
            reason = "agent_responded_to_social_signal"
        elif outcome == "skipped":
            status = "agent_skipped"
            reason = "agent_saw_but_chose_not_to_respond"
        else:
            status = "auto_processed"
            reason = "social_signal_handled_outcome_unclear"

        count = 0
        for notif in notifications:
            uri = notif.get("uri", "")
            if uri and uri not in processed:
                db.mark_processed(uri, status=status, reason=reason)
                count += 1

        db.close()
        logger.info(f"Marked {count} notifications as '{status}' (outcome: {outcome})")
        return count
    except Exception as e:
        logger.warning(f"Failed to mark notifications: {e}")
        return 0


def handle_signal(
    emitted: EmittedSignal,
    client: Letta,
    agent_id: str,
    limbic: LimbicLayer,
) -> None:
    """Handle an emitted signal appropriately.

    Most signals wake the main agent with a contextual prompt.
    Some signals (like MAINTENANCE) may also trigger specific actions.
    """
    signal_type = emitted.signal

    # MAINTENANCE signal also runs queue processing
    if signal_type == Signal.MAINTENANCE:
        run_queue_cycle()

    # All signals wake the agent with their prompt
    run_agent_with_signal(client, agent_id, emitted, limbic)

    # After SOCIAL signal, mark notifications based on how agent handled them
    # This compensates for Letta cloud tools not having local filesystem access
    if signal_type == Signal.SOCIAL:
        # Get the outcome that was just recorded
        social_state = limbic.state.get_pressure(Signal.SOCIAL)
        last_outcome = social_state.last_outcomes.get("social", "acknowledged")
        mark_notifications_processed(outcome=last_outcome)

    # Periodic cleanup on MAINTENANCE or STALE
    if signal_type in (Signal.MAINTENANCE, Signal.STALE):
        if emitted.context.get("emission_count", 0) % 6 == 0:
            run_cleanup_cycle()


def main():
    parser = argparse.ArgumentParser(
        description="Interoception-based Magenta Heartbeat (v2)"
    )
    parser.add_argument(
        "--tick-interval",
        type=int,
        default=60,
        help="Seconds between limbic layer ticks (default: 60)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print status and exit"
    )
    parser.add_argument(
        "--quiet",
        type=float,
        help="Enable quiet mode for N hours"
    )
    parser.add_argument(
        "--clear-quiet",
        action="store_true",
        help="Disable quiet mode"
    )
    parser.add_argument(
        "--force-signal",
        type=str,
        choices=[s.value for s in Signal],
        help="Force emit a specific signal"
    )
    args = parser.parse_args()

    # Load config
    get_config("config.yaml")
    letta_cfg = get_letta_config()

    # Initialize Letta client
    client_params = {
        "api_key": letta_cfg["api_key"],
        "timeout": letta_cfg.get("timeout", 600),
    }
    if letta_cfg.get("base_url"):
        client_params["base_url"] = letta_cfg["base_url"]
    try:
        client = Letta(**client_params)
    except TypeError:
        client_params["key"] = client_params.pop("api_key")
        client = Letta(**client_params)
    agent_id = letta_cfg["agent_id"]

    # Initialize interoception layer
    state_store = InteroceptionStateStore(Path("state/interoception.json"))
    provider = MagentaStateProvider(
        agent_state_path=Path("state/agent_state.json"),
        telemetry_path=Path("state/telemetry.jsonl"),
    )
    limbic = LimbicLayer(
        state_store=state_store,
        external_provider=provider,
    )

    # Handle one-shot commands
    if args.status:
        status = limbic.get_status()
        import json
        print(json.dumps(status, indent=2))
        return

    if args.quiet:
        limbic.set_quiet_hours(args.quiet)
        logger.info(f"Quiet mode enabled for {args.quiet} hours")
        return

    if args.clear_quiet:
        limbic.clear_quiet_hours()
        logger.info("Quiet mode disabled")
        return

    if args.force_signal:
        signal_type = Signal(args.force_signal)
        emitted = limbic.force_signal(signal_type, reason="manual_force")
        logger.info(f"Forced signal: {emitted}")
        handle_signal(emitted, client, agent_id, limbic)
        return

    # Main loop
    running = True

    def sig_handler(sig, frame):
        nonlocal running
        logger.info("Received shutdown signal")
        running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    logger.info("=" * 60)
    logger.info("Interoception Heartbeat v2 Starting")
    logger.info("=" * 60)
    logger.info(f"Tick interval: {args.tick_interval}s")
    logger.info(f"Quiet mode: {'active' if limbic.accumulator.is_quiet() else 'inactive'}")

    # Log initial status
    status = limbic.get_status()
    logger.info(f"Active signals: {len([s for s in status['signals'].values() if s['pressure'] > 0])}")

    # Sync quiet mode and full state FROM archival first (agent may have set it while heartbeat was down)
    sync_quiet_from_archival(client, agent_id, limbic)
    sync_state_from_archival(client, agent_id, limbic)
    limbic._save_state()

    # Then sync full state TO archival (but quiet_until is now preserved)
    sync_state_to_archival(client, agent_id, limbic.state.to_dict())
    write_sync_snapshot(provider, limbic)

    tick_count = 0
    last_sync_tick = 0
    last_quiet_sync_tick = 0
    last_full_sync_tick = 0
    while running:
        tick_count += 1
        logger.debug(f"Tick {tick_count}")

        # Sync quiet mode from archival every tick (agent may have set it)
        if tick_count - last_quiet_sync_tick >= 1:
            if sync_quiet_from_archival(client, agent_id, limbic):
                limbic._save_state()  # Persist the change
            last_quiet_sync_tick = tick_count
            write_sync_snapshot(provider, limbic)

        # Sync full state from archival periodically (tools may have updated it)
        if tick_count - last_full_sync_tick >= 5:
            if sync_state_from_archival(client, agent_id, limbic):
                limbic._save_state()
            last_full_sync_tick = tick_count

        # Run limbic layer tick
        emitted = limbic.tick()

        if emitted:
            logger.info(f"Signal emitted: {emitted}")
            handle_signal(emitted, client, agent_id, limbic)

            # Sync state to archival after signal emission
            sync_state_to_archival(client, agent_id, limbic.state.to_dict())
            last_sync_tick = tick_count
            write_sync_snapshot(provider, limbic)

            if args.once:
                logger.info("--once flag set, exiting after first signal")
                break
        else:
            # Log pressure summary every 10 ticks
            if tick_count % 10 == 0:
                pressures = limbic.accumulator.get_all_pressures()
                top_pressures = sorted(
                    pressures.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]
                pressure_str = ", ".join(
                    f"{s.value}={p:.2f}" for s, p in top_pressures
                )
                logger.debug(f"Top pressures: {pressure_str}")

            # Sync state to archival every 5 ticks (5 minutes at default interval)
            if tick_count - last_sync_tick >= 5:
                sync_state_to_archival(client, agent_id, limbic.state.to_dict())
                last_sync_tick = tick_count
                write_sync_snapshot(provider, limbic)

        # Sleep until next tick
        if running and not args.once:
            time.sleep(args.tick_interval)

    logger.info("Interoception Heartbeat v2 stopped")


if __name__ == "__main__":
    main()
