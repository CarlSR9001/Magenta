"""Lightweight agent state (cooldowns, dedupe, per-user caps)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class AgentState:
    last_action_hashes: Dict[str, str] = field(default_factory=dict)
    per_user_counts: Dict[str, int] = field(default_factory=dict)
    per_user_last_interaction: Dict[str, str] = field(default_factory=dict)
    consented_users: Dict[str, bool] = field(default_factory=dict)
    cooldowns: Dict[str, str] = field(default_factory=dict)
    processed_notifications: List[str] = field(default_factory=list)
    last_commit_at: Optional[str] = None
    recent_commit_times: List[str] = field(default_factory=list)
    # New state tracking fields
    responded_uris: Set[str] = field(default_factory=set)
    notification_poll_hash: Optional[str] = None
    consecutive_unchanged_polls: int = 0
    per_thread_replies: Dict[str, List[str]] = field(default_factory=dict)
    thread_cooldowns: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "last_action_hashes": self.last_action_hashes,
            "per_user_counts": self.per_user_counts,
            "per_user_last_interaction": self.per_user_last_interaction,
            "consented_users": self.consented_users,
            "cooldowns": self.cooldowns,
            "processed_notifications": self.processed_notifications,
            "last_commit_at": self.last_commit_at,
            "recent_commit_times": self.recent_commit_times,
            "responded_uris": list(self.responded_uris),
            "notification_poll_hash": self.notification_poll_hash,
            "consecutive_unchanged_polls": self.consecutive_unchanged_polls,
            "per_thread_replies": self.per_thread_replies,
            "thread_cooldowns": self.thread_cooldowns,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        return cls(
            last_action_hashes=data.get("last_action_hashes", {}),
            per_user_counts=data.get("per_user_counts", {}),
            per_user_last_interaction=data.get("per_user_last_interaction", {}),
            consented_users=data.get("consented_users", {}),
            cooldowns=data.get("cooldowns", {}),
            processed_notifications=data.get("processed_notifications", []),
            last_commit_at=data.get("last_commit_at"),
            recent_commit_times=data.get("recent_commit_times", []),
            responded_uris=set(data.get("responded_uris", [])),
            notification_poll_hash=data.get("notification_poll_hash"),
            consecutive_unchanged_polls=data.get("consecutive_unchanged_polls", 0),
            per_thread_replies=data.get("per_thread_replies", {}),
            thread_cooldowns=data.get("thread_cooldowns", {}),
        )

    def mark_commit(self) -> None:
        self.last_commit_at = datetime.now(timezone.utc).isoformat()


class AgentStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AgentState:
        if not self.path.exists():
            return AgentState()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return AgentState.from_dict(data)

    def save(self, state: AgentState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
