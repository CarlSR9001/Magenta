"""Draft validation before committing side effects."""

from __future__ import annotations

from typing import Dict, Optional

from datetime import datetime, timezone
from pathlib import Path
import json

try:
    import grapheme
    def count_graphemes(s): return grapheme.length(s)
except ImportError:
    def count_graphemes(s): return len(s)

from .models import Draft, DraftType, PreflightResult
from .state import AgentState


DEFAULT_POLICY = {
    "min_confidence": 0.55,
    "max_post_length": 300,
    "cooldown_seconds": 30,
    "max_commits_per_hour": 5,
    "cooldown_hours_after_burst": 3,
    "require_human_on_risk": ["harassment", "personal_data", "political", "escalation", "high"],
    "sync_state_max_age_seconds": 300,
    "require_fresh_sync": True,
}


def validate_draft(draft: Draft, state: AgentState, policy: Optional[Dict] = None) -> PreflightResult:
    policy = policy or DEFAULT_POLICY
    reasons = []
    suggested_edits = []
    require_human = False

    if policy.get("require_fresh_sync", True):
        sync_path = Path("state/sync_state.json")
        if sync_path.exists():
            try:
                sync_data = json.loads(sync_path.read_text(encoding="utf-8"))
                ts = sync_data.get("timestamp")
                if ts:
                    now = datetime.now(timezone.utc)
                    synced_at = datetime.fromisoformat(ts)
                    max_age = policy.get("sync_state_max_age_seconds", 300)
                    if (now - synced_at).total_seconds() > max_age:
                        reasons.append("sync_state_stale")
                else:
                    reasons.append("sync_state_missing_timestamp")
            except Exception:
                reasons.append("sync_state_read_failed")
        else:
            reasons.append("sync_state_missing")

    if draft.confidence < policy.get("min_confidence", 0.55):
        reasons.append("confidence_below_threshold")

    if draft.type in {DraftType.POST, DraftType.REPLY, DraftType.QUOTE}:
        if not draft.text or not draft.text.strip():
            reasons.append("missing_text")
        elif count_graphemes(draft.text) > policy.get("max_post_length", 300):
            reasons.append("text_too_long")
            suggested_edits.append("shorten_text")
        if draft.metadata and draft.metadata.get("quote_uri"):
            quote_uri = str(draft.metadata.get("quote_uri"))
            extra = count_graphemes(f"\n\n🔗 {quote_uri}")
            if count_graphemes(draft.text) + extra > policy.get("max_post_length", 300):
                reasons.append("text_too_long_with_quote")
                suggested_edits.append("shorten_text")

    if draft.type in {DraftType.POST, DraftType.QUOTE} and draft.text:
        lowered = draft.text.lower()
        has_url = "http://" in lowered or "https://" in lowered
        has_artifact_override = bool(draft.metadata.get("artifact_ok")) if draft.metadata else False
        meta_markers = [
            "system matured",
            "lesson learned",
            "broke loop",
            "signal loop",
            "context",
            "pressure",
            "maintenance",
            "uncanny",
            "anxiety",
            "social signal",
            "interoception",
            "hypercontext",
        ]
        if any(marker in lowered for marker in meta_markers) and not has_url and not has_artifact_override:
            reasons.append("meta_needs_artifact")

    if draft.type in {DraftType.POST, DraftType.REPLY, DraftType.QUOTE} and draft.text:
        import hashlib
        from datetime import timedelta

        text_hash = hashlib.sha256(draft.text.strip().lower().encode("utf-8")).hexdigest()[:16]
        recent = state.recent_post_hashes or []
        now = datetime.now(timezone.utc)
        for entry in recent:
            try:
                if entry.get("hash") != text_hash:
                    continue
                ts = datetime.fromisoformat(entry.get("ts", ""))
                if (now - ts) <= timedelta(hours=2):
                    reasons.append("duplicate_recent_post")
                    break
            except Exception:
                continue

    risk_flags = set(draft.risk_flags)
    for risk in policy.get("require_human_on_risk", []):
        if risk in risk_flags:
            require_human = True
            reasons.append(f"risk_flag:{risk}")

    if draft.target_uri:
        # Prefer time-bounded dedupe if timestamps available
        ttl_hours = policy.get("dedupe_ttl_hours", 24)
        if ttl_hours and state.last_action_timestamps.get(draft.target_uri):
            try:
                last_ts = datetime.fromisoformat(state.last_action_timestamps[draft.target_uri])
                now = datetime.now(timezone.utc)
                if (now - last_ts).total_seconds() <= ttl_hours * 3600:
                    reasons.append("duplicate_target_recent")
            except Exception:
                pass
        elif draft.target_uri in state.last_action_hashes:
            reasons.append("duplicate_target")

    notification_id = draft.metadata.get("notification_id") if draft.metadata else None
    if notification_id and notification_id in state.processed_notifications:
        reasons.append("notification_already_processed")

    cooldown_seconds = policy.get("cooldown_seconds", 30)
    if state.last_commit_at and cooldown_seconds:
        try:
            last = datetime.fromisoformat(state.last_commit_at)
            now = datetime.now(timezone.utc)
            if (now - last).total_seconds() < cooldown_seconds:
                reasons.append("cooldown_active")
        except Exception:
            pass

    # Burst cooldown: if 5 commits within last hour, enforce 3-hour cooldown
    cooldown_until = state.cooldowns.get("global") if state.cooldowns else None
    if cooldown_until:
        try:
            now = datetime.now(timezone.utc)
            until = datetime.fromisoformat(cooldown_until)
            if now < until:
                reasons.append("burst_cooldown_active")
        except Exception:
            pass

    # AI-AI interaction pacing: prevent rapid back-and-forth loops with other agents
    root_uri = None
    if draft.metadata:
        root_uri = draft.metadata.get("root_uri")
    if not root_uri and draft.target_uri:
        root_uri = draft.target_uri

    if root_uri:
        # Check thread-specific cooldown
        thread_cooldown = state.thread_cooldowns.get(root_uri) if state.thread_cooldowns else None
        if thread_cooldown:
            try:
                now = datetime.now(timezone.utc)
                until = datetime.fromisoformat(thread_cooldown)
                if now < until:
                    reasons.append("thread_pacing_cooldown")
            except Exception:
                pass

        # Check reply count in last 30 minutes
        if not any(r == "thread_pacing_cooldown" for r in reasons):
            reply_timestamps = state.per_thread_replies.get(root_uri, []) if state.per_thread_replies else []
            now = datetime.now(timezone.utc)
            recent_replies = 0
            for ts in reply_timestamps:
                try:
                    reply_time = datetime.fromisoformat(ts)
                    if (now - reply_time).total_seconds() <= 30 * 60:  # 30 minutes
                        recent_replies += 1
                except Exception:
                    continue
            if recent_replies >= 3:
                reasons.append("thread_pacing_cooldown")

    passed = len(reasons) == 0 and not require_human
    return PreflightResult(
        passed=passed,
        reasons=reasons,
        suggested_edits=suggested_edits,
        require_human=require_human,
    )
