"""Magenta agent implementation using Letta + Bluesky APIs."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from letta_client import Letta

from config_loader import get_letta_config, get_bluesky_config
from flow.bsky_api import BskyApi
from flow.models import CandidateAction, DraftType, Observation
from flow.salience import SalienceConfig, compute_salience
from flow.toolset import Toolset

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Optional[Any]:
    if not text:
        return None
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _assistant_text(messages: List[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "message_type", None) == "assistant_message":
            return getattr(message, "content", "") or ""
    return ""


def _build_reply_ref(thread: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not thread:
        return None
    node = thread.get("thread") or {}
    parent = node.get("post") or {}
    if not parent:
        return None

    root = parent
    cursor = node
    while cursor.get("parent"):
        cursor = cursor.get("parent")
        if cursor and cursor.get("post"):
            root = cursor.get("post")
        else:
            break

    def _ref(post: Dict[str, Any]) -> Dict[str, Any]:
        return {"uri": post.get("uri"), "cid": post.get("cid")}

    return {"root": _ref(root), "parent": _ref(parent)}


def _reason_salience(reason: Optional[str]) -> float:
    if reason in {"mention", "reply"}:
        return 0.65
    if reason == "follow":
        return 0.45
    if reason == "like":
        return 0.25
    if reason == "repost":
        return 0.3
    return 0.1


class MagentaAgent(Toolset):
    def __init__(
        self,
        outbox,
        policy,
        memory_policy,
        commit_dispatcher=None,
        bsky_api: Optional[BskyApi] = None,
        letta_client: Optional[Letta] = None,
        letta_agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(outbox=outbox, policy=policy, memory_policy=memory_policy, commit_dispatcher=commit_dispatcher)
        if bsky_api is None:
            bsky_cfg = get_bluesky_config()
            bsky_api = BskyApi(
                username=bsky_cfg.get("username"),
                password=bsky_cfg.get("password"),
                pds_uri=bsky_cfg.get("pds_uri"),
            )
        self.bsky = bsky_api
        if letta_client is None:
            letta_cfg = get_letta_config()
            params = {"api_key": letta_cfg["api_key"], "timeout": letta_cfg["timeout"]}
            if letta_cfg.get("base_url"):
                params["base_url"] = letta_cfg["base_url"]
            letta_client = Letta(**params)
        self.letta = letta_client
        self.letta_agent_id = letta_agent_id or get_letta_config()["agent_id"]

    def observe(self, state) -> Observation:
        notifications = self.bsky.list_notifications(limit=20)
        threads = []
        profiles = []
        reply_refs: Dict[str, Any] = {}
        consent_updates: Dict[str, bool] = {}

        need_more_context = False
        for notif in notifications[:5]:
            reason = notif.get("reason")
            uri = notif.get("uri")
            actor = notif.get("author", {}).get("handle") or notif.get("author", {}).get("did")
            record = notif.get("record", {}) or {}
            text = record.get("text") if isinstance(record, dict) else None
            if actor and text:
                lowered = text.lower()
                if any(phrase in lowered for phrase in ["you can reply", "feel free", "okay to continue", "ok to continue", "keep responding", "consent", "go ahead"]):
                    consent_updates[actor] = True
            if actor:
                try:
                    profiles.append(self.bsky.get_profile(actor))
                except Exception as exc:
                    logger.warning("Failed to fetch profile for %s: %s", actor, exc)
            if reason in {"mention", "reply"} and uri:
                try:
                    thread = self.bsky.get_post_thread(uri, depth=6, parent_height=3)
                    threads.append(thread)
                    reply_ref = _build_reply_ref(thread)
                    if reply_ref:
                        reply_refs[uri] = reply_ref
                except Exception as exc:
                    logger.warning("Failed to fetch thread for %s: %s", uri, exc)
                    need_more_context = True

        filtered = [n for n in notifications if n.get("uri") not in state.processed_notifications]

        # Compute hash of notification URIs to detect changes
        sorted_uris = sorted(n.get("uri", "") for n in notifications if n.get("uri"))
        current_hash = hashlib.sha256("|".join(sorted_uris).encode()).hexdigest()[:16]

        # Compare to previous poll hash and update state
        skip_poll_suggested = False
        if current_hash == state.notification_poll_hash:
            state.consecutive_unchanged_polls += 1
        else:
            state.consecutive_unchanged_polls = 0
            state.notification_poll_hash = current_hash

        # Suggest skipping if unchanged for 3+ consecutive polls
        if state.consecutive_unchanged_polls >= 3:
            skip_poll_suggested = True

        return Observation(
            notifications=filtered,
            threads=threads,
            profiles=profiles,
            local_context={"reply_refs": reply_refs, "consent_updates": consent_updates},
            need_more_context=need_more_context,
            skip_poll_suggested=skip_poll_suggested,
        )

    def propose_actions(self, observation: Observation, state) -> List[CandidateAction]:
        if not observation.notifications:
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
                    notes="no notifications",
                    intent="ignore",
                )
            ]

        top = observation.notifications[0]
        notif_summary = {
            "reason": top.get("reason"),
            "uri": top.get("uri"),
            "cid": top.get("cid"),
            "author": top.get("author", {}),
            "record": top.get("record", {}),
            "is_read": top.get("isRead"),
            "indexed_at": top.get("indexedAt"),
        }

        reply_refs = observation.local_context.get("reply_refs", {})
        consent_updates = observation.local_context.get("consent_updates", {})
        for actor, consented in consent_updates.items():
            if consented:
                state.consented_users[actor] = True
        reply_ref = reply_refs.get(top.get("uri"))

        actor_id = top.get("author", {}).get("handle") or top.get("author", {}).get("did")
        profile = observation.profiles[:1][0] if observation.profiles else {}
        description = (profile.get("description") or "").lower() if isinstance(profile, dict) else ""
        handle_text = (actor_id or "").lower()
        is_bot = any(token in description for token in ["bot", "agent", "ai", "automated"]) or any(token in handle_text for token in ["bot", "agent", "ai"])
        consented = bool(state.consented_users.get(actor_id))
        prior_replies = int(state.per_user_counts.get(actor_id, 0)) if actor_id else 0

        prompt = {
            "instruction": (
                "Return JSON array of candidate actions. Use only these action_type values: "
                "reply, quote, post, follow, mute, block, like, ignore, queue. "
                "Keep 1-3 candidates. Include fields: action_type, target_uri, text, intent, "
                "constraints (list), confidence (0..1), salience (0..1), delta_u, voi, "
                "optionality, cost, risk, fatigue, risk_flags (list), abort_if (list)."
            ),
            "notification": notif_summary,
            "thread": observation.threads[:1],
            "profiles": observation.profiles[:1],
            "policy": "Be cautious. Prefer queue/ignore for low salience or high risk. Avoid harassment, sensitive topics, or unclear targets.",
            "constraints": [
                "Tools are not thoughts. Drafts are required before any side effect.",
                "If uncertain, return queue or ignore.",
                "If risk_flags contain high, require queue or human.",
                "Do not bother humans unless they directly interacted. Without consent, allow at most one reply.",
            ],
            "context": {
                "actor": actor_id,
                "is_bot": is_bot,
                "consented": consented,
                "prior_replies": prior_replies,
                "direct_interaction": top.get("reason") in {"mention", "reply"},
            },
        }

        message = json.dumps(prompt, ensure_ascii=True)
        try:
            response = self.letta.agents.messages.create(
                agent_id=self.letta_agent_id,
                messages=[{"role": "user", "content": message}],
            )
            content = _assistant_text(getattr(response, "messages", []))
            data = _extract_json(content)
        except Exception as exc:
            logger.error("Letta proposal failed: %s", exc)
            data = None

        candidates: List[CandidateAction] = []
        if isinstance(data, dict):
            data = [data]

        if isinstance(data, list):
            for item in data[:3]:
                try:
                    action_type = DraftType(item.get("action_type", "ignore"))
                except Exception:
                    action_type = DraftType.IGNORE
                target_uri = item.get("target_uri") or top.get("uri")
                salience = float(item.get("salience", 0.0))
                if salience <= 0.0:
                    salience = _reason_salience(top.get("reason"))
                if salience <= 0.0 and self.policy:
                    salience = compute_salience(
                        {
                            "delta_u": float(item.get("delta_u", 0.0)),
                            "risk": float(item.get("risk", 0.0)) * -1.0,
                            "voi": float(item.get("voi", 0.0)),
                        },
                        self.policy.salience_config,
                    )
                delta_u = float(item.get("delta_u", 0.0)) or (0.2 if top.get("reason") in {"mention", "reply"} else 0.05)
                risk = float(item.get("risk", 0.0))
                voi = float(item.get("voi", 0.0)) or (0.1 if observation.need_more_context else 0.0)
                cost = float(item.get("cost", 0.0)) or (0.1 if action_type in {DraftType.REPLY, DraftType.POST, DraftType.QUOTE} else 0.02)
                fatigue = float(item.get("fatigue", 0.0))
                candidates.append(
                    CandidateAction(
                        action_type=action_type,
                        target_uri=target_uri,
                        delta_u=delta_u,
                        voi=voi,
                        optionality=float(item.get("optionality", 0.0)),
                        cost=cost,
                        risk=risk,
                        fatigue=fatigue,
                        salience=salience,
                        notes="letta_generated",
                        intent=item.get("intent", ""),
                        draft_text=item.get("text"),
                        constraints=item.get("constraints", []),
                        risk_flags=item.get("risk_flags", []),
                        abort_if=item.get("abort_if", []),
                        confidence=float(item.get("confidence", 0.0)),
                        metadata={
                            "notification_id": top.get("uri"),
                            "target_uri": target_uri,
                            "cid": top.get("cid"),
                            "actor": top.get("author", {}).get("handle") or top.get("author", {}).get("did"),
                            "reply_to": reply_ref,
                        },
                    )
                )

        if not candidates:
            candidates.append(
                CandidateAction(
                    action_type=DraftType.IGNORE,
                    target_uri=top.get("uri"),
                    delta_u=0.0,
                    voi=0.0,
                    optionality=0.0,
                    cost=0.0,
                    risk=0.0,
                    fatigue=0.0,
                    salience=0.0,
                    notes="fallback ignore",
                    intent="ignore",
                    metadata={"notification_id": top.get("uri")},
                )
            )

        # Enforce consent guardrails for humans: only 1 reply without consent.
        if actor_id and not is_bot and not consented and prior_replies >= 1:
            candidates = [
                c for c in candidates if c.action_type in {DraftType.IGNORE, DraftType.QUEUE}
            ] or candidates

        # Always include ignore as a viable option
        candidates.append(
            CandidateAction(
                action_type=DraftType.IGNORE,
                target_uri=top.get("uri"),
                delta_u=0.0,
                voi=0.0,
                optionality=0.0,
                cost=0.0,
                risk=0.0,
                fatigue=0.0,
                salience=0.0,
                notes="always-available ignore",
                intent="ignore",
                metadata={"notification_id": top.get("uri")},
            )
        )

        return candidates
