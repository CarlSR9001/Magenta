"""Toolset protocol and default implementations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .commit import CommitDispatcher, not_implemented_commit
from .models import CandidateAction, Draft, DraftType, Observation, PreflightResult, ScoredAction
from .outbox import OutboxStore
from .preflight import validate_draft
from .salience import SalienceConfig, compute_j_score
from .state import AgentState


@dataclass
class DecisionPolicy:
    salience_config: SalienceConfig
    j_weights: Dict[str, float]
    low_action_threshold: float = 0.0
    high_action_threshold: float = 0.2
    queue_threshold: float = 0.05
    epsilon: float = 0.15
    temperature: float = 0.8


@dataclass
class MemoryPolicy:
    core_threshold: float = 0.7
    summary_threshold: float = 0.45


class Toolset:
    def __init__(
        self,
        outbox: OutboxStore,
        commit_dispatcher: Optional[CommitDispatcher] = None,
        policy: Optional[DecisionPolicy] = None,
        memory_policy: Optional[MemoryPolicy] = None,
    ) -> None:
        self.outbox = outbox
        self.commit_dispatcher = commit_dispatcher or CommitDispatcher({
            DraftType.POST: not_implemented_commit,
            DraftType.REPLY: not_implemented_commit,
            DraftType.QUOTE: not_implemented_commit,
            DraftType.LIKE: not_implemented_commit,
            DraftType.FOLLOW: not_implemented_commit,
            DraftType.MUTE: not_implemented_commit,
            DraftType.BLOCK: not_implemented_commit,
        })
        self.policy = policy
        self.memory_policy = memory_policy or MemoryPolicy()

    # ---- Read-only tools ----
    def observe(self, state: AgentState) -> Observation:
        return Observation(notifications=[], threads=[], profiles=[], local_context={})

    # ---- Decision ----
    def propose_actions(self, observation: Observation, state: AgentState) -> List[CandidateAction]:
        return [
            CandidateAction(
                action_type=DraftType.IGNORE,
                target_uri=None,
                delta_u=0.0,
                voi=0.0,
                optionality=0.0,
                cost=0.0,
                risk=0.0,
                fatigue=0.0,
                salience=0.0,
                notes="default ignore",
                intent="ignore",
            )
        ]

    def score_actions(self, actions: List[CandidateAction]) -> List[ScoredAction]:
        if not self.policy:
            return [ScoredAction(**action.__dict__, j_score=0.0) for action in actions]
        scored: List[ScoredAction] = []
        for action in actions:
            j_score = compute_j_score(
                action.delta_u,
                action.voi,
                action.optionality,
                action.cost,
                action.risk,
                action.fatigue,
                self.policy.j_weights,
            )
            scored.append(ScoredAction(**action.__dict__, j_score=j_score))
        return scored

    def pick_action(self, actions: List[CandidateAction]) -> ScoredAction:
        import random
        import math

        scored = self.score_actions(actions)
        if not scored:
            return ScoredAction(
                action_type=DraftType.IGNORE,
                target_uri=None,
                delta_u=0.0,
                voi=0.0,
                optionality=0.0,
                cost=0.0,
                risk=0.0,
                fatigue=0.0,
                salience=0.0,
                notes="fallback ignore",
                intent="ignore",
                j_score=0.0,
            )

        # Epsilon-greedy: sometimes pick a random option to avoid repetition
        epsilon = getattr(self.policy, "epsilon", 0.15) if self.policy else 0.0
        if epsilon > 0 and random.random() < epsilon:
            return random.choice(scored)

        # Softmax selection with temperature
        temperature = getattr(self.policy, "temperature", 0.8) if self.policy else 0.0
        if temperature and temperature > 0:
            weights = [math.exp(a.j_score / temperature) for a in scored]
            total = sum(weights)
            if total > 0:
                pick = random.random() * total
                upto = 0.0
                for action, weight in zip(scored, weights):
                    upto += weight
                    if upto >= pick:
                        return action

        return sorted(scored, key=lambda a: a.j_score, reverse=True)[0]

    # ---- Draft ----
    def create_draft(self, action: CandidateAction) -> Draft:
        return Draft(
            id=uuid.uuid4().hex[:12],
            type=action.action_type,
            target_uri=action.target_uri,
            text=action.draft_text,
            intent=action.intent or action.notes or "",
            constraints=action.constraints,
            confidence=action.confidence,
            salience=action.salience,
            salience_factors={},
            risk_flags=action.risk_flags,
            abort_if=action.abort_if,
            metadata={**action.metadata, "delta_u": action.delta_u, "voi": action.voi},
        )

    def validate_draft(self, draft: Draft, state: AgentState) -> PreflightResult:
        return validate_draft(draft, state)

    # ---- Commit ----
    def commit(self, draft: Draft):
        return self.commit_dispatcher.commit(draft)
