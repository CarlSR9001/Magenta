#!/usr/bin/env python3
"""Autonomous loop with jitter, RNG action choice, and safety caps."""

import argparse
import random
import time
from pathlib import Path

from config_loader import get_config
from flow import (
    AgentStateStore,
    DecisionPolicy,
    MemoryPolicy,
    OutboxStore,
    SalienceConfig,
    TelemetryStore,
    run_once,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Magenta loop")
    parser.add_argument("--min-seconds", type=int, default=45, help="Min sleep between cycles")
    parser.add_argument("--max-seconds", type=int, default=120, help="Max sleep between cycles")
    parser.add_argument("--action-chance", type=float, default=0.6, help="Chance to run a notification cycle")
    parser.add_argument("--queue-chance", type=float, default=0.2, help="Chance to process queued draft")
    parser.add_argument("--max-runs", type=int, default=0, help="Max cycles (0 = infinite)")
    args = parser.parse_args()

    get_config("config.yaml")

    policy = DecisionPolicy(
        salience_config=SalienceConfig(weights={"delta_u": 0.4, "risk": -0.4}),
        j_weights={"voi": 1.0, "optionality": 0.5, "risk": 1.0, "fatigue": 1.0},
        low_action_threshold=0.0,
        high_action_threshold=0.2,
        queue_threshold=0.05,
        epsilon=0.2,
        temperature=0.9,
    )

    outbox = OutboxStore(Path("outbox"))
    dispatcher = CommitDispatcher(
        {
            DraftType.POST: commit_post,
            DraftType.REPLY: commit_reply,
            DraftType.QUOTE: commit_post,
            DraftType.LIKE: commit_like,
            DraftType.FOLLOW: commit_follow,
            DraftType.MUTE: commit_mute,
            DraftType.BLOCK: commit_block,
        }
    )

    toolset = MagentaAgent(outbox=outbox, policy=policy, memory_policy=MemoryPolicy(), commit_dispatcher=dispatcher)
    state_store = AgentStateStore(Path("state/agent_state.json"))
    telemetry = TelemetryStore(Path("state/telemetry.jsonl"))

    runs = 0
    while True:
        if args.max_runs and runs >= args.max_runs:
            break

        roll = random.random()
        if roll < args.action_chance:
            run_once(toolset, state_store, telemetry, outbox)
        elif roll < args.action_chance + args.queue_chance:
            run_queue_once(toolset, state_store, telemetry, outbox)
        else:
            pass  # do nothing

        runs += 1
        sleep_for = random.randint(args.min_seconds, args.max_seconds)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
