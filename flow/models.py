"""Core data models for the observe→decide→draft→preflight→commit flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class DraftType(str, Enum):
    REPLY = "reply"
    QUOTE = "quote"
    POST = "post"
    FOLLOW = "follow"
    MUTE = "mute"
    BLOCK = "block"
    LIKE = "like"
    IGNORE = "ignore"
    QUEUE = "queue"


@dataclass
class Draft:
    id: str
    type: DraftType
    target_uri: Optional[str]
    text: Optional[str]
    intent: str
    constraints: List[str] = field(default_factory=list)
    confidence: float = 0.0
    salience: float = 0.0
    salience_factors: Dict[str, float] = field(default_factory=dict)
    risk_flags: List[str] = field(default_factory=list)
    abort_if: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "draft"


@dataclass
class CandidateAction:
    action_type: DraftType
    target_uri: Optional[str]
    delta_u: float
    voi: float
    optionality: float
    cost: float
    risk: float
    fatigue: float
    salience: float
    notes: str = ""
    intent: str = ""
    draft_text: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    abort_if: List[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredAction(CandidateAction):
    j_score: float = 0.0


@dataclass
class PreflightResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)
    suggested_edits: List[str] = field(default_factory=list)
    require_human: bool = False
    need_more_context: bool = False


@dataclass
class Observation:
    notifications: List[Dict[str, Any]]
    threads: List[Dict[str, Any]]
    profiles: List[Dict[str, Any]]
    local_context: Dict[str, Any]
    need_more_context: bool = False
    skip_poll_suggested: bool = False


@dataclass
class CommitResult:
    success: bool
    external_uri: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TelemetryEvent:
    run_id: str
    loop_iter: int
    tools_called: List[str]
    chosen_action: Optional[str]
    j_components: Dict[str, float]
    salience_components: Dict[str, float]
    preflight: Optional[PreflightResult]
    commit_result: Optional[CommitResult]
    abort_reason: Optional[str] = None
