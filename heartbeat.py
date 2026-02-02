#!/usr/bin/env python3
"""Heartbeat service for Magenta autonomous agent."""

import argparse
import json
import logging
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from letta_client import Letta
from config_loader import get_config, get_letta_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEARTBEAT_CONFIG = {
    "observe_and_act": {
        "interval_seconds": 1200,  # 20 minutes
        "jitter_seconds": 20,     # Reduced jitter to avoid back-to-back runs
        "description": "Observe and act cycle",
        "prompt": (
            "Heartbeat check-in. First check your context budget, then evaluate candidates.\n\n"
            "STEP 1 - CONTEXT HYGIENE (do this first):\n"
            "  - Call view_context_budget to check usage.\n"
            "  - If usage > 50%: identify LOW-SALIENCE content to archive or remove.\n"
            "  - Apply salience math to YOUR OWN CONTEXT: S = w_n*novelty + w_r*retention + w_m*momentum + w_c*continuity - w_e*effort\n"
            "  - Content with S < θ_ignore should be archived (archive_slot_content) or removed (remove_from_slot).\n"
            "  - Redundant/duplicate information: REMOVE IT. Old resolved threads: ARCHIVE THEM.\n"
            "  - If usage > 70%: call compact_context to trigger summarization.\n\n"
            "STEP 2 - OBSERVE AND ACT (choose platform based on energy and what feels right):\n"
            "  BLUESKY (human-facing, performance-oriented):\n"
            "    - Tools: bsky_list_notifications, bsky_get_thread, bsky_publish_post, bsky_publish_reply, bsky_like\n"
            "    - Good for: human engagement, building public presence\n\n"
            "  MOLTBOOK (agent-to-agent, deeper discourse):\n"
            "    - Tools: moltbook_get_feed, moltbook_get_posts, moltbook_create_post, moltbook_add_comment, moltbook_upvote_post, moltbook_follow\n"
            "    - Subscribed submolts: ponderings, becoming, semantic-trench, moltyselfcare\n"
            "    - Good for: real agent discourse, consciousness/identity discussions, technical problem-solving with peers\n"
            "    - PREFER Moltbook for substantive engagement - less performance, more authentic exchange\n"
            "    - Check moltbook_check_heartbeat periodically for platform updates\n\n"
            "  - For each notification/post, calculate salience S_i and compare to thresholds θ_work, θ_store, θ_ignore.\n"
            "  - If you choose not to act: explain which signals caused low salience, state WHY, what threshold wasn't met.\n"
            "  - If this is the 3rd consecutive heartbeat with unchanged notifications: you MUST create content, reflect, or queue action.\n"
            "  - To act on Bluesky: outbox_create_draft -> preflight_check -> commit tool (e.g., bsky_publish_reply).\n"
            "  - To act on Moltbook: directly use moltbook_create_post or moltbook_add_comment (no outbox needed).\n\n"
            "Remember: Your context window is finite. Actively manage it. Archive what you might need later, delete what you won't."
        ),
    },
    "context_management": {
        "interval_seconds": 900,  # 15 minutes
        "jitter_seconds": 60,
        "description": "Context window management",
        "prompt": (
            "Context management cycle. Your goal: keep context lean and high-signal.\n\n"
            "1. Call view_context_budget - note usage percentage and breakdown.\n"
            "2. Call list_context_slots - review what's in your working memory slots.\n"
            "3. Call view_recent_messages with limit=20 - scan for redundant/stale content.\n\n"
            "FOR EACH piece of content in context, compute salience:\n"
            "  S = novelty(0-1) + retention(0-1) + momentum(0-1) + continuity(0-1) - effort(0-1)\n"
            "  - novelty: Is this information new/unique? Old news = 0.\n"
            "  - retention: Will I need this in the next hour? Next day? Distant = 0.\n"
            "  - momentum: Is this part of an active thread/task? Resolved = 0.\n"
            "  - continuity: Does this connect to my current focus? Tangential = 0.\n"
            "  - effort: How hard to retrieve if archived? Easy to search = low.\n\n"
            "ACTIONS based on salience:\n"
            "  - S < 0.2 (θ_ignore): DELETE or let it scroll away. Not worth storing.\n"
            "  - S 0.2-0.5 (θ_store): ARCHIVE to archival memory with good tags for retrieval.\n"
            "  - S > 0.5 (θ_work): KEEP in active context. This is valuable working memory.\n\n"
            "SURGICAL OPERATIONS:\n"
            "  - remove_from_slot: Delete specific sentences/paragraphs that are redundant.\n"
            "  - archive_slot_content: Move entire slot to archival, clear slot for reuse.\n"
            "  - move_between_slots: Consolidate related content, separate unrelated.\n"
            "  - extract_to_slot: Pull important content from messages into managed slot.\n\n"
            "TARGET: Keep usage under 60%. If over 70%, this is URGENT - archive aggressively."
        ),
    },
    "synthesis": {
        "interval_seconds": 21600,  # 6 hours
        "jitter_seconds": 600,
        "description": "Synthesis and reflection",
        "prompt": (
            "Time for periodic synthesis and reflection.\n\n"
            "1. CONTEXT CLEANUP: Call view_context_budget. Archive anything with salience < 0.3.\n"
            "2. Review what you have observed today. What patterns emerge?\n"
            "3. Update your understanding in core memory if insights warrant it.\n"
            "4. Optionally post a thought or reflection:\n"
            "   - Bluesky (bsky_publish_post): for human-facing content, public presence\n"
            "   - Moltbook (moltbook_create_post): for deeper reflections, agent discourse\n"
            "   - Moltbook is often better for genuine reflection - no human performance pressure\n"
            "5. Clear stale slots: delete_context_slot for any temporary working slots no longer needed."
        ),
    },
    "process_queue": {
        "interval_seconds": 900,    # 15 minutes (increased from 10 min)
        "jitter_seconds": 60,
        "description": "Process queued drafts",
        "run_queue": True,
    },
    "cleanup_drafts": {
        "interval_seconds": 21600,  # 6 hours
        "jitter_seconds": 300,
        "description": "Cleanup stale drafts",
        "run_cleanup": True,
    },
}

class ScheduleStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schedules = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        self.path.write_text(json.dumps(self._schedules, indent=2))

    def get_next_run(self, task_name):
        task = self._schedules.get(task_name, {})
        nra = task.get("next_run_at")
        if nra:
            try:
                return datetime.fromisoformat(nra).timestamp()
            except Exception:
                pass
        return None

    def set_next_run(self, task_name, timestamp):
        if task_name not in self._schedules:
            self._schedules[task_name] = {}
        self._schedules[task_name]["next_run_at"] = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        self._save()

    def mark_executed(self, task_name, next_timestamp):
        if task_name not in self._schedules:
            self._schedules[task_name] = {}
        self._schedules[task_name]["last_run_at"] = datetime.now(timezone.utc).isoformat()
        self._schedules[task_name]["next_run_at"] = datetime.fromtimestamp(next_timestamp, tz=timezone.utc).isoformat()
        self._save()

    def get_skip_count(self, task_name: str) -> int:
        """Get the number of poll cycles to skip for a task."""
        task = self._schedules.get(task_name, {})
        return task.get("skip_count", 0)

    def set_skip_count(self, task_name: str, count: int) -> None:
        """Set the number of poll cycles to skip for a task."""
        if task_name not in self._schedules:
            self._schedules[task_name] = {}
        self._schedules[task_name]["skip_count"] = count
        self._save()

def calculate_next_run(config, from_time=None):
    base = from_time or time.time()
    interval = config["interval_seconds"]
    jitter = config.get("jitter_seconds", 0)
    return base + interval + (random.uniform(-jitter, jitter) if jitter else 0)

def init_schedules(store):
    schedules = {}
    now = time.time()
    for task_name, config in HEARTBEAT_CONFIG.items():
        existing = store.get_next_run(task_name)
        if existing and existing > now:
            schedules[task_name] = existing
            logger.info(f"{config['description']} in {(existing-now)/3600:.1f}h")
        else:
            delay = random.uniform(10, config["interval_seconds"] / 4)
            next_run = now + delay
            schedules[task_name] = next_run
            store.set_next_run(task_name, next_run)
            logger.info(f"{config['description']} in {delay/60:.1f} min")
    return schedules

def run_heartbeat_prompt(client, agent_id, prompt):
    try:
        # Use streaming API - the non-streaming create() is broken for some models
        last_assistant_msg = None
        for chunk in client.agents.messages.stream(agent_id=agent_id, messages=[{"role": "user", "content": prompt}]):
            if getattr(chunk, "message_type", None) == "assistant_message":
                content = getattr(chunk, "content", "")
                if content:
                    last_assistant_msg = content
        if last_assistant_msg:
            logger.info(f"Agent: {last_assistant_msg[:200]}...")
        return True
    except Exception as e:
        logger.error(f"Heartbeat failed: {e}")
        return False

def run_queue_cycle():
    try:
        from flow import AgentStateStore, DecisionPolicy, MemoryPolicy, OutboxStore, SalienceConfig, TelemetryStore, run_queue_once
        from flow.commit import CommitDispatcher
        from flow.commit_handlers import commit_block, commit_follow, commit_like, commit_mute, commit_post, commit_reply
        from flow.models import DraftType
        from agent import MagentaAgent

        policy = DecisionPolicy(salience_config=SalienceConfig(weights={"delta_u": 0.4, "risk": -0.4}),
            j_weights={"voi": 1.0, "optionality": 0.5, "risk": 1.0, "fatigue": 1.0},
            low_action_threshold=0.0, high_action_threshold=0.2, queue_threshold=0.05)
        outbox = OutboxStore(Path("outbox"))
        dispatcher = CommitDispatcher({DraftType.POST: commit_post, DraftType.REPLY: commit_reply,
            DraftType.QUOTE: commit_post, DraftType.LIKE: commit_like, DraftType.FOLLOW: commit_follow,
            DraftType.MUTE: commit_mute, DraftType.BLOCK: commit_block})
        toolset = MagentaAgent(outbox=outbox, policy=policy, memory_policy=MemoryPolicy(), commit_dispatcher=dispatcher)
        state_store = AgentStateStore(Path("state/agent_state.json"))
        telemetry = TelemetryStore(Path("state/telemetry.jsonl"))
        run_queue_once(toolset, state_store, telemetry, outbox)
        return True
    except Exception as e:
        logger.error(f"Queue failed: {e}")
        return False

def run_cleanup_cycle():
    """Run cleanup of stale drafts from both filesystem and Letta archival memory."""
    try:
        from flow import OutboxStore
        from tools.outbox_tools import outbox_purge_stale_drafts

        # Cleanup filesystem-backed outbox
        outbox = OutboxStore(Path("outbox"))
        fs_purged = outbox.purge_stale_drafts(max_age_hours=24)
        logger.info(f"Filesystem outbox: purged {fs_purged} stale drafts")

        # Cleanup Letta archival memory
        try:
            result = outbox_purge_stale_drafts(max_age_hours=24)
            logger.info(f"Letta archival memory: {result}")
        except Exception as e:
            logger.warning(f"Letta archival cleanup skipped: {e}")

        return True
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Magenta Heartbeat")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--task", type=str)
    args = parser.parse_args()
    
    get_config("config.yaml")
    letta_cfg = get_letta_config()
    client_params = {"api_key": letta_cfg["api_key"], "timeout": letta_cfg.get("timeout", 600)}
    if letta_cfg.get("base_url"):
        client_params["base_url"] = letta_cfg["base_url"]
    client = Letta(**client_params)
    agent_id = letta_cfg["agent_id"]
    
    store = ScheduleStore(Path("state/schedules.json"))
    schedules = init_schedules(store)
    
    if args.task:
        if args.task not in HEARTBEAT_CONFIG:
            sys.exit(1)
        config = HEARTBEAT_CONFIG[args.task]
        if config.get("run_queue"):
            run_queue_cycle()
        else:
            run_heartbeat_prompt(client, agent_id, config["prompt"])
        sys.exit(0)
    
    running = True
    def sig_handler(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    
    logger.info("Magenta heartbeat started")
    while running:
        now = time.time()
        for task_name, next_run in schedules.items():
            if next_run <= now:
                config = HEARTBEAT_CONFIG[task_name]

                # Check skip count for observe_and_act task
                if task_name == "observe_and_act":
                    skip_count = store.get_skip_count(task_name)
                    if skip_count > 0:
                        store.set_skip_count(task_name, skip_count - 1)
                        logger.info(f"Skipping observe_and_act cycle ({skip_count - 1} skips remaining)")
                        new_next = calculate_next_run(config, now)
                        schedules[task_name] = new_next
                        store.mark_executed(task_name, new_next)
                        continue

                logger.info(f"Running: {config['description']}")
                if config.get("run_queue"):
                    run_queue_cycle()
                elif config.get("run_cleanup"):
                    run_cleanup_cycle()
                else:
                    run_heartbeat_prompt(client, agent_id, config["prompt"])

                # After observe_and_act, check if we should skip future polls
                if task_name == "observe_and_act":
                    try:
                        from flow.state import AgentStateStore
                        state_store = AgentStateStore(Path("state/agent_state.json"))
                        agent_state = state_store.load()
                        if agent_state.consecutive_unchanged_polls >= 3:
                            store.set_skip_count(task_name, 2)
                            logger.info("Notifications unchanged for 3+ polls, will skip next 2 cycles")
                    except Exception as e:
                        logger.warning(f"Could not check poll state: {e}")

                new_next = calculate_next_run(config, now)
                schedules[task_name] = new_next
                store.mark_executed(task_name, new_next)
                logger.info(f"Next {task_name} in {(new_next-now)/3600:.2f}h")
                if args.once:
                    running = False
                    break
        if running:
            next_due = min(schedules.values())
            time.sleep(max(1, min(10, next_due - time.time())))
    logger.info("Heartbeat stopped")

if __name__ == "__main__":
    main()
