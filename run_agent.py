#!/usr/bin/env python3
"""Minimal runner wiring the gated flow with default toolset."""

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
)
from flow.commit import CommitDispatcher
from flow.models import DraftType
from flow.commit_handlers import (
    commit_block,
    commit_follow,
    commit_like,
    commit_mute,
    commit_post,
    commit_reply,
)
from agent import MagentaAgent


def main() -> None:
    get_config("config.yaml")
    policy = DecisionPolicy(
        salience_config=SalienceConfig(weights={"delta_u": 0.4, "risk": -0.4}),
        j_weights={"voi": 1.0, "optionality": 0.5, "risk": 1.0, "fatigue": 1.0},
        low_action_threshold=0.0,
        high_action_threshold=0.2,
        queue_threshold=0.05,
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

    run_once(toolset, state_store, telemetry, outbox)


if __name__ == "__main__":
    main()
